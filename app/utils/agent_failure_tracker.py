"""Per-agent consecutive-failure tracker.

Implements YAPOC's general "alert me if any agent fails twice in a row" rule.

Unlike cron escalation (which auto-disables a *job* after N failures) and the
supervisor fast-crash circuit breaker (which guards a *process*), this module
tracks consecutive task failures on an *individual agent* basis. Each agent's
state is persisted to a single JSON file (data/agent_failures.json) so the
counter survives restarts and is shared across all agent subprocesses.

State shape (mirrors cron_parser's tolerance idiom — readers handle both the
older plain-string legacy value and the dict form; writers always write dicts):

    data/agent_failures.json: {
      "<agent_name>": {
        "consecutive_failures": int,
        "last_status": "done" | "error",
        "updated_at": "YYYY-MM-DDTHH:MM:SSZ"
      },
      ...
    }

Usage:
    from app.utils import agent_failure_tracker as aft

    # On an agent task finalizing "done":
    aft.record_agent_success(agent_name)

    # On an agent task finalizing "error" — fires ONCE at the threshold:
    if aft.record_agent_failure(agent_name):
        # alert the user (threshold just crossed for this agent)
        ...

    aft.get_failure_count(agent_name)   # inspect without mutating
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Default consecutive-failure count that triggers the user alert.
DEFAULT_FAILURE_THRESHOLD = 2


def _data_path() -> Path:
    """Resolve the state file under <project_root>/data/. Creates the dir."""
    from app.config import settings
    p = settings.project_root / "data" / "agent_failures.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def failure_threshold() -> int:
    """Return the configured threshold, falling back to the default (2).

    settings.agent_failure_threshold is optional; settings.py is
    integrity-gated so we never depend on it being present.
    """
    try:
        from app.config import settings
        return int(getattr(settings, "agent_failure_threshold", DEFAULT_FAILURE_THRESHOLD))
    except Exception:
        return DEFAULT_FAILURE_THRESHOLD


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load() -> dict[str, Any]:
    """Load the tracker state. Tolerant of a missing/corrupt file."""
    path = _data_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # A corrupt state file must never crash the task-finalization path.
        return {}


def _write(state: dict[str, Any]) -> None:
    """Atomically write the tracker state (tmp file + rename)."""
    path = _data_path()
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix="agent_failures_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp, str(path))
    except Exception:
        # Best-effort durability only — never raise into the task path.
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass


def _entry(agent_name: str, state: dict[str, Any]) -> dict[str, Any]:
    """Return the dict entry for an agent, trimming any legacy string value."""
    entry = state.get(agent_name)
    if isinstance(entry, dict):
        return entry
    # Legacy/literal value or missing entry — promote to a clean dict so all
    # writers operate on a uniform shape.
    state[agent_name] = {
        "consecutive_failures": 0,
        "last_status": "",
        "updated_at": _now_str(),
    }
    return state[agent_name]


def record_agent_success(agent_name: str) -> None:
    """Reset the agent's consecutive-failure counter after a successful task."""
    try:
        state = _load()
        entry = _entry(agent_name, state)
        entry["consecutive_failures"] = 0
        entry["last_status"] = "done"
        entry["updated_at"] = _now_str()
        _write(state)
    except Exception:
        # Never let tracking break the underlying task status write.
        pass


def record_agent_failure(agent_name: str, threshold: int | None = None) -> bool:
    """Increment an agent's consecutive-failure counter.

    Returns True exactly at the moment the counter *reaches* the threshold
    (the alert trigger), and False otherwise — so an alert is raised once at
    the 2nd consecutive failure (default threshold) and NOT spammed again on
    3rd/4th+ consecutive failures. The counter resets on a later success via
    ``record_agent_success``.
    """
    if not threshold or threshold < 1:
        threshold = failure_threshold()
    try:
        state = _load()
        entry = _entry(agent_name, state)
        failures = int(entry.get("consecutive_failures", 0)) + 1
        entry["consecutive_failures"] = failures
        entry["last_status"] = "error"
        entry["updated_at"] = _now_str()
        _write(state)
        return failures >= threshold
    except Exception:
        return False


def get_failure_count(agent_name: str) -> int:
    """Return the agent's current consecutive-failure count (0 when untracked)."""
    entry = _load().get(agent_name)
    if isinstance(entry, dict):
        try:
            return int(entry.get("consecutive_failures", 0))
        except (TypeError, ValueError):
            return 0
    return 0
