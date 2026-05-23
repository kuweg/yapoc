"""Graph event bus — in-memory event store for the agent topology graph.

Maintains a ring buffer of last 100 graph events and provides methods for
the WebSocket router to push live updates to connected clients.

Exports:
    graph_event_bus: GraphEventBus singleton
    GraphEvent: TypedDict-compatible event schema
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class GraphEvent:
    """An event in the agent topology graph.

    All fields are JSON-serializable. The 'event_type' discriminator
    determines which other fields are populated.
    """

    event_type: str
    source: str
    timestamp: str = ""
    target: str = ""
    task_id: str = ""
    status: str = ""
    level: str = ""
    message: str = ""
    old_status: str = ""
    new_status: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "event_type": self.event_type,
            "source": self.source,
            "timestamp": self.timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if self.target:
            d["target"] = self.target
        if self.task_id:
            d["task_id"] = self.task_id
        if self.status:
            d["status"] = self.status
        if self.level:
            d["level"] = self.level
        if self.message:
            d["message"] = self.message
        if self.old_status:
            d["old_status"] = self.old_status
        if self.new_status:
            d["new_status"] = self.new_status
        return d


@dataclass
class GraphSnapshot:
    """Initial topology snapshot sent on WebSocket connect."""

    agents: list[dict[str, Any]]
    edges: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {"agents": self.agents, "edges": self.edges}


class GraphEventBus:
    """In-memory event bus for graph topology events.

    Keeps a ring buffer of the last ``max_events`` events and notifies
    registered listeners (typically the WebSocket router) when new events
    are emitted.
    """

    def __init__(self, max_events: int = 100) -> None:
        self._events: list[GraphEvent] = []
        self._max_events = max_events
        self._listeners: list[Callable[[dict[str, Any]], Awaitable[None]]] = []
        self._running = False

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the graph event bus.

        Logically marks the bus as running. Subclasses or extensions may
        override this to, e.g., start a background flush loop or connect
        to an external event sink.
        """
        self._running = True

    async def stop(self) -> None:
        """Stop the graph event bus.

        Clears the running flag. Subclasses may override to flush pending
        events or disconnect external sinks.
        """
        self._running = False

    # ── Listeners ────────────────────────────────────────────────────────

    def add_listener(self, listener: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self._listeners = [l for l in self._listeners if l is not listener]

    async def _notify(self, event: GraphEvent) -> None:
        payload = event.to_dict()
        for listener in self._listeners:
            try:
                await listener(payload)
            except Exception:
                pass  # isolated listener failures

    # ── Events ───────────────────────────────────────────────────────────

    def _push(self, event: GraphEvent) -> None:
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events.pop(0)

    async def emit_agent_spawned(self, source: str, target: str) -> None:
        event = GraphEvent(
            event_type="agent_spawned",
            source=source,
            target=target,
        )
        self._push(event)
        await self._notify(event)

    async def emit_agent_died(self, source: str, target: str) -> None:
        event = GraphEvent(
            event_type="agent_died",
            source=source,
            target=target,
        )
        self._push(event)
        await self._notify(event)

    async def emit_task_assigned(self, source: str, target: str, task_id: str) -> None:
        event = GraphEvent(
            event_type="task_assigned",
            source=source,
            target=target,
            task_id=task_id,
        )
        self._push(event)
        await self._notify(event)

    async def emit_task_completed(self, source: str, target: str, task_id: str, status: str) -> None:
        event = GraphEvent(
            event_type="task_completed",
            source=source,
            target=target,
            task_id=task_id,
            status=status,
        )
        self._push(event)
        await self._notify(event)

    async def emit_notification_sent(self, source: str, target: str) -> None:
        event = GraphEvent(
            event_type="notification_sent",
            source=source,
            target=target,
        )
        self._push(event)
        await self._notify(event)

    async def emit_health_logged(self, source: str, level: str, message: str) -> None:
        event = GraphEvent(
            event_type="health_logged",
            source=source,
            level=level,
            message=message,
        )
        self._push(event)
        await self._notify(event)

    async def emit_status_changed(self, source: str, old_status: str, new_status: str) -> None:
        event = GraphEvent(
            event_type="status_changed",
            source=source,
            old_status=old_status,
            new_status=new_status,
        )
        self._push(event)
        await self._notify(event)

    # ── Accessors ────────────────────────────────────────────────────────

    def recent_events(self, count: int = 50) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._events[-count:]]

    async def build_snapshot(self, agents_dir: str | None = None) -> GraphSnapshot:
        """Build a topology snapshot from agent-settings.json and STATUS.json files."""
        from pathlib import Path

        from app.config import settings

        agents_cfg: dict[str, Any] = {}
        try:
            agents_cfg = settings.agent_settings  # dict from agent-settings.json
        except Exception:
            pass

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        known_names: set[str] = set()
        delegation_map: dict[str, list[str]] = {}

        # Build from agent-settings.json
        for name, cfg in agents_cfg.items():
            if name == "__meta__" or not isinstance(cfg, dict):
                continue
            known_names.add(name)

            status = "idle"
            is_alive = False
            status_path = settings.agents_dir / name / "STATUS.json"
            if status_path.exists():
                try:
                    status_data = json.loads(status_path.read_text(encoding="utf-8"))
                    state = status_data.get("state", "terminated")
                    status = state if state in ("idle", "running", "error", "stopped") else "idle"
                    pid = status_data.get("pid")
                    is_alive = bool(pid and _pid_alive(pid))
                except Exception:
                    pass

            node_type: str = name
            if name in ("master",):
                node_type = "master"
            elif name in ("planning",):
                node_type = "planning"
            elif name in ("builder",):
                node_type = "builder"
            elif name in ("keeper",):
                node_type = "keeper"
            elif name in ("cron",):
                node_type = "cron"
            elif name in ("doctor",):
                node_type = "doctor"
            elif name in ("model_manager", "evaluator", "security", "researcher", "librarian"):
                node_type = "ephemeral"

            nodes.append({
                "id": name,
                "name": name,
                "type": node_type,
                "status": status,
                "isAlive": is_alive,
            })

            # Collect delegation targets for edge creation
            targets = cfg.get("delegation_targets", [])
            if targets:
                delegation_map[name] = targets

        # Build edges from delegation targets
        edge_id = 0
        for source_name, targets in delegation_map.items():
            for target_name in targets:
                if target_name in known_names:
                    edges.append({
                        "id": f"delegates_to-{source_name}-{target_name}",
                        "source": source_name,
                        "target": target_name,
                        "type": "delegates_to",
                        "frequency": 1,
                    })
                    edge_id += 1

        # Add master->everyone edges for notification/peer_delegate
        if "master" in known_names:
            for name in known_names:
                if name != "master":
                    edges.append({
                        "id": f"notifies-{name}-master",
                        "source": name,
                        "target": "master",
                        "type": "notifies",
                        "frequency": 1,
                    })

        return GraphSnapshot(agents=nodes, edges=edges)


def _pid_alive(pid: int) -> bool:
    """Check if a PID is still alive (best-effort)."""
    import os as _os

    try:
        _os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError, PermissionError):
        return False


# Singleton
graph_event_bus = GraphEventBus()
