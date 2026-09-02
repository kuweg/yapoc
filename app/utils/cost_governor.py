"""Cost governor — daily autonomous + unified global budget tracking.

Tracks spending from autonomous tasks (source: cron, goal, doctor) separately
from user-initiated tasks. When the daily autonomous budget is exhausted,
autonomous work pauses while user tasks continue.

A unified GLOBAL daily cap (``daily_total_budget_usd``) also exists across
ALL task sources via :func:`is_total_budget_exhausted` /
:func:`get_total_spend_today`. The setting is read via ``getattr`` because
``app/config/settings.py`` is gate-protected; it falls back to a safe default
(5.0) when unset.

Usage:
    from app.utils.cost_governor import (
        is_autonomous_budget_exhausted,
        get_autonomous_spend_today,
        is_total_budget_exhausted,
        get_total_spend_today,
    )

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


def get_total_spend_today() -> float:
    """Sum cost_usd for ALL tasks created today (UTC), across every source.

    Unlike ``get_autonomous_spend_today`` there is no source filter — this is
    the unified global spend used for the whole-system daily cap.
    """
    db = get_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = db.execute(
        """SELECT COALESCE(SUM(cost_usd), 0.0) as total
           FROM task_queue
           WHERE created_at >= ?""",
        (today,),
    ).fetchone()
    return float(row["total"]) if row else 0.0


def is_total_budget_exhausted() -> bool:
    """Check whether the unified GLOBAL daily spend cap (across ALL task
    sources) has been exceeded.

    The cap is read from ``settings.daily_total_budget_usd``. ``app/config/
    settings.py`` is gate-protected from agents, so we never assume the
    attribute exists — ``getattr`` falls back to a safe default (5.0). A
    value of 0 or unset means "no cap". The existing per-source autonomous
    budget (``is_autonomous_budget_exhausted``) is intentionally left intact
    and operates independently of this unified cap.
    """
    budget = float(getattr(settings, "daily_total_budget_usd", 5.0) or 0.0)
    if budget <= 0:
        return False
    return get_total_spend_today() >= budget


def record_autonomous_cost(task_id: str, amount: float) -> None:
    """Update a task's cost_usd in the task_queue. Called by dispatcher on completion."""
    from app.utils.db import update_queued_task
    update_queued_task(task_id, cost_usd=amount)


def is_autonomous_source(source: str | None) -> bool:
    """Check if a task source counts as autonomous (costs against daily budget)."""
    return (source or "").lower() in _AUTONOMOUS_SOURCES
