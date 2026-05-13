"""Session event relay — tails subprocess-written events.jsonl files and
forwards each appended event to connected WebSocket subscribers.

Why this exists
---------------
``BaseAgent._emit_event`` writes a JSONL line to
``data/sessions/<session_id>/events.jsonl`` AND tries to push the same event
over the WebSocket via ``ws_manager.push_session_event``. The WS push works
when the agent runs *in the server process* (master), but is a silent no-op
when the agent runs in a subprocess (planning, builder, keeper, …) because
the subprocess has its own ``WebSocketManager`` instance with an empty
subscriber set.

The relay closes that gap. It watches the sessions directory with
``watchdog`` for file modifications, reads the new bytes appended since the
last read, parses each line as a JSON event, and pushes the event through
the *server's* ``ws_manager`` so the UI receives sub-agent thinking deltas,
tool calls, and tool results in real time.

Design choices
--------------
- **Memory-only offsets**: per-file byte offsets are kept in a dict. On
  server restart, every file's offset is initialised to its current size,
  so we never replay backlog after a restart (the UI reconnects fresh
  anyway).
- **Bytes, not lines**: tracking byte offsets means we tolerate partial
  flushes — if an event was half-written when we read, the next read picks
  up where we left off without losing or duplicating data.
- **No watchdog for new directories**: we watch ``data/sessions/``
  recursively so new ``<session_id>/events.jsonl`` files trigger
  ``FileModifiedEvent`` automatically when first written to. New session
  directories don't need explicit registration.
- **Best-effort**: any per-file read/parse error is logged at WARNING and
  skipped. We never crash the server.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from threading import Lock

from loguru import logger
from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from app.config import settings


_EVENTS_FILENAME = "events.jsonl"

# Caps so the unified server log doesn't drown in long text bodies. The full
# event still goes over the WebSocket; only the terminal summary is truncated.
_TEXT_PREVIEW_CHARS = 200
_TOOL_INPUT_PREVIEW_CHARS = 200
_TOOL_RESULT_PREVIEW_CHARS = 200


def _trunc(value: object, cap: int) -> str:
    s = "" if value is None else str(value)
    s = s.replace("\n", " ").replace("\r", " ")
    if len(s) > cap:
        return s[:cap] + "…"
    return s


# thinking/message delta events fire per-chunk (hundreds per turn). Logging
# each one would drown the terminal. Track a per-agent timestamp of the last
# delta log and emit at most one "started generating" line every N seconds.
_DELTA_THROTTLE_SECONDS = 2.0
_delta_last_logged: dict[tuple[str, str], float] = {}


def _log_event_summary(event: dict) -> None:
    """Emit one human-readable loguru INFO line per relayed event.

    The format intentionally mirrors what BaseAgent's in-process logs look
    like for master (``[master    ] Tool spawn_agent done | …``) so the
    terminal becomes a unified stream across all agents.

    Per-chunk text/thinking deltas are throttled — they fire dozens of
    times per turn and would drown the terminal. Tool calls and results
    log every time (low volume, high signal).
    """
    import time as _time

    agent = event.get("agent") or "unknown"
    event_type = event.get("type") or "?"

    if event_type in ("thinking_delta", "message_delta"):
        key = (agent, event_type)
        now = _time.monotonic()
        last = _delta_last_logged.get(key, 0.0)
        if now - last < _DELTA_THROTTLE_SECONDS:
            return
        _delta_last_logged[key] = now
        label = "thinking" if event_type == "thinking_delta" else "message "
        body = _trunc(event.get("text"), _TEXT_PREVIEW_CHARS)
        logger.bind(agent=agent).info("{} | {}", label, body)
    elif event_type == "tool_call":
        name = event.get("name") or "?"
        input_preview = _trunc(event.get("input"), _TOOL_INPUT_PREVIEW_CHARS)
        logger.bind(agent=agent).info("tool_call  | {} {}", name, input_preview)
    elif event_type == "tool_result":
        name = event.get("name") or "?"
        is_error = event.get("is_error", False)
        result_preview = _trunc(
            event.get("content") or event.get("result"),
            _TOOL_RESULT_PREVIEW_CHARS,
        )
        status = "error" if is_error else "ok"
        logger.bind(agent=agent).info(
            "tool_result| {} {} {}", name, status, result_preview
        )
    else:
        # Generic catch-all for any future event types so they aren't silently
        # dropped from the unified log.
        logger.bind(agent=agent).info("{} | {}", event_type, _trunc(event, 200))


class _EventHandler(FileSystemEventHandler):
    """Schedules a coroutine on the main event loop when an events.jsonl
    file is modified.

    Watchdog runs callbacks in its own thread; we hand work back to the
    asyncio loop because the WebSocket manager is async-only.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, relay: "SessionEventRelay") -> None:
        self._loop = loop
        self._relay = relay

    def on_modified(self, event) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.name != _EVENTS_FILENAME:
            return
        asyncio.run_coroutine_threadsafe(self._relay._drain_file(path), self._loop)


