"""Cron schedule parser — reads NOTES.MD schedule blocks and checks due jobs.

Parses cron expressions from agent NOTES.MD files and determines which jobs
are due for execution based on their schedule and last run time.

Usage:
    from app.utils.cron_parser import parse_schedule, get_due_jobs

    jobs = parse_schedule(notes_text)
    due = get_due_jobs(jobs, last_runs)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from croniter import croniter
from loguru import logger


def parse_schedule(notes_text: str) -> list[dict[str, str]]:
    """Parse schedule entries from a NOTES.MD schedule: block.

    Expected format:
    ```
    schedule:
      - id: daily-tests
        cron: "0 8 * * *"
        task: "Run full test suite."
        assign_to: builder
    ```

    Returns list of dicts with keys: id, cron, task, assign_to.
    """
    jobs: list[dict[str, str]] = []

    # Find the schedule block (allows blank lines between entries)
    match = re.search(r"^schedule:\s*\n((?:(?:[ \t]+.+|[ \t]*)\n?)*)", notes_text, re.MULTILINE)
    if not match:
        return jobs

    block = match.group(1)
    current_job: dict[str, str] = {}

    for line in block.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- id:"):
            if current_job and "id" in current_job:
                jobs.append(current_job)
            current_job = {"id": stripped.split(":", 1)[1].strip()}
        elif ":" in stripped and current_job:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key in ("cron", "task", "assign_to"):
                current_job[key] = val

    if current_job and "id" in current_job:
        jobs.append(current_job)

    return jobs


def is_due(cron_expr: str, last_run: datetime | None, now: datetime | None = None) -> bool:
    """Check if a cron expression is due for execution.

    Returns True if the job should run based on:
    - The cron expression matches the current time window
    - It hasn't been run since the last matching time
    """
    if now is None:
        now = datetime.now(timezone.utc)

    try:
        cron = croniter(cron_expr, now)
        prev_match = cron.get_prev(datetime)

        if last_run is None:
            return True  # Never run before — due now

        # Job is due if the previous match time is after the last run
        if prev_match.tzinfo is None:
            prev_match = prev_match.replace(tzinfo=timezone.utc)
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=timezone.utc)

        return prev_match > last_run
    except (ValueError, KeyError):
        logger.warning(f"Invalid cron expression: {cron_expr}")
        return False


def get_due_jobs(
    jobs: list[dict[str, str]],
    last_runs: dict[str, str],
) -> list[dict[str, str]]:
    """Filter jobs to only those that are due for execution.

    last_runs: dict mapping job_id to ISO timestamp of last run.
    """
    now = datetime.now(timezone.utc)
    due: list[dict[str, str]] = []

    for job in jobs:
        job_id = job.get("id", "")
        cron_expr = job.get("cron", "")
        if not job_id or not cron_expr:
            continue

        last_run_str = last_runs.get(job_id)
        last_run = None
        if last_run_str:
            try:
                last_run = datetime.fromisoformat(last_run_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        if is_due(cron_expr, last_run, now):
            due.append(job)

    return due


# ── Last-run tracking (file-based) ────────────────────────────────────


def _runs_path() -> Path:
    from app.config import settings
    p = settings.project_root / "data" / "cron_runs.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_last_runs() -> dict[str, str]:
    """Load last-run timestamps from data/cron_runs.json."""
    path = _runs_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_last_run(job_id: str) -> None:
    """Record the current time as the last run for a job."""
    runs = load_last_runs()
    runs[job_id] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _runs_path().write_text(json.dumps(runs, indent=2), encoding="utf-8")
