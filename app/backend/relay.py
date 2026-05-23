"""MessageBusRelay — bridges Redis pub/sub to WebSocket clients.

Subscribes to Redis channels and forwards events to connected WebSocket
clients via ``ws_manager``. Replaces the file-watching ``session_event_relay``
and the polling-based ``notification_poller``.

Subscriptions:
    session:*:events  → ws_manager.push_session_event(session_id, event)
    agent:*:status    → ws_manager.push_event("agent_status", ...)
    agent:*:activity  → ws_manager.push_agent_event(name, event)
                        + bounded in-memory ring buffer for HTTP hydration
    system:tasks      → ws_manager.push_event("task_lifecycle", ...)
    system:health     → ws_manager.push_event("health_alert", ...)
"""

from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from typing import Any

from loguru import logger

from app.backend.message_bus import bus
from app.backend.websocket import ws_manager

# Extract session_id from channel name: "session:<id>:events"
_SESSION_PATTERN = re.compile(r"^session:([^:]+):events$")
# Extract agent name from "agent:<name>:activity"
_AGENT_ACTIVITY_PATTERN = re.compile(r"^agent:([^:]+):activity$")

# Per-agent ring buffer size. Bounds memory while keeping enough history
# to hydrate a freshly-opened Live tab with the recent past.
_AGENT_ACTIVITY_BUFFER = 200


