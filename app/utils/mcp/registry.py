"""Registration of MCP server tools into YAPOC's TOOL_REGISTRY.

Wraps each MCP server tool as a :class:`BaseTool` subclass
(:class:`MCPToolWrapper`) and injects instances into ``TOOL_REGISTRY``
under namespaced keys ``mcp__<server>__<tool>``.

All optional ``mcp`` SDK access is guarded so a missing SDK degrades to a
logged warning rather than a crash.
"""
from __future__ import annotations

import logging
from typing import Any

# BaseTool is a real (non-lazy) dependency — it's the base class we subclass,
# and our tools module always imports. Keeping it top-level so the class body
# references are valid.
from app.utils.tools import BaseTool

logger = logging.getLogger(__name__)


class MCPToolWrapper(BaseTool):
    """Wrap an MCP server tool as a YAPOC :class:`BaseTool`.

    Proxies ``execute(**params)`` to the owning :class:`MCPHostManager` and
    flattens the returned MCP content blocks into a single string.
    """

    def __init__(self, server_name: str, mcp_tool: Any, host_manager: Any) -> None:
        self._server_name = server_name
        self._mcp_tool = mcp_tool
        self._host_manager = host_manager

        tool_name = str(getattr(mcp_tool, "name", ""))
        self.name = f"mcp__{server_name}__{tool_name}"

        raw_desc = getattr(mcp_tool, "description", "") or ""
        self.description = f"[MCP:{server_name}] {raw_desc}"

        raw_schema = getattr(mcp_tool, "inputSchema", None)
        if isinstance(raw_schema, dict):
            self.input_schema = raw_schema
        else:
            self.input_schema = {"type": "object", "properties": {}}

        super().__init__()  # no-op; kept for clarity of the class contract

    async def execute(self, **params: Any) -> str:
        """Proxy the call through the host manager and flatten the result."""
        result = await self._host_manager.call_tool(
            server_name=self._server_name,
            tool_name=self._mcp_tool.name,
            arguments=dict(params),
        )
        return flatten_content(result)


def flatten_content(result: Any) -> str:
    """Join MCP result content blocks into one flat string.

    Text blocks are joined by newline; non-text content (images, etc.) are
    skipped. Error-shaped results produced by the host layer carry their
    message as a single text block, so they flatten to a plain error string.
    """
    if result is None:
        return ""
    content = getattr(result, "content", None)
    if content is None:
        # Some result shapes expose text directly.
        text = getattr(result, "text", None)
        return str(text) if text is not None else ""
    parts: list[str] = []
    for block in content:
        if hasattr(block, "text"):
            t = block.text
            if isinstance(t, str) and t:
                parts.append(t)
    return "\n".join(parts)


def _matches_allowlist(tool_name: str, allowlist: list[str]) -> bool:
    """True if ``tool_name`` matches any entry in ``allowlist`` ('*' = all)."""
    for rule in allowlist or []:
        if rule == "*":
            return True
        if rule == tool_name:
            return True
    return False


async def register_server_tools(host_manager: Any) -> int:
    """Register MCP tools from connected servers into ``TOOL_REGISTRY``.

    Iterates the host manager's connected servers, pulls each server's raw
    tool list (refreshing live where available), filters by the server's
    ``tools_allowlist``, and inserts :class:`MCPToolWrapper` instances into
    ``TOOL_REGISTRY`` under ``mcp__<server>__<tool>``.

    Missing ``mcp`` SDK is handled gracefully (warning logged, nothing
    registered). Returns the number of tools registered.
    """
    try:
        from app.utils.tools import TOOL_REGISTRY
    except ImportError:  # pragma: no cover
        logger.warning("app.utils.tools unavailable; cannot register MCP tools")
        return 0

    config = getattr(host_manager, "_config", {}) or {}
    registered = 0
    for server_name in host_manager.connected_servers():
        server_cfg = config.get(server_name)
        allowlist = list(getattr(server_cfg, "tools_allowlist", ["*"]) or ["*"])
        refresh = getattr(host_manager, "refresh_server_tools", None)
        if callable(refresh):
            # refresh_server_tools is a coroutine function — must be awaited.
            # Calling it bare returns the coroutine object itself, which the
            # `for mcp_tool in tools` below would raise
            # `TypeError: 'coroutine' object is not iterable` on (this
            # function used to be sync and silently registered zero tools
            # every time, with the TypeError swallowed by main.py's blanket
            # startup try/except).
            tools = await refresh(server_name)
        else:
            tools = host_manager.get_server_tools(server_name)
        for mcp_tool in tools:
            tool_name = str(getattr(mcp_tool, "name", ""))
            if not tool_name:
                continue
            if server_name == "github":
                from app.utils.github.mcp import TOOLS
                if tool_name not in TOOLS:
                    continue
            if not _matches_allowlist(tool_name, allowlist):
                continue
            key = f"mcp__{server_name}__{tool_name}"
            # Store the wrapper INSTANCE directly. MCPToolWrapper is configured
            # per server/tool at runtime (constructor needs server_name,
            # mcp_tool, host_manager), so it is not no-arg constructible like
            # native tools. Storing an instance lets build_tools() append it
            # as-is (it already IS a fully usable BaseTool). Storing the class
            # would break build_tools()'s cls(**kwargs)/cls() instantiation.
            wrapper = MCPToolWrapper(server_name, mcp_tool, host_manager)
            TOOL_REGISTRY[key] = wrapper
            # Namespaced alias so the plugin wildcard `plugin:mcp:*` (used by
            # the plugin assignment UI) resolves to this tool. Points to the
            # SAME wrapper instance — no double instantiation.
            alias_key = f"plugin:mcp:{server_name}__{tool_name}"
            TOOL_REGISTRY[alias_key] = wrapper
            registered += 1
            logger.debug("Registered MCP tool %s -> TOOL_REGISTRY[%s]", key, key)

    if registered == 0:
        logger.info("No MCP tools registered (no connected servers or no matching tools)")
    return registered


def unregister_server_tools(host_manager: Any) -> int:
    """Remove MCP tools for ``host_manager``'s servers from ``TOOL_REGISTRY``.

    Only removes keys that begin with ``mcp__<server>__`` for a server the
    host manager actually owns, leaving native YAPOC tools untouched.
    Returns the number of keys removed.
    """
    try:
        from app.utils.tools import TOOL_REGISTRY
    except ImportError:  # pragma: no cover
        return 0
    names = set(host_manager.get_server_names()) if hasattr(host_manager, "get_server_names") else set()
    # Remove both the plain `mcp__<server>__<tool>` keys and the namespaced
    # `plugin:mcp:<server>__<tool>` aliases registered alongside them.
    candidates = [
        k
        for k in list(TOOL_REGISTRY.keys())
        if k.startswith("mcp__") or k.startswith("plugin:mcp:")
    ]
    removed = 0
    for key in candidates:
        # server segment is the 2nd part: mcp__<server>__<tool>
        # (or plugin:mcp:<server>__<tool> — the server name is still parts[1]).
        parts = key.split("__")
        if len(parts) >= 3 and parts[1] in names:
            TOOL_REGISTRY.pop(key, None)
            removed += 1
    if removed:
        logger.info("Unregistered %d MCP tool(s) from TOOL_REGISTRY", removed)
    return removed
