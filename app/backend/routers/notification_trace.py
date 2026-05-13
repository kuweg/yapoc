"""Notification trace router — observability for the notification queue lifecycle.

GET /notifications/trace returns recent enqueue / dedup / drain events so the UI
can show a timeline of how completion notifications flowed through the system.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.backend.services.notification_queue import notification_queue

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/trace")
async def get_trace(
    limit: int = Query(200, ge=1, le=2000),
    session_id: str | None = None,
    since: str | None = None,
) -> dict:
    """Return the most recent notification-queue events, newest first.

    - `limit` caps the number of events returned.
    - `session_id` filters to a single UI session (empty string for non-session events).
    - `since` is an ISO timestamp lower bound (exclusive of older entries).
    """
    events = notification_queue.read_trace(limit=limit, session_id=session_id, since_iso=since)
    return {"events": events, "count": len(events)}
