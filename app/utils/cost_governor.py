"""Cost governor — daily autonomous budget tracking.

Tracks spending from autonomous tasks (source: cron, goal, doctor) separately
from user-initiated tasks. When the daily autonomous budget is exhausted,
autonomous work pauses while user tasks continue.

Usage:
    from app.utils.cost_governor import is_autonomous_budget_exhausted, get_autonomous_spend_today

    if is_autonomous_budget_exhausted():
        # Skip autonomous work
        pass
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import settings
from app.utils.db import get_db


_AUTONOMOUS_SOURCES = {"cron", "goal", "doctor", "webhook"}


def get_autonomous_spend_today() -> float:
    """Sum cost_usd for autonomous tasks created today (UTC)."""
    db = get_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = db.execute(
        """SELECT COALESCE(SUM(cost_usd), 0.0) as total
           FROM task_queue
           WHERE source IN ('cron', 'goal', 'doctor', 'webhook')
             AND created_at >= ?""",
        (today,),
    ).fetchone()
    return float(row["total"]) if row else 0.0


def is_autonomous_budget_exhausted() -> bool:
    """Check if the daily autonomous budget has been exceeded."""
    budget = settings.daily_autonomous_budget_usd
    if budget <= 0:
        return False
    return get_autonomous_spend_today() >= budget


def record_autonomous_cost(task_id: str, amount: float) -> None:
    """Update a task's cost_usd in the task_queue. Called by dispatcher on completion."""
    from app.utils.db import update_queued_task
    update_queued_task(task_id, cost_usd=amount)


def is_autonomous_source(source: str | None) -> bool:
    """Check if a task source counts as autonomous (costs against daily budget)."""
    return (source or "").lower() in _AUTONOMOUS_SOURCES
