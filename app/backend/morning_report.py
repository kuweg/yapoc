"""Morning Report writer — the surface humans wake up to.

`MORNING_REPORT.md` lives in master's agent dir and is the single canonical
place to see what YAPOC did while you weren't watching. It is rewritten
(not appended) on every trigger so you always see the *latest* picture.

Triggers (call write_morning_report from these sites):
  - "goal_completed"   — dispatcher finished an autonomous-source task
  - "budget_halt"      — daily_autonomous_budget_usd halted mid-run
  - "stuck"            — stuck detector force-stopped an agent
  - "crash_recovery"   — backend lifespan recovered from a prior crash
  - "evaluator_tick"   — scheduled evaluator run completed

The report is intentionally short and scannable. For deep history, use
`yapoc git checkpoints` (commits) + `search_memory` (vector DB) + the
per-agent MEMORY.MD/HEALTH.MD files.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from loguru import logger as _log

from app.config import settings


REPORT_PATH = settings.agents_dir / "master" / "MORNING_REPORT.md"

_REASON_LABEL = {
    "goal_completed": "Goal completed",
    "budget_halt": "Daily autonomous budget exhausted — paused",
    "stuck": "Stuck detector tripped",
    "crash_recovery": "Recovered from prior crash",
    "evaluator_tick": "Scheduled evaluation completed",
    "manual": "Manual update",
}


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _recent_health_lines(agent_dir: Path, max_lines: int = 10) -> list[str]:
    health = agent_dir / "HEALTH.MD"
    if not health.exists():
        return []
    try:
        text = health.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return lines[-max_lines:]


def _today_autonomous_spend() -> dict:
    """Snapshot today's autonomous spend + task counts. Returns {} on failure."""
    try:
        from app.utils.db import get_db
        db = get_db()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = db.execute(
            """SELECT
                COUNT(*)               AS task_count,
                COALESCE(SUM(cost_usd), 0.0) AS total_cost
               FROM task_queue
               WHERE source IN ('cron', 'goal', 'doctor', 'webhook')
                 AND created_at >= ?""",
            (today,),
        ).fetchone()
        if not row:
            return {}
        return {
            "task_count": int(row["task_count"]),
            "total_cost": float(row["total_cost"]),
        }
    except Exception as exc:
        _log.warning("morning_report: spend query failed ({})", exc)
        return {}


def _resume_md_summary() -> str:
    """Return a one-paragraph summary of RESUME.MD, or '' if none/empty."""
    resume_path = settings.agents_dir / "master" / "RESUME.MD"
    if not resume_path.exists():
        return ""
    try:
        content = resume_path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""
    if not content:
        return ""
    # First 600 chars is enough for a glance.
    return content[:600] + ("…" if len(content) > 600 else "")


def _recent_checkpoint_commits(limit: int = 5) -> list[str]:
    """Return the last N yapoc:* commits as `<sha>  <subject>` lines."""
    try:
        import subprocess
        prefix = settings.git_checkpoint_label_prefix
        out = subprocess.run(
            [
                "git", "log",
                f"--grep=^{prefix}:",
                "-E",
                f"--max-count={limit}",
                "--pretty=format:%h  %s",
            ],
            cwd=str(settings.project_root),
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if out.returncode != 0:
            return []
        return [l for l in out.stdout.splitlines() if l.strip()]
    except Exception as exc:
        _log.debug("morning_report: git log failed ({})", exc)
        return []


def _goals_snapshot() -> dict:
    """Return active/backlog/done goal counts from master's GOALS.MD."""
    path = settings.agents_dir / "master" / "GOALS.MD"
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}

    sections: dict[str, list[str]] = {"Active": [], "Backlog": [], "Done": []}
    current: list[str] | None = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## "):
            name = s[3:].strip()
            current = sections.get(name)
        elif current is not None and (s.startswith("- ") or s.startswith("* ")):
            current.append(s[2:])

    return {k: len(v) for k, v in sections.items()}


def write_morning_report(reason: str, context: dict[str, Any] | None = None) -> Path:
    """Rewrite MORNING_REPORT.md with the latest snapshot.

    Safe to call from any code path; failures are logged but never raised.
    """
    context = context or {}
    label = _REASON_LABEL.get(reason, reason)

    parts: list[str] = []
    parts.append("# YAPOC Morning Report")
    parts.append("")
    parts.append(f"*Updated: {_utc_now_str()} — {label}*")
    parts.append("")

    # Last trigger context block
    if context:
        parts.append("## Last trigger")
        for key, value in context.items():
            line = str(value).replace("\n", " ").strip()[:200]
            parts.append(f"- **{key}**: {line}")
        parts.append("")

    # Today's autonomous spend
    spend = _today_autonomous_spend()
    if spend:
        cap = settings.daily_autonomous_budget_usd
        pct = (spend["total_cost"] / cap * 100) if cap > 0 else 0
        parts.append("## Today's autonomous spend")
        parts.append(
            f"- {spend['task_count']} task(s), "
            f"${spend['total_cost']:.4f} / ${cap:.2f} cap ({pct:.0f}%)"
        )
        parts.append("")

    # Goals snapshot
    goals = _goals_snapshot()
    if goals:
        parts.append("## Goals")
        parts.append(
            f"- Active: {goals.get('Active', 0)} | "
            f"Backlog: {goals.get('Backlog', 0)} | "
            f"Done: {goals.get('Done', 0)}"
        )
        parts.append("")

    # Recent checkpoints
    commits = _recent_checkpoint_commits(limit=5)
    if commits:
        parts.append("## Recent autocheckpoints")
        for c in commits:
            parts.append(f"- `{c}`")
        parts.append("")

    # Recent master health entries
    master_dir = settings.agents_dir / "master"
    health_lines = _recent_health_lines(master_dir, max_lines=8)
    if health_lines:
        parts.append("## Recent master health log")
        for hl in health_lines:
            parts.append(f"- {hl[:200]}")
        parts.append("")

    # RESUME.MD snapshot
    resume = _resume_md_summary()
    if resume:
        parts.append("## Pending work (from RESUME.MD)")
        parts.append("")
        parts.append("```")
        parts.append(resume)
        parts.append("```")
        parts.append("")

    parts.append("---")
    parts.append("")
    parts.append(
        "*This file is auto-rewritten on every trigger. For deep history use "
        "`yapoc git checkpoints` and `search_memory`.*"
    )
    parts.append("")

    content = "\n".join(parts)
    try:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(content, encoding="utf-8")
        _log.bind(reason=reason).info(
            "morning_report: wrote {} ({} bytes)", REPORT_PATH, len(content),
        )
    except OSError as exc:
        _log.warning("morning_report: write failed ({})", exc)
    return REPORT_PATH
