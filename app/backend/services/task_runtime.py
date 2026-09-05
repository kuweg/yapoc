"""Run identity, durable stream events, and cancellation for every transport."""
from contextvars import ContextVar
import json

from app.utils.db import get_db

current_task_id: ContextVar[str | None] = ContextVar('current_task_id', default=None)


def append_event(task_id: str, event: dict) -> None:
    db = get_db()
    db.execute('INSERT INTO task_events (task_id, payload) VALUES (?, ?)', (task_id, json.dumps(event)))
    db.commit()


def read_events(task_id: str, after: int = 0) -> list[dict]:
    rows = get_db().execute('SELECT seq, payload FROM task_events WHERE task_id=? AND seq>? ORDER BY seq LIMIT 200', (task_id, after)).fetchall()
    return [{'seq': row['seq'], **json.loads(row['payload'])} for row in rows]


def claim_task(task_id: str, session_id: str, now: str) -> bool:
    """Only one dispatcher can acquire a pending row."""
    db = get_db()
    cursor = db.execute(
        "UPDATE task_queue SET status='running', started_at=?, updated_at=?, assigned_agent='master', session_id=? WHERE id=? AND status='pending'",
        (now, now, session_id, task_id),
    )
    db.commit()
    return cursor.rowcount == 1
