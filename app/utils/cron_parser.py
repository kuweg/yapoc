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

# Valid 5-field cron day-of-week integers and their short/long English names.
_WEEKDAYS: dict[str, int] = {
    "sunday": 0, "sun": 0,
    "monday": 1, "mon": 1,
    "tuesday": 2, "tue": 2, "tues": 2,
    "wednesday": 3, "wed": 3,
    "thursday": 4, "thu": 4, "thur": 4, "thurs": 4,
    "friday": 5, "fri": 5,
    "saturday": 6, "sat": 6,
}

# Ordered list of (regex, cron-fields-template) rules for nl_to_cron.
# The regex captures groups that must be substituted into the template.
_NL_RULES: list[tuple[re.Pattern[str], str]] = []


def _add_nl_rule(pattern: str, template: str) -> None:
    """Register a natural-language -> cron rule. Captured groups are filled
    into `template`'s {} placeholders in order."""
    _NL_RULES.append((re.compile(pattern, re.IGNORECASE), template))


# Rules are evaluated top-to-bottom; first match wins. Keep day/hour/minute
# ordering that mirrors a typical English schedule phrase.
_add_nl_rule(r"^every\s+(\d+)\s+minutes?$", "*/{} * * * *")           # every 5 minutes
_add_nl_rule(r"^every\s+(\d+)\s+hours?$", "0 */{} * * *")             # every 2 hours
_add_nl_rule(r"^every\s+(\d+)\s+days?$", "0 0 */{} * *")              # every 3 days
_add_nl_rule(r"^every\s+(\d+)\s+weeks?$", "WEEK")                      # handled specially
_add_nl_rule(r"^every\s+(\d+)\s+months?$", "0 0 1 */{} *")            # every 2 months
_add_nl_rule(r"^every\s+day(?:ly)?$", "0 0 * * *")                    # every day / daily
_add_nl_rule(r"^daily$", "0 0 * * *")
_add_nl_rule(r"^every\s+hour$", "0 * * * *")                          # every hour
_add_nl_rule(r"^weekly$", "0 0 * * 0")
_add_nl_rule(r"^monthly$", "0 0 1 * *")
_add_nl_rule(r"^yearly$", "0 0 1 1 *")
_add_nl_rule(
    r"^(?:every\s+(?:day|morning)|daily)\s+at\s+(\d{1,2}):(\d{2})$",
    "{} {} * * *",
)


def _normalize_expr(expr: str) -> str:
    """Lowercase and strip surrounding punctuation for NL matching."""
    return " ".join(expr.lower().strip().strip(".,;!?").split())


def _is_passthrough(expr: str) -> bool:
    """True if `expr` is already a 5-field croniter expression we should
    pass through untouched."""
    fields = expr.strip().split()
    if len(fields) != 5:
        return False
    for field in fields:
        if field == "*":
            continue
        # Accept simple numeric ranges/stepped values (lazy but safe):
        if all(part.isdigit() for part in field.replace("/", " ").replace("-", " ").split()):
            continue
        return False
    return True


def nl_to_cron(expr: str) -> str:
    """Map a human schedule phrase to a 5-field cron expression, purely.

    Unknown/ambiguous phrases are returned unchanged (defensive — never
    raises). Already-valid 5-field expressions pass through untouched.
    """
    if not expr or not expr.strip():
        return expr

    # Drop a trailing "at HH:MM" style time; handled by the time rule below.
    if _is_passthrough(expr):
        return expr

    for pattern, template in _NL_RULES:
        m = pattern.match(_normalize_expr(expr))
        if not m:
            continue
        if template == "WEEK":
            n = int(m.group(1))
            if n == 1:
                return "0 0 * * 0"
            return expr  # N>1 weeks unsupported — return input unchanged
        return template.format(*m.groups())

    # Weekday names (monday/tue/etc.) -> "0 0 * * N"
    norm = _normalize_expr(expr)
    match = re.fullmatch(r"every\s+([a-z]+)", norm)
    if match:
        name = match.group(1)
        if name in _WEEKDAYS:
            return f"0 0 * * {_WEEKDAYS[name]}"

    # Bare "every monday" handled above; also accept "mondays" plural.
    match = re.fullmatch(r"every\s+([a-z]+s)", norm)
    if match and match.group(1)[:-1] in _WEEKDAYS:
        return f"0 0 * * {_WEEKDAYS[match.group(1)[:-1]]}"

    return expr


