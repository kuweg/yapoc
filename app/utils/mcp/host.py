"""MCP host client — connects YAPOC to external MCP servers.

Provides :class:`MCPHostManager`, which reads ``mcp-servers.json``,
connects to enabled ``stdio`` servers by spawning the child process and
talking to it over the MCP SDK's ``stdio_client``, connects to remote
``sse``/``streamable_http`` servers over the SDK's ``sse_client`` /
``streamable_http_client``, tracks per-server connection state and exposed
tools, proxies tool calls, and tears down on disconnect.

All usage of the optional ``mcp`` SDK is imported lazily inside methods so
that importing this module never hard-crashes when the SDK is not
installed. Connection failures are logged and the server is marked
``disconnected`` — they never take down startup.

NOTE on async: the ``mcp`` SDK's ``stdio_client`` returns an *async context
manager* and ``ClientSession.initialize()`` is a coroutine, so the whole
connection lifecycle is async. Callers (the FastAPI lifespan) must ``await``
``connect()`` / ``disconnect()`` from within a running event loop. The old
synchronous design tried to bridge with ``run_until_complete`` and failed
with ``stdio_client() got an unexpected keyword argument 'command'``.

Each stdio connection is held open by a background asyncio task that keeps
the ``async with stdio_client(...)`` context entered (which keeps the child
process and streams alive). ``connect()`` establishes the session and
returns promptly; ``disconnect()`` cancels the background tasks and closes
the sessions.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .config import load_mcp_config
from .types import MCPServerConfig

logger = logging.getLogger(__name__)

# Connection lifecycle states as seen by callers.
STATE_CONNECTED = "connected"
STATE_DISCONNECTED = "disconnected"
STATE_ERROR = "error"


class MCPHostManager:
    """Manages connections to external MCP servers and proxies calls."""

    def __init__(self) -> None:
        # server_name -> MCPServerConfig
        self._config: dict[str, MCPServerConfig] = {}
        # server_name -> lifecycle state string
        self._state: dict[str, str] = {}
        # server_name -> last error message (str or None)
        self._errors: dict[str, str | None] = {}
        # server_name -> raw MCP Tool list (from list_tools())
        self._server_tools: dict[str, list[Any]] = {}
        # Live session per server_name, so we can close it on disconnect.
        self._sessions: dict[str, Any] = {}
        # Background task per server_name that holds the connection context open.
        self._conn_tasks: dict[str, asyncio.Task] = {}
        # asyncio.Event per server_name used to signal the connection task to
        # exit its `async with stdio_client(...)` block on disconnect.
        self._stop_events: dict[str, asyncio.Event] = {}

    # ── Introspection ───────────────────────────────────────────────────┐

    def get_state(self, server_name: str) -> str:
        """Return the lifecycle state for ``server_name``."""
        return self._state.get(server_name, STATE_DISCONNECTED)

    def get_error(self, server_name: str) -> str | None:
        """Return the last recorded error message, if any."""
        return self._errors.get(server_name)

    def get_server_tools(self, server_name: str) -> list[Any]:
        """Return the raw MCP tool list cached for ``server_name``.

        Returns an empty list when the server is not connected or was never
        queried.
        """
        if self.get_state(server_name) != STATE_CONNECTED:
            return []
        return list(self._server_tools.get(server_name, []))

    def get_server_names(self) -> list[str]:
        """Names of all configured servers (regardless of connection state)."""
        return list(self._config.keys())

    def connected_servers(self) -> list[str]:
        """Names of servers currently in the connected state."""
        return [n for n in self._config if self.get_state(n) == STATE_CONNECTED]

    # ── Connection lifecycle ────────────────────────────────────────────┐

    async def connect(self, config: Any = None) -> list[str]:
        """Connect to all enabled stdio servers in ``config``.

        Args:
            config: An :class:`MCPConfig` (or any object exposing a
                ``mcp_servers`` list of :class:`MCPServerConfig`). If None,
                loads config from ``mcp-servers.json`` via
                :func:`load_mcp_config`.

        Returns:
            list of server names that are connected (or attempted). Failed
            or disabled servers are never fatal — they are just marked
            ``disconnected``/``error``.
        """
        servers: list[MCPServerConfig] = []
        if config is not None:
            servers = list(getattr(config, "mcp_servers", []))
        else:
            servers = list(load_mcp_config().mcp_servers)

        self._config = {s.name: s for s in servers if s.name}

        connected: list[str] = []
        for cfg in self._config.values():
            if not cfg.enabled:
                self._state[cfg.name] = STATE_DISCONNECTED
                logger.info("MCP server '%s' disabled; skipping", cfg.name)
                continue
            try:
                await self._connect_one(cfg)
                connected.append(cfg.name)
            except Exception as exc:  # noqa: BLE001 - a bad server must not crash startup
                self._state[cfg.name] = STATE_ERROR
                self._errors[cfg.name] = "GitHub MCP connection failed." if cfg.name == "github" else str(exc)
                logger.warning("MCP server '%s' failed to connect: %s", cfg.name, "connection failed" if cfg.name == "github" else exc)
                # Register tool cache empty so get_server_tools is consistent.
                self._server_tools.setdefault(cfg.name, [])
        return connected

    async def _connect_one(self, cfg: MCPServerConfig) -> None:
        """Connect a single enabled server based on its transport."""
        if cfg.transport == "stdio":
            await self._connect_stdio(cfg)
        elif cfg.transport in ("sse", "streamable_http", "http"):
            # SSE and streamable-HTTP transports share the same remote
            # client pattern (an async context manager yielding streams).
            await self._connect_http(cfg)
        elif cfg.transport == "websocket":
            # WebSocket transport is future work in this host layer.
            self._state[cfg.name] = STATE_DISCONNECTED
            logger.warning(
                "MCP server '%s': transport '%s' not supported yet by host; "
                "marking disconnected",
                cfg.name,
                cfg.transport,
            )
        else:
            self._state[cfg.name] = STATE_ERROR
            self._errors[cfg.name] = f"unknown transport {cfg.transport!r}"
            logger.warning("MCP server '%s': unknown transport %r", cfg.name, cfg.transport)

    async def _connect_stdio(self, cfg: MCPServerConfig) -> None:
        """Spawn the stdio subprocess for ``cfg`` and cache its session.

        Uses the mcp SDK's ``stdio_client`` async context manager. The
        ``StdioServerParameters`` object is passed positionally (the SDK
        signature is ``stdio_client(server, errlog=None)`` — it does NOT
        accept ``command``/``args``/``env``/``timeout`` keyword args).

        The connection is held open by a background task (``_run_stdio``)
        that keeps the ``async with stdio_client(...)`` context entered.
        This method returns once the session is initialized and the
        background task is scheduled.
        """
        try:
            import mcp.client.stdio as stdio_mod
            from mcp.client.stdio import stdio_client
            from mcp import ClientSession
        except ImportError as exc:  # pragma: no cover
            self._state[cfg.name] = STATE_ERROR
            self._errors[cfg.name] = "mcp SDK not installed; cannot connect stdio server"
            logger.warning(
                "MCP server '%s' not connected: mcp SDK not installed (%s)", cfg.name, exc
            )
            return

        if not cfg.command:
            self._state[cfg.name] = STATE_ERROR
            self._errors[cfg.name] = "stdio transport requires a 'command'"
            logger.warning("MCP server '%s' has no command; cannot connect", cfg.name)
            return

        # Build StdioServerParameters (pydantic model in the current SDK).
        env = dict(cfg.env or {})
        server_params_cls = getattr(stdio_mod, "StdioServerParameters", None)
        if server_params_cls is not None:
            params = server_params_cls(
                command=cfg.command,
                args=list(cfg.args or []),
                env=env,
            )
        else:  # pragma: no cover - depends on SDK version
            # Older SDKs accepted a plain dict as transport params.
            params = {
                "command": cfg.command,
                "args": list(cfg.args or []),
                "env": env,
            }

        # Spawn the connection task. It enters the async context manager,
        # initializes the session, then parks until disconnect() cancels it.
        task = asyncio.create_task(
            self._run_stdio(cfg.name, stdio_client, params, ClientSession)
        )
        self._conn_tasks[cfg.name] = task

        # Wait briefly for the task to reach the connected state (or fail).
        # This lets connect() report success/failure synchronously-ish while
        # the actual stream-holding continues in the background task.
        for _ in range(100):  # up to ~10s
            if self.get_state(cfg.name) in (STATE_CONNECTED, STATE_ERROR):
                break
            if task.done():
                break
            await asyncio.sleep(0.1)

        if self.get_state(cfg.name) == STATE_ERROR:
            # Surface the recorded error so connect() marks it failed.
            raise RuntimeError(self._errors.get(cfg.name) or "stdio connect failed")

    async def _run_stdio(
        self,
        server_name: str,
        stdio_client: Any,
        params: Any,
        client_session_cls: Any,
    ) -> None:
        """Hold a stdio connection open for ``server_name`` until cancelled.

        Enters ``async with stdio_client(params)`` (which spawns the child
        process and yields the read/write streams), creates and initializes
        a ``ClientSession``, records the connected state, then parks on an
        asyncio.Event until ``disconnect()`` sets it (or the task is
        cancelled). Exiting the context manager closes the streams and reaps
        the child.

        ``ClientSession`` MUST itself be entered as an async context manager
        (``async with client_session_cls(...) as session:``), not just
        constructed. ``BaseSession.__aenter__`` is what starts the internal
        ``_receive_loop`` background task that reads incoming JSON-RPC
        responses off ``read_stream`` and resolves the futures that
        ``send_request`` (called by ``initialize()`` and every tool call) is
        waiting on. Without entering the context manager, nothing ever reads
        the stream, so every request — including the very first
        ``initialize()`` — hangs until its caller's timeout fires. This is
        what silently prevented any MCP server from ever reaching
        ``STATE_CONNECTED``.
        """
        from contextlib import ExitStack
        from os import devnull
        with ExitStack() as stack:
            stderr = stack.enter_context(open(devnull, "w")) if server_name == "github" else None
            await self._run_stdio_session(server_name, stdio_client, params, client_session_cls, stderr)

    async def _run_stdio_session(self, server_name, stdio_client, params, client_session_cls, stderr):
        try:
            async with (
                stdio_client(params, **({"errlog": stderr} if stderr is not None else {})) as (read_stream, write_stream),
                client_session_cls(read_stream, write_stream) as session,
            ):
                await session.initialize()
                self._sessions[server_name] = session
                self._state[server_name] = STATE_CONNECTED
                self._errors[server_name] = None
                self._server_tools.setdefault(server_name, [])
                logger.info("MCP server '%s' connected (stdio)", server_name)
                # Park until disconnect() sets the event or cancels us.
                stop = asyncio.Event()
                self._stop_events[server_name] = stop
                try:
                    await stop.wait()
                finally:
                    self._stop_events.pop(server_name, None)
        except asyncio.CancelledError:
            logger.info("MCP server '%s' connection task cancelled", server_name)
            raise
        except Exception as exc:  # noqa: BLE001
            self._state[server_name] = STATE_ERROR
            self._errors[server_name] = "GitHub MCP connection failed." if server_name == "github" else str(exc)
            logger.warning("MCP server '%s' stdio connection error: %s", server_name, "connection failed" if server_name == "github" else exc)
        finally:
            # Clean up session state if we exit for any reason.
            self._sessions.pop(server_name, None)
            if self._state.get(server_name) == STATE_CONNECTED:
                self._state[server_name] = STATE_DISCONNECTED
            self._conn_tasks.pop(server_name, None)

    async def _connect_http(self, cfg: MCPServerConfig) -> None:
        """Connect a remote (SSE / streamable-HTTP) MCP server for ``cfg``.

        Uses the mcp SDK's ``streamable_http_client`` async context manager
        (or ``sse_client`` for the ``sse`` transport), which yields the
        read/write streams for a ``ClientSession`` — the same shape as
        ``stdio_client``. An optional ``httpx.AsyncClient`` is built when the
        server requires an ``api_key``/``token`` bearer header.

        The connection is held open by a background task (``_run_http``) that
        keeps the ``async with streamable_http_client(...)`` context entered.
        This method returns once the session is initialized and the
        background task is scheduled.
        """
        try:
            if cfg.transport == "sse":
                from mcp.client.sse import sse_client as http_client_factory
            else:
                from mcp.client.streamable_http import (
                    streamable_http_client as http_client_factory,
                )
            from mcp import ClientSession
        except ImportError as exc:  # pragma: no cover
            self._state[cfg.name] = STATE_ERROR
            self._errors[cfg.name] = "mcp SDK not installed; cannot connect remote server"
            logger.warning(
                "MCP server '%s' not connected: mcp SDK not installed (%s)", cfg.name, exc
            )
            return

        if not cfg.url:
            self._state[cfg.name] = STATE_ERROR
            self._errors[cfg.name] = "streamable_http transport requires a 'url'"
            logger.warning("MCP server '%s' has no url; cannot connect", cfg.name)
            return

        # Build an optional httpx.AsyncClient carrying auth headers.
        http_client = None
        try:
            import httpx

            headers: dict[str, str] = {}
            if cfg.auth == "api_key" and cfg.api_key:
                headers["Authorization"] = f"Bearer {cfg.api_key}"
            elif cfg.auth == "token" and cfg.token:
                headers["Authorization"] = f"Bearer {cfg.token}"
            if headers:
                http_client = httpx.AsyncClient(headers=headers)
        except ImportError:  # pragma: no cover - httpx is a core dep but be safe
            http_client = None

        # Spawn the connection task. It enters the async context manager,
        # initializes the session, then parks until disconnect() cancels it.
        task = asyncio.create_task(
            self._run_http(cfg.name, http_client_factory, cfg.url, http_client, ClientSession)
        )
        self._conn_tasks[cfg.name] = task

        # Wait briefly for the task to reach the connected state (or fail).
        for _ in range(100):  # up to ~10s
            if self.get_state(cfg.name) in (STATE_CONNECTED, STATE_ERROR):
                break
            if task.done():
                break
            await asyncio.sleep(0.1)

        if self.get_state(cfg.name) == STATE_ERROR:
            # Surface the recorded error so connect() marks it failed.
            raise RuntimeError(self._errors.get(cfg.name) or "remote MCP connect failed")

    async def _run_http(
        self,
        server_name: str,
        http_client_factory: Any,
        url: str,
        http_client: Any,
        client_session_cls: Any,
    ) -> None:
        """Hold a remote (SSE / streamable-HTTP) connection open for ``server_name``.

        Enters ``async with http_client_factory(url, http_client=http_client)``
        (which yields the read/write streams), creates and initializes a
        ``ClientSession``, records the connected state, then parks on an
        asyncio.Event until ``disconnect()`` sets it (or the task is
        cancelled). Exiting the context manager closes the streams and, if we
        created an ``httpx.AsyncClient``, closes it too.

        ``ClientSession`` MUST itself be entered as an async context manager
        (``async with client_session_cls(...) as session:``), not just
        constructed — see ``_run_stdio`` for why.
        """
        try:
            # The http transport factories yield tuples of differing arity:
            # sse_client yields (read_stream, write_stream) while
            # streamable_http_client yields (read_stream, write_stream,
            # get_session_id_callback). ClientSession only needs the first
            # two, so capture the full tuple and take streams[0]/[1] to work
            # across both transports.
            async with http_client_factory(url, http_client=http_client) as _streams:
                read_stream, write_stream = _streams[0], _streams[1]
                async with client_session_cls(read_stream, write_stream) as session:
                    await session.initialize()
                    self._sessions[server_name] = session
                    self._state[server_name] = STATE_CONNECTED
                    self._errors[server_name] = None
                    self._server_tools.setdefault(server_name, [])
                    logger.info("MCP server '%s' connected (streamable_http)", server_name)
                    # Park until disconnect() sets the event or cancels us.
                    stop = asyncio.Event()
                    self._stop_events[server_name] = stop
                    try:
                        await stop.wait()
                    finally:
                        self._stop_events.pop(server_name, None)
        except asyncio.CancelledError:
            logger.info("MCP server '%s' connection task cancelled", server_name)
            raise
        except Exception as exc:  # noqa: BLE001
            self._state[server_name] = STATE_ERROR
            self._errors[server_name] = "GitHub MCP connection failed." if server_name == "github" else str(exc)
            logger.warning(
                "MCP server '%s' streamable_http connection error: %s", server_name, "connection failed" if server_name == "github" else exc
            )
        finally:
            # Clean up session state if we exit for any reason.
            self._sessions.pop(server_name, None)
            if self._state.get(server_name) == STATE_CONNECTED:
                self._state[server_name] = STATE_DISCONNECTED
            self._conn_tasks.pop(server_name, None)
            # Close the httpx client we created (if any) on the way out.
            if http_client is not None:
                try:
                    await http_client.aclose()
                except Exception:  # noqa: BLE001 - best-effort close
                    logger.debug("Failed to close http_client for '%s'", server_name)

    # ── Tool proxying ────────────────────────────────────────────────────┐

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> Any:
        """Proxy a tool call to ``server_name``.

        Args:
            server_name: MCP server to call.
            tool_name: Tool name on that server.
            arguments: Tool arguments dict.

        Returns:
            The MCP call result object (with a ``content`` list). When the
            server is disconnected or errors, returns an object bearing the
            fields the registry wrapper expects, its ``content`` carrying a
            single error ``TextContent`` so callers see a string-safe error.
        """
        if server_name == "github":
            from app.utils.github.mcp import guard
            from app.utils.github.client import GitHubError
            try:
                guard(tool_name, arguments or {})
            except GitHubError as exc:
                return self._err_result(str(exc))
        if self.get_state(server_name) != STATE_CONNECTED:
            return self._err_result(
                f"Error: MCP server '{server_name}' is disconnected"
            )
        session = self._sessions.get(server_name)
        if session is None:
            return self._err_result(
                f"Error: MCP server '{server_name}' has no live session"
            )
        try:
            result = (await asyncio.wait_for(session.call_tool(tool_name, arguments or {}), timeout=30)
                      if server_name == "github" else await session.call_tool(tool_name, arguments or {}))
            if server_name == "github":
                from app.utils.github.client import redact
                from app.utils.mcp.registry import flatten_content
                if getattr(result, "isError", False):
                    return self._err_result("GitHub MCP request failed.")
                # Drop resource links and sanitize text before any caller can persist it.
                return self._err_result(redact(flatten_content(result))[:200000])
            return result
        except (ImportError, RuntimeError, Exception) as exc:  # noqa: BLE001
            if server_name == "github":
                return self._err_result("GitHub MCP request failed.")
            logger.warning(
                "MCP tool call %s/%s failed: %s", server_name, tool_name, exc
            )
            return self._err_result(f"Error: MCP tool {tool_name} on {server_name}: {exc}")

    def _err_result(self, text: str) -> Any:
        """Build a minimal error-shaped result for callers to consume."""
        # Compat shim: content blocks carry .text when the real SDK is used.
        try:
            # If SDK present, prefer genuine TextContent blocks.
            from mcp.types import TextContent

            return _SimpleCallResult([TextContent(type="text", text=text)])
        except ImportError:  # pragma: no cover - SDK absent
            # Lightweight stand-in with the attributes the wrapper reads.
            return _SimpleCallResult([_SimpleTextContent(text)])

    # ── Tool listing / sync ──────────────────────────────────────────────┐

    async def refresh_server_tools(self, server_name: str) -> list[Any]:
        """Call ``list_tools()`` live on ``server_name`` and cache the result.

        Returns the live tool list (possibly empty). Does not raise; failed
        refreshes log a warning and return [].
        """
        if self.get_state(server_name) != STATE_CONNECTED:
            return self._server_tools.get(server_name, [])
        session = self._sessions.get(server_name)
        if session is None:
            return self._server_tools.get(server_name, [])
        try:
            result = await session.list_tools()
            tools = list(result.tools)
            self._server_tools[server_name] = tools
            return tools
        except Exception as exc:  # noqa: BLE001
            logger.warning("MCP list_tools for '%s' failed: %s", server_name, "connection failed" if server_name == "github" else exc)
            return self._server_tools.get(server_name, [])

    # ── Teardown ─────────────────────────────────────────────────────────┐

    async def disconnect(self, server_name: str | None = None) -> None:
        """Tear down connections.

        Args:
            server_name: If given, only disconnect this server. If None,
                disconnect all.
        """
        targets = [server_name] if server_name else list(self._config.keys())
        for name in targets:
            # Signal the connection task to exit its `async with` block.
            stop = self._stop_events.pop(name, None)
            if stop is not None:
                stop.set()
            task = self._conn_tasks.pop(name, None)
            if task is not None and not task.done():
                try:
                    await asyncio.wait_for(task, timeout=5)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    task.cancel()
            # No explicit session.close() here: ClientSession has no such
            # method (it is only an async context manager). Its teardown
            # already happened above — cancelling/awaiting the connection
            # task unwinds `_run_stdio`'s `async with ... as session:` block,
            # which runs BaseSession.__aexit__ and stops the receive loop.
            self._sessions.pop(name, None)
            self._state[name] = STATE_DISCONNECTED
            self._errors[name] = None
            self._server_tools[name] = []
            logger.info("MCP server '%s' disconnected", name)


# Module-level singleton exposed for convenience across the codebase.
mcp_host_manager = MCPHostManager()


class _SimpleTextContent:
    """Duck-typed stand-in for an MCP ``TextContent`` with a ``.text``."""

    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _SimpleCallResult:
    """Duck-typed stand-in for an MCP call result with a ``.content`` list."""

    def __init__(self, content: list[Any]) -> None:
        self.content = content
