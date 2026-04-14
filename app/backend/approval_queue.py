"""Approval queue — persists CONFIRM-tier tool calls awaiting human review.

When an autonomous agent needs to execute a CONFIRM-tier tool and the policy
says "queue", the request is stored here. The UI shows a badge for pending
approvals, and the user can approve/deny via REST endpoints.

Tables added to yapoc.db:
- approval_queue — pending/approved/denied/expired tool call approvals
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from loguru import logger

from app.utils.db import get_db


def _ensure_table() -> None:
    """Create the approval_queue table if it doesn't exist."""
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS approval_queue (
            id          TEXT PRIMARY KEY,
            agent       TEXT NOT NULL,
            tool        TEXT NOT NULL,
            input_json  TEXT NOT NULL,
            task_id     TEXT,
            status      TEXT DEFAULT 'pending',
            created_at  TEXT NOT NULL,
            resolved_at TEXT,
            resolved_by TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_aq_status ON approval_queue(status);
    """)
    db.commit()


def queue_approval(
    *,
    agent: str,
    tool: str,
    tool_input: dict[str, Any],
    task_id: str | None = None,
) -> str:
    """Queue a tool call for human approval. Returns the approval request ID."""
    _ensure_table()
    db = get_db()
    req_id = str(uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.execute(
        """INSERT INTO approval_queue (id, agent, tool, input_json, task_id, status, created_at)
           VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
        (req_id, agent, tool, json.dumps(tool_input), task_id, now),
    )
    db.commit()
    logger.info(f"[APPROVAL QUEUE] {agent}/{tool} queued as {req_id[:8]}…")

    # Push WebSocket notification so the UI shows the approval dialog
    try:
        import asyncio
        from app.backend.websocket import ws_manager
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(ws_manager.push_event("approval_needed", {
                "id": req_id,
                "agent": agent,
                "tool": tool,
                "input_json": json.dumps(tool_input),
                "created_at": now,
            }))
    except Exception:
        pass  # best-effort — don't break the approval flow

    return req_id


def resolve_approval(req_id: str, approved: bool, resolved_by: str = "user") -> dict[str, Any] | None:
    """Approve or deny a queued request. Returns updated row."""
    _ensure_table()
    db = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status = "approved" if approved else "denied"
    db.execute(
        "UPDATE approval_queue SET status = ?, resolved_at = ?, resolved_by = ? WHERE id = ?",
        (status, now, resolved_by, req_id),
    )
    db.commit()
    row = db.execute("SELECT * FROM approval_queue WHERE id = ?", (req_id,)).fetchone()
    return dict(row) if row else None


def get_pending(limit: int = 50) -> list[dict[str, Any]]:
    """Return all pending approval requests."""
    _ensure_table()
    db = get_db()
    rows = db.execute(
        "SELECT * FROM approval_queue WHERE status = 'pending' ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def expire_stale(ttl_seconds: int = 86400) -> int:
    """Auto-deny approvals older than ttl_seconds. Returns count expired."""
    _ensure_table()
    db = get_db()
    now = datetime.now(timezone.utc)
    rows = db.execute(
        "SELECT id, created_at FROM approval_queue WHERE status = 'pending'"
    ).fetchall()
    expired = 0
    for row in rows:
        try:
            created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            if (now - created).total_seconds() > ttl_seconds:
                resolve_approval(row["id"], approved=False, resolved_by="system:expired")
                expired += 1
        except (ValueError, TypeError):
            continue
    if expired:
        logger.info(f"[APPROVAL QUEUE] Expired {expired} stale approvals")
    return expired