def parse_schedule(notes_text: str) -> list[dict[str, Any]]:
    """Parse schedule entries from a NOTES.MD schedule: block.

    Expected format:
    ```
    schedule:
      - id: daily-tests
        cron: "0 8 * * *"
        task: "Run full test suite."
        assign_to: builder
    ```

    expected format:
    ```
    schedule:
      - id: daily-tests
        cron: "0 8 * * *"
        task: "Run full test suite."
        assign_to: builder
        silent: true            # optional — suppress notifications
        script: "poetry run pytest"   # optional — run a shell command instead of an agent
        context_from: prev-job   # optional — chain this job after another's result
        run_only_after: true     # optional — skip until context_from has a done result
    ```

    Returns list of dicts with keys:
    id, cron (converted via nl_to_cron), task, assign_to, plus optional
    silent (bool), script (str), context_from (str), run_only_after (bool).
    A `[SILENT]` tag in the task text sets silent=True and is stripped.
    """
    jobs: list[dict[str, str]] = []

    # Find the schedule block (allows blank lines between entries)
    match = re.search(r"^schedule:\s*\n((?:(?:[ \t]+.+|[ \t]*)\n?)*)", notes_text, re.MULTILINE)
    if not match:
        return jobs

    block = match.group(1)
    current_job: dict[str, Any] = {}

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
            elif key == "silent":
                current_job["silent"] = _parse_bool(val)
            elif key == "script":
                current_job["script"] = val or ""
            elif key == "context_from":
                current_job["context_from"] = val
            elif key == "run_only_after":
                current_job["run_only_after"] = _parse_bool(val)

    if current_job and "id" in current_job:
        jobs.append(current_job)

    # Post-process each job: convert cron via nl_to_cron, honor [SILENT] tag.
    for job in jobs:
        if "cron" in job:
            job["cron"] = nl_to_cron(job["cron"]).strip()
        task_text = job.get("task", "")
        if re.search(r"\[silent\]", task_text, re.IGNORECASE):
            job["silent"] = True
            job["task"] = re.sub(r"\[silent\]", "", task_text, flags=re.IGNORECASE).strip()

    return jobs


def _parse_bool(val: str) -> bool:
    """Parse a single truthy value from a schedule YAML scalar, compact."""
    return val.strip().lower() in ("true", "1")


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
    last_runs: dict[str, Any],
) -> list[dict[str, str]]:
    """Filter jobs to only those that are due for execution.

    last_runs: dict mapping job_id to either a plain ISO timestamp string
    (legacy shape) or a dict with a "last_run" key (escalation shape:
    {"last_run": str, "consecutive_failures": int, "disabled": bool}).
    Both shapes are handled transparently; missing entries are due now.
    """
    now = datetime.now(timezone.utc)
    due: list[dict[str, str]] = []

    for job in jobs:
        job_id = job.get("id", "")
        cron_expr = job.get("cron", "")
        if not job_id or not cron_expr:
            continue

        last_run = _entry_last_run(last_runs.get(job_id))

        if is_due(cron_expr, last_run, now):
            due.append(job)

    return due


# ── Last-run tracking (file-based) ────────────────────────────────────
#
# Each cron_runs.json value is either:
#   - legacy shape: a plain ISO timestamp string
#   - escalation shape: a dict {"last_run", "consecutive_failures",
#     "disabled"} tracking failure escalation.
#
# All readers handle both shapes so an existing plain-string file is NOT
# broken; writers upgrade entries to dicts only when the value is touched.


