"""Graph view router — WebSocket endpoint for live agent topology.

Provides a dedicated /ws/graph WebSocket endpoint that streams:
1. An ``initial_snapshot`` event on connect with all agents and delegation edges.
2. Live ``graph_event`` messages for topology changes (spawn, die, task, etc.).

Uses FastAPI's native WebSocket support (independent of SSE).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from app.backend.services.graph_events import graph_event_bus

router = APIRouter()

# ── Connected graph-view clients ─────────────────────────────────────────

_graph_clients: set[WebSocket] = set()
_graph_lock = asyncio.Lock()


async def _broadcast_graph_event(payload: dict[str, Any]) -> None:
    """Broadcast a graph event to all connected graph-view clients."""
    message = json.dumps({"type": "graph_event", **payload})
    async with _graph_lock:
        clients = list(_graph_clients)
    dead: list[WebSocket] = []
    for ws in clients:
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)
    if dead:
        async with _graph_lock:
            for ws in dead:
                _graph_clients.discard(ws)


# Register as listener on the graph event bus
graph_event_bus.add_listener(_broadcast_graph_event)


@router.websocket("/ws/graph")
async def graph_websocket_endpoint(ws: WebSocket) -> None:
    """WebSocket endpoint for the graph view.

    1. Accepts the connection.
    2. Builds and sends an ``initial_snapshot`` event.
    3. Sends recent events as a batch.
    4. Keeps connection alive (handles pings).
    5. Broadcasts subsequent graph events to all connected clients.
    """
    await ws.accept()
    async with _graph_lock:
        _graph_clients.add(ws)
    logger.info(f"Graph WS client connected ({len(_graph_clients)} total)")

    try:
        # Send initial snapshot
        snapshot = await graph_event_bus.build_snapshot()
        await ws.send_text(json.dumps({
            "type": "graph_initial_snapshot",
            **snapshot.to_dict(),
        }))

        # Send recent events
        recent = graph_event_bus.recent_events(50)
        if recent:
            await ws.send_text(json.dumps({
                "type": "graph_recent_events",
                "events": recent,
            }))

        # Keep connection alive, handle client messages
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                msg_type = msg.get("type", "")
                if msg_type == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
                elif msg_type == "get_snapshot":
                    snapshot = await graph_event_bus.build_snapshot()
                    await ws.send_text(json.dumps({
                        "type": "graph_initial_snapshot",
                        **snapshot.to_dict(),
                    }))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Graph WS error")
    finally:
        async with _graph_lock:
            _graph_clients.discard(ws)
        logger.info(f"Graph WS client disconnected ({len(_graph_clients)} remaining)")
