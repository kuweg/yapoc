"""WebSocket manager — task-level event broadcasting.

Maintains a registry of connected WebSocket clients and broadcasts
task lifecycle events (created, update, complete, error) to all of them.

Usage:
    from app.backend.websocket import ws_manager

    # In a route handler or background task:
    await ws_manager.push_event("task_created", {"task_id": "...", ...})
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from app.utils.db import recent_tasks_queue


class WebSocketManager:
    """Manages connected WebSocket clients and broadcasts events."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._session_subscribers: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)
        logger.info(f"WebSocket client connected ({len(self._clients)} total)")
        # Send state sync on connect (recent tasks + pending approvals)
        try:
            recent = recent_tasks_queue(limit=20)
            pending_approvals: list = []
            try:
                from app.backend.approval_queue import get_pending
                pending_approvals = get_pending(limit=20)
            except Exception:
                pass
            await ws.send_text(json.dumps({
                "type": "state_sync",
                "tasks": recent,
                "pending_approvals": pending_approvals,
            }))
        except Exception:
            pass

    async def disconnect(self, ws: WebSocket) -> None:
        await self._unsubscribe_all(ws)
        async with self._lock:
            self._clients.discard(ws)
        logger.info(f"WebSocket client disconnected ({len(self._clients)} total)")

    async def push_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Broadcast an event to all connected clients."""
        message = json.dumps({"type": event_type, **payload})
        async with self._lock:
            clients = list(self._clients)
        dead: list[WebSocket] = []
        for ws in clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)

    async def subscribe_session(self, ws: WebSocket, session_id: str) -> None:
        """Subscribe a client to turn-level events for a specific session."""
        async with self._lock:
            if session_id not in self._session_subscribers:
                self._session_subscribers[session_id] = set()
            self._session_subscribers[session_id].add(ws)
        logger.debug(f"WebSocket subscribed to session {session_id}")

    async def unsubscribe_session(self, ws: WebSocket, session_id: str) -> None:
        """Unsubscribe a client from a session."""
        async with self._lock:
            subs = self._session_subscribers.get(session_id)
            if subs:
                subs.discard(ws)
                if not subs:
                    del self._session_subscribers[session_id]

    async def _unsubscribe_all(self, ws: WebSocket) -> None:
        """Remove a client from all session subscriptions."""
        async with self._lock:
            empty: list[str] = []
            for sid, subs in self._session_subscribers.items():
                subs.discard(ws)
                if not subs:
                    empty.append(sid)
            for sid in empty:
                del self._session_subscribers[sid]

    @property
    def client_count(self) -> int:
        return len(self._clients)


# Singleton
ws_manager = WebSocketManager()


async def websocket_endpoint(ws: WebSocket) -> None:
    """FastAPI WebSocket endpoint handler for /ws."""
    await ws_manager.connect(ws)
    try:
        while True:
            # Keep connection alive; process any client messages (future: subscriptions)
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                msg_type = msg.get("type", "")
                if msg_type == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
                elif msg_type == "subscribe":
                    sid = msg.get("session_id", "")
                    if sid:
                        await ws_manager.subscribe_session(ws, sid)
                        await ws.send_text(json.dumps({"type": "subscribed", "session_id": sid}))
                elif msg_type == "unsubscribe":
                    sid = msg.get("session_id", "")
                    if sid:
                        await ws_manager.unsubscribe_session(ws, sid)
                        await ws.send_text(json.dumps({"type": "unsubscribed", "session_id": sid}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await ws_manager.disconnect(ws)