class SessionEventRelay:
    """Watches ``data/sessions/`` for new events.jsonl appends and forwards
    each event to subscribed WebSocket clients.
    """

    def __init__(self, sessions_dir: Path | None = None) -> None:
        self._sessions_dir = sessions_dir or (settings.project_root / "data" / "sessions")
        self._offsets: dict[Path, int] = {}
        self._offsets_lock = Lock()
        self._observer: Observer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _session_id_for(self, path: Path) -> str | None:
        # data/sessions/<session_id>/events.jsonl
        try:
            return path.parent.name
        except Exception:
            return None

    def _seed_offsets(self) -> None:
        """On startup, set every existing events.jsonl offset to its
        current size so we don't replay backlog."""
        if not self._sessions_dir.is_dir():
            return
        for session_dir in self._sessions_dir.iterdir():
            ev = session_dir / _EVENTS_FILENAME
            if ev.is_file():
                try:
                    self._offsets[ev] = ev.stat().st_size
                except OSError:
                    self._offsets[ev] = 0

    async def _drain_file(self, path: Path) -> None:
        """Read new appended bytes from ``path`` since the last drain and
        forward each line as a session event.
        """
        session_id = self._session_id_for(path)
        if not session_id:
            return
        try:
            size = path.stat().st_size
        except OSError:
            return

        with self._offsets_lock:
            prev = self._offsets.get(path, 0)
            # Handle truncation / rotation: if file shrunk, reset to start.
            if size < prev:
                prev = 0
            self._offsets[path] = size

        if size <= prev:
            return

        try:
            with open(path, "rb") as f:
                f.seek(prev)
                chunk = f.read(size - prev)
        except OSError as exc:
            logger.warning("session_event_relay: read failed for {}: {}", path, exc)
            return

        # The chunk may not end on a newline if a writer is mid-flush;
        # in that case, roll the offset back to the last newline so we
        # re-read the partial line on the next drain.
        last_newline = chunk.rfind(b"\n")
        if last_newline == -1:
            # No complete line yet — roll back fully.
            with self._offsets_lock:
                self._offsets[path] = prev
            return
        if last_newline + 1 < len(chunk):
            partial_bytes = len(chunk) - (last_newline + 1)
            chunk = chunk[: last_newline + 1]
            with self._offsets_lock:
                self._offsets[path] = size - partial_bytes

        try:
            text = chunk.decode("utf-8", errors="replace")
        except Exception as exc:
            logger.warning("session_event_relay: decode failed for {}: {}", path, exc)
            return

        # Late import — ws_manager lives in the server process and we don't
        # want a circular import at module load time.
        from app.backend.websocket import ws_manager

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "session_event_relay: skip malformed JSON in {}: {}", path, exc
                )
                continue
            # ── Log the event in the *server* process so the user's
            # `yapoc start` terminal shows sub-agent activity alongside
            # master's. Sub-agents are subprocesses — their own loguru
            # output goes to their stderr → OUTPUT.MD, not here. The
            # relay sits in the server process and is the only place
            # where every agent's events converge.
            try:
                _log_event_summary(event)
            except Exception as exc:
                logger.warning(
                    "session_event_relay: per-event log failed: {}", exc
                )
            try:
                await ws_manager.push_session_event(session_id, event)
            except Exception as exc:
                logger.warning(
                    "session_event_relay: push failed for session {}: {}",
                    session_id[:8],
                    exc,
                )

    def start(self) -> None:
        """Start watching the sessions directory. Idempotent."""
        if self._observer is not None:
            return
        self._loop = asyncio.get_event_loop()
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        self._seed_offsets()
        self._observer = Observer()
        handler = _EventHandler(self._loop, self)
        self._observer.schedule(handler, str(self._sessions_dir), recursive=True)
        self._observer.start()
        logger.info(
            "session_event_relay: watching {} (seeded {} existing files)",
            self._sessions_dir,
            len(self._offsets),
        )

    def stop(self) -> None:
        """Stop the watcher (best-effort)."""
        if self._observer is None:
            return
        try:
            self._observer.stop()
            self._observer.join(timeout=5)
        except Exception as exc:
            logger.warning("session_event_relay: stop failed: {}", exc)
        finally:
            self._observer = None


# Module-level singleton — wired into the lifespan in app/backend/main.py.
relay = SessionEventRelay()