class MessageBusRelay:
    """Bridges Redis pub/sub events to connected WebSocket clients."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._shutdown = asyncio.Event()
        # Per-agent ring buffer of recent activity events. Populated by
        # _relay_agent_activity, read by the HTTP /activity endpoint to
        # hydrate the UI on cold load before WS streaming takes over.
        self._agent_activity: dict[str, deque[dict[str, Any]]] = {}

    def get_agent_activity(self, name: str) -> list[dict[str, Any]]:
        """Return a snapshot of recent activity events for an agent."""
        buf = self._agent_activity.get(name)
        return list(buf) if buf else []

    async def start(self) -> None:
        """Start the relay as a background task."""
        if self._task is not None and not self._task.done():
            logger.warning("MessageBusRelay: already running")
            return
        self._task = asyncio.create_task(self._run(), name="message_bus_relay")
        logger.info("MessageBusRelay: started")

    async def stop(self) -> None:
        """Signal the relay to stop and wait for completion."""
        if self._task and not self._task.done():
            self._shutdown.set()
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("MessageBusRelay: stopped")

    async def _run(self) -> None:
        """Main relay loop — subscribe to channels and forward to WebSocket."""
        # We need to create separate sub/pub tasks for each pattern
        # since PubSub.subscribe() blocks the connection for that pubsub.
        tasks = [
            asyncio.create_task(self._relay_session_events(), name="relay_session"),
            asyncio.create_task(self._relay_agent_status(), name="relay_agent_status"),
            asyncio.create_task(self._relay_agent_activity(), name="relay_agent_activity"),
            asyncio.create_task(self._relay_system_tasks(), name="relay_system_tasks"),
            asyncio.create_task(self._relay_system_health(), name="relay_system_health"),
        ]

        # Wait until shutdown is signaled
        await self._shutdown.wait()

        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _relay_session_events(self) -> None:
        """Forward session:*:events to WebSocket per-session subscribers."""
        last_event = time.monotonic()
        _delta_last_push: dict[str, float] = {}  # per-session throttle for text/thinking deltas

        async def _heartbeat() -> None:
            while not self._shutdown.is_set():
                await asyncio.sleep(60)
                if self._shutdown.is_set():
                    break
                since_last = int(time.monotonic() - last_event)
                logger.info(
                    "BusRelay[heartbeat]: session_events alive (last event {}s ago)",
                    since_last,
                )

        hb_task = asyncio.create_task(_heartbeat())
        try:
            while not self._shutdown.is_set():
                try:
                    async for msg in bus.psubscribe("session:*:events"):
                        if self._shutdown.is_set():
                            break
                        last_event = time.monotonic()
                        channel = str(msg.get("channel", ""))
                        m = _SESSION_PATTERN.match(channel)
                        if m:
                            session_id = m.group(1)
                            event_data: dict[str, Any] = msg.get("data", {}) if isinstance(msg.get("data"), dict) else {}
                            ev_type = event_data.get("type", "?") if isinstance(event_data, dict) else "?"
                            # Cap large tool_results at WebSocket boundary to prevent UI lag.
                            # Full content is in TASK.MD / RESULT.MD — agent reads from files.
                            if isinstance(event_data, dict) and ev_type == "tool_result":
                                raw = event_data.get("result", "")
                                if isinstance(raw, str) and len(raw) > 5000:
                                    event_data = {**event_data, "result": raw[:5000] + f"\n... ({len(raw)} total chars, truncated for display)"}
                            if ev_type in ("tool_start", "tool_done"):
                                logger.info(
                                    "BusRelay: session={} event={} → WS",
                                    session_id[:8],
                                    ev_type,
                                )
                            else:
                                logger.debug(
                                    "BusRelay: session={} event={} → WS",
                                    session_id[:8],
                                    ev_type,
                                )
                            # Throttle per-token deltas to 10/sec max (reduce render churn)
                            if ev_type in ("thinking_delta", "message_delta"):
                                now_t = time.monotonic()
                                last_t = _delta_last_push.get(session_id, 0)
                                if now_t - last_t < 0.1:
                                    continue
                                _delta_last_push[session_id] = now_t
                            try:
                                await ws_manager.push_session_event(session_id, event_data)
                            except Exception as _ws_exc:
                                logger.warning(
                                    "MessageBusRelay: push_session_event failed ({}): {}",
                                    session_id[:8],
                                    _ws_exc,
                                )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if self._shutdown.is_set():
                        break
                    logger.warning(
                        "MessageBusRelay: session_events error (reconnecting): {}",
                        exc,
                    )
                    await asyncio.sleep(2)
        finally:
            hb_task.cancel()

    async def _relay_agent_status(self) -> None:
        """Forward agent:*:status to all connected WebSocket clients."""
        last_event = time.monotonic()

        async def _heartbeat() -> None:
            while not self._shutdown.is_set():
                await asyncio.sleep(60)
                if self._shutdown.is_set():
                    break
                since_last = int(time.monotonic() - last_event)
                logger.info(
                    "BusRelay[heartbeat]: agent_status alive (last event {}s ago)",
                    since_last,
                )

        hb_task = asyncio.create_task(_heartbeat())
        try:
            while not self._shutdown.is_set():
                try:
                    async for msg in bus.psubscribe("agent:*:status"):
                        if self._shutdown.is_set():
                            break
                        last_event = time.monotonic()
                        channel = str(msg.get("channel", ""))
                        agent_name = channel.removeprefix("agent:").removesuffix(":status")
                        event_data: Any = msg.get("data")
                        logger.info("BusRelay: agent_status {} → WS", agent_name)
                        try:
                            await ws_manager.push_event("agent_status", {
                                "agent": agent_name,
                                "data": event_data,
                            })
                        except Exception as _ws_exc:
                            logger.warning(
                                "MessageBusRelay: push_event(agent_status) failed: {}",
                                _ws_exc,
                            )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if self._shutdown.is_set():
                        break
                    logger.warning(
                        "MessageBusRelay: agent_status error (reconnecting): {}",
                        exc,
                    )
                    await asyncio.sleep(2)
        finally:
            hb_task.cancel()

    async def _relay_agent_activity(self) -> None:
        """Forward agent:*:activity to per-agent WebSocket subscribers.

        Also maintains an in-memory ring buffer of the last
        ``_AGENT_ACTIVITY_BUFFER`` events per agent, used by the HTTP
        /agents/{name}/activity endpoint to hydrate the UI on cold load.
        Reuses the session-events 10/sec throttle for delta-style events,
        keyed by agent name.
        """
        last_event = time.monotonic()
        _delta_last_push: dict[str, float] = {}

        async def _heartbeat() -> None:
            while not self._shutdown.is_set():
                await asyncio.sleep(60)
                if self._shutdown.is_set():
                    break
                since_last = int(time.monotonic() - last_event)
                logger.info(
                    "BusRelay[heartbeat]: agent_activity alive (last event {}s ago)",
                    since_last,
                )

        hb_task = asyncio.create_task(_heartbeat())
        try:
            while not self._shutdown.is_set():
                try:
                    async for msg in bus.psubscribe("agent:*:activity"):
                        if self._shutdown.is_set():
                            break
                        last_event = time.monotonic()
                        channel = str(msg.get("channel", ""))
                        m = _AGENT_ACTIVITY_PATTERN.match(channel)
                        if not m:
                            continue
                        agent_name = m.group(1)
                        event_data: dict[str, Any] = (
                            msg.get("data", {}) if isinstance(msg.get("data"), dict) else {}
                        )
                        ev_type = event_data.get("type", "?")

                        # Truncate large tool_result payloads at the WS
                        # boundary to keep the UI snappy (full text lives
                        # in the agent's TASK.MD / RESULT.MD).
                        if ev_type == "tool_result":
                            raw = event_data.get("result", "")
                            if isinstance(raw, str) and len(raw) > 5000:
                                event_data = {
                                    **event_data,
                                    "result": raw[:5000]
                                    + f"\n... ({len(raw)} total chars, truncated for display)",
                                }

                        # Throttle delta-style events (10/sec per agent) so a
                        # long thinking turn doesn't evict milestones from the
                        # ring buffer or flood the WS. Milestone events
                        # (turn_*, tool_*, status_*) always pass.
                        if ev_type in ("thinking_delta", "message_delta"):
                            now_t = time.monotonic()
                            last_t = _delta_last_push.get(agent_name, 0.0)
                            if now_t - last_t < 0.1:
                                continue
                            _delta_last_push[agent_name] = now_t

                        buf = self._agent_activity.get(agent_name)
                        if buf is None:
                            buf = deque(maxlen=_AGENT_ACTIVITY_BUFFER)
                            self._agent_activity[agent_name] = buf
                        buf.append(event_data)

                        try:
                            await ws_manager.push_agent_event(agent_name, event_data)
                        except Exception as _ws_exc:
                            logger.warning(
                                "MessageBusRelay: push_agent_event failed ({}): {}",
                                agent_name,
                                _ws_exc,
                            )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if self._shutdown.is_set():
                        break
                    logger.warning(
                        "MessageBusRelay: agent_activity error (reconnecting): {}",
                        exc,
                    )
                    await asyncio.sleep(2)
        finally:
            hb_task.cancel()

    async def _relay_system_tasks(self) -> None:
        """Forward system:tasks to all connected WebSocket clients."""
        last_event = time.monotonic()

        async def _heartbeat() -> None:
            while not self._shutdown.is_set():
                await asyncio.sleep(60)
                if self._shutdown.is_set():
                    break
                since_last = int(time.monotonic() - last_event)
                logger.info(
                    "BusRelay[heartbeat]: system_tasks alive (last event {}s ago)",
                    since_last,
                )

        hb_task = asyncio.create_task(_heartbeat())
        try:
            while not self._shutdown.is_set():
                try:
                    async for msg in bus.subscribe("system:tasks"):
                        if self._shutdown.is_set():
                            break
                        last_event = time.monotonic()
                        event_data: dict[str, Any] = msg.get("data", {}) if isinstance(msg.get("data"), dict) else {}
                        ev_type = event_data.get("type", "?") if isinstance(event_data, dict) else "?"
                        logger.info("BusRelay: system_tasks {} → WS", ev_type)
                        try:
                            await ws_manager.push_event("task_lifecycle", event_data)
                        except Exception as _ws_exc:
                            logger.warning(
                                "MessageBusRelay: push_event(task_lifecycle) failed: {}",
                                _ws_exc,
                            )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if self._shutdown.is_set():
                        break
                    logger.warning(
                        "MessageBusRelay: system_tasks error (reconnecting): {}",
                        exc,
                    )
                    await asyncio.sleep(2)
        finally:
            hb_task.cancel()

    async def _relay_system_health(self) -> None:
        """Forward system:health (doctor alerts) to all connected WebSocket clients."""
        last_event = time.monotonic()

        async def _heartbeat() -> None:
            while not self._shutdown.is_set():
                await asyncio.sleep(60)
                if self._shutdown.is_set():
                    break
                since_last = int(time.monotonic() - last_event)
                logger.info(
                    "BusRelay[heartbeat]: system_health alive (last event {}s ago)",
                    since_last,
                )

        hb_task = asyncio.create_task(_heartbeat())
        try:
            while not self._shutdown.is_set():
                try:
                    async for msg in bus.subscribe("system:health"):
                        if self._shutdown.is_set():
                            break
                        last_event = time.monotonic()
                        event_data: dict[str, Any] = msg.get("data", {}) if isinstance(msg.get("data"), dict) else {}
                        ev_type = event_data.get("type", "?") if isinstance(event_data, dict) else "?"
                        logger.info("BusRelay: system_health {} → WS", ev_type)
                        try:
                            await ws_manager.push_event("health_alert", event_data)
                        except Exception as _ws_exc:
                            logger.warning(
                                "MessageBusRelay: push_event(health_alert) failed: {}",
                                _ws_exc,
                            )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if self._shutdown.is_set():
                        break
                    logger.warning(
                        "MessageBusRelay: system_health error (reconnecting): {}",
                        exc,
                    )
                    await asyncio.sleep(2)
        finally:
            hb_task.cancel()


# Module-level singleton — wired into lifespan in app/backend/main.py
relay = MessageBusRelay()