def _runs_path() -> Path:
    from app.config import settings
    p = settings.project_root / "data" / "cron_runs.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_last_runs() -> dict[str, Any]:
    """Load last-run tracking entries from data/cron_runs.json."""
    path = _runs_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _entry_last_run(entry: Any) -> str | None:
    """Return the effective last-run timestamp for an entry (str or dict)."""
    if isinstance(entry, dict):
        lr = entry.get("last_run")
        return lr if isinstance(lr, str) else None
    if isinstance(entry, str):
        return entry
    return None


def _write_runs(runs: dict[str, Any]) -> None:
    _runs_path().write_text(json.dumps(runs, indent=2), encoding="utf-8")


def save_last_run(job_id: str) -> None:
    """Record the current time as the last run for a job.

    Preserves the escalation shape if the entry is already a dict
    (keeps consecutive_failures/disabled, updates last_run). A legacy
    string or missing entry is upgraded to a dict with failure counters
    reset to zero and disabled=False.
    """
    runs = load_last_runs()
    entry = runs.get(job_id)
    if isinstance(entry, dict):
        entry["last_run"] = _now_str()
        runs[job_id] = entry
    else:
        runs[job_id] = {
            "last_run": _now_str(),
            "consecutive_failures": 0,
            "disabled": False,
        }
    _write_runs(runs)


# ── Failure escalation helpers ────────────────────────────────────────
#
# Records success/failure for each cron job and auto-disables a job after
# DEFAULT_FAILURE_THRESHOLD consecutive failures. The threshold is resolved
# from settings.cron_failure_threshold with a safe default (settings.py is
# integrity-gated so we never depend on it being present).

DEFAULT_FAILURE_THRESHOLD = 3


def failure_threshold() -> int:
    """Return the configured failure threshold, falling back to a default."""
    try:
        from app.config import settings
        return getattr(settings, "cron_failure_threshold", DEFAULT_FAILURE_THRESHOLD)
    except Exception:
        return DEFAULT_FAILURE_THRESHOLD


def record_cron_success(job_id: str) -> None:
    """Record a successful run for a cron job: update last_run, reset
    consecutive_failures and disabled. Upgrades legacy entries to dicts."""
    runs = load_last_runs()
    runs[job_id] = {
        "last_run": _now_str(),
        "consecutive_failures": 0,
        "disabled": False,
    }
    _write_runs(runs)


def record_cron_failure(job_id: str, threshold: int | None = None) -> bool:
    """Increment the consecutive-failure counter for a cron job.

    If the failures reach the threshold, the job is marked disabled=True.
    last_run is left untouched on failure so the schedule is not advanced.

    Returns True if the job became disabled by this failure, else False.
    """
    if not threshold:
        threshold = failure_threshold()
    runs = load_last_runs()
    entry = runs.get(job_id)
    if isinstance(entry, dict):
        failures = int(entry.get("consecutive_failures", 0)) + 1
        entry["consecutive_failures"] = failures
        entry["disabled"] = bool(entry.get("disabled")) or failures >= threshold
        runs[job_id] = entry
    else:
        # Legacy string or missing entry — promote to dict, first failure.
        failures = 1
        runs[job_id] = {
            "last_run": _entry_last_run(entry) or _now_str(),
            "consecutive_failures": failures,
            "disabled": failures >= threshold,
        }
    _write_runs(runs)
    return bool(runs[job_id].get("disabled"))


def get_failure_count(job_id: str) -> int:
    """Return the consecutive-failure count for a job (0 if not tracked)."""
    entry = load_last_runs().get(job_id)
    if isinstance(entry, dict):
        try:
            return int(entry.get("consecutive_failures", 0))
        except (TypeError, ValueError):
            return 0
    return 0


def is_cron_disabled(job_id: str) -> bool:
    """Return True if the job has been auto-disabled (False for legacy string
    or missing entries)."""
    entry = load_last_runs().get(job_id)
    if isinstance(entry, dict):
        return bool(entry.get("disabled"))
    return False
