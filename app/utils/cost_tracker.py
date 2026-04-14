"""Per-task cost tracking for YAPOC agents.

Writes per-LLM-call cost records to ``COSTS.json`` in each agent directory.
This is additive alongside the existing cumulative ``USAGE.json``.

Schema of ``COSTS.json`` (array of records):

    [
      {
        "task_id":     str,   # timestamp + agent_name if no better ID
        "description": str,   # task description from TASK.MD ## Task section
        "agent_name":  str,
        "tokens_in":   int,
        "tokens_out":  int,
        "cost_usd":    float,
        "timestamp":   str,   # ISO-8601 UTC
        "model_used":  str
      },
      ...
    ]

File locking uses fcntl (POSIX) with a fallback to a simple atomic
write pattern (write to .tmp, rename) for environments where fcntl
is unavailable (e.g. Windows).
"""

from __future__ import annotations

import json
import logging
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

COSTS_FILE = "COSTS.json"

_PRICING_TABLE: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6":              (3.0,   15.0),
    "claude-sonnet-4-5":              (3.0,   15.0),
    "claude-haiku-4-5":               (1.0,    5.0),
    "claude-haiku-4-5-20251001":      (1.0,    5.0),
    "claude-3-haiku-20240307":        (0.25,   1.25),
    "claude-3-5-sonnet-20241022":     (3.0,   15.0),
    "claude-3-5-sonnet-20240620":     (3.0,   15.0),
    "claude-3-opus-20240229":         (15.0,  75.0),
    "claude-3-sonnet-20240229":       (3.0,   15.0),
}


def _calc_cost(
    model: str,
    tokens_in: int,
    tokens_out: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    try:
        from app.utils.adapters.models import ALL_PRICING
        pricing = ALL_PRICING.get(model) or _PRICING_TABLE.get(model)
    except Exception:
        pricing = _PRICING_TABLE.get(model)

    if not pricing:
        return 0.0

    in_rate, out_rate = pricing
    base_input = max(0, tokens_in - cache_creation_tokens - cache_read_tokens)
    return (
        base_input * in_rate
        + cache_creation_tokens * in_rate * 1.25
        + cache_read_tokens * in_rate * 0.1
        + tokens_out * out_rate
    ) / 1_000_000


try:
    import fcntl as _fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False


@contextmanager
def _locked_costs(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)

    if _HAS_FCNTL:
        lock_path = path.with_suffix(".lock")
        lock_fd = open(lock_path, "w")
        try:
            _fcntl.flock(lock_fd, _fcntl.LOCK_EX)
            records = _load_costs_raw(path)
            yield records
            _save_costs_raw(path, records)
        finally:
            _fcntl.flock(lock_fd, _fcntl.LOCK_UN)
            lock_fd.close()
    else:
        records = _load_costs_raw(path)
        yield records
        _save_costs_raw(path, records)


def _load_costs_raw(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("cost_tracker: unreadable %s (%s), starting fresh", path, exc)
        return []


def _save_costs_raw(path: Path, records: list[dict]) -> None:
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(records, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("cost_tracker: write failed for %s: %s", path, exc)
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _parse_task_description(task_content: str) -> str:
    if not task_content:
        return ""

    m = re.search(r"## Task\n(.*?)(?=\n## |\Z)", task_content, re.DOTALL)
    if m:
        text = m.group(1).strip()
        for line in text.splitlines():
            line = line.strip()
            if line:
                return line[:200]

    body = task_content
    fm = re.match(r"^---\s*\n.*?\n---\s*\n?", task_content, re.DOTALL)
    if fm:
        body = task_content[fm.end():]

    for line in body.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line[:200]

    return task_content.strip()[:200]


def _make_task_id(agent_name: str, timestamp: str) -> str:
    safe_ts = re.sub(r"[^0-9TZ\-:]", "", timestamp)
    return f"{agent_name}:{safe_ts}"


def record_cost(
    agent_dir: Path,
    agent_name: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    *,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    task_content: str = "",
    task_id: str = "",
) -> None:
    """Append one cost record to the agent's COSTS.json.

    Called from UsageTracker.record_turn() after every LLM turn.
    Errors are swallowed so they never break the run loop.
    """
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cost = _calc_cost(
            model,
            tokens_in,
            tokens_out,
            cache_creation_tokens,
            cache_read_tokens,
        )
        description = _parse_task_description(task_content)
        tid = task_id or _make_task_id(agent_name, now)

        record: dict[str, Any] = {
            "task_id":     tid,
            "description": description,
            "agent_name":  agent_name,
            "tokens_in":   int(tokens_in or 0),
            "tokens_out":  int(tokens_out or 0),
            "cost_usd":    round(cost, 8),
            "timestamp":   now,
            "model_used":  model,
        }

        costs_path = agent_dir / COSTS_FILE
        with _locked_costs(costs_path) as records:
            records.append(record)

    except Exception as exc:
        log.warning("cost_tracker.record_cost failed for %s: %s", agent_name, exc)


def load_costs(agent_dir: Path) -> list[dict]:
    """Load all cost records for an agent. Returns empty list on error."""
    path = agent_dir / COSTS_FILE
    return _load_costs_raw(path)


def load_all_costs(agents_dir: Path) -> list[dict]:
    """Load and merge cost records from all agent directories.

    Returns a flat list sorted by timestamp descending.
    """
    all_records: list[dict] = []
    try:
        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            records = load_costs(agent_dir)
            all_records.extend(records)
    except Exception as exc:
        log.warning("cost_tracker.load_all_costs failed: %s", exc)

    all_records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return all_records
