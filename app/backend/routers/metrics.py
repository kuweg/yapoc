import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psutil
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.backend.services import _pid_alive, _read_status_json, _parse_health_log, _parse_task
from app.config import settings
from app.utils import AGENTS_DIR
from app.utils.db import get_db

router = APIRouter(prefix="/metrics")


# ── Response models ──────────────────────────────────────────────────────────

class AgentMetrics(BaseModel):
    name: str
    status: str
    is_alive: bool
    task_count: int
    last_active_at: str | None
    health_issues: int


class AgentCpuMetrics(BaseModel):
    agent_name: str
    pid: int | None
    cpu_percent: float
    memory_mb: float
    timestamp: str


# ── Helpers ──────────────────────────────────────────────────────────────────

def _count_memory_entries(agent_dir: Path) -> int:
    """Count non-blank lines in MEMORY.MD as a proxy for completed tasks."""
    memory_path = agent_dir / "MEMORY.MD"
    if not memory_path.exists():
        return 0
    try:
        lines = [
            line.strip()
            for line in memory_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip()
        ]
        return len(lines)
    except OSError:
        return 0


def _last_active_at(agent_dir: Path) -> str | None:
    """Return ISO-format mtime of TASK.MD, or None if the file doesn't exist."""
    task_path = agent_dir / "TASK.MD"
    if not task_path.exists():
        return None
    try:
        mtime = task_path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except OSError:
        return None


def _count_health_issues(agent_dir: Path) -> int:
    """Count ERROR-level lines in HEALTH.MD from the last 24 hours."""
    import re

    health_path = agent_dir / "HEALTH.MD"
    if not health_path.exists():
        return 0
    try:
        raw = health_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0

    pattern = re.compile(_HEALTH_LINE_RE)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    count = 0
    for line in raw.splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        level = m.group("level").upper()
        if level != "ERROR":
            continue
        try:
            ts = datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                count += 1
        except ValueError:
            continue
    return count


def _get_current_status(agent_dir: Path) -> str:
    """Return the current status string from TASK.MD frontmatter, or 'idle'."""
    task = _parse_task(agent_dir)
    if task and task.status:
        return task.status
    return "idle"


def _is_alive(agent_dir: Path) -> bool:
    """Return True if the agent process is currently alive."""
    status = _read_status_json(agent_dir)
    if not status:
        return False
    pid = status.get("pid")
    if not pid:
        return False
    return _pid_alive(pid)


def _build_agent_metrics(agent_dir: Path) -> AgentMetrics:
    """Build an AgentMetrics object for a single agent directory."""
    return AgentMetrics(
        name=agent_dir.name,
        status=_get_current_status(agent_dir),
        is_alive=_is_alive(agent_dir),
        task_count=_count_memory_entries(agent_dir),
        last_active_at=_last_active_at(agent_dir),
        health_issues=_count_health_issues(agent_dir),
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/agents", response_model=list[AgentMetrics])
async def list_agent_metrics():
    """Return metrics for all agents."""
    results: list[AgentMetrics] = []
    for agent_dir in sorted(AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name.startswith("_"):
            continue
        if agent_dir.name == "base":
            continue
        try:
            results.append(_build_agent_metrics(agent_dir))
        except Exception:
            pass
    return results


# ── CPU / memory helpers ─────────────────────────────────────────────────────

def _get_process_cpu_memory(pid: int) -> tuple[float, float]:
    """Return (cpu_percent, memory_mb) for a PID, or (0.0, 0.0) on any error.

    Uses a 0.1-second interval for cpu_percent so the call is non-blocking
    enough for an API endpoint while still returning a meaningful value.
    """
    try:
        proc = psutil.Process(pid)
        cpu = proc.cpu_percent(interval=0.1)
        mem = proc.memory_info().rss / (1024 * 1024)  # bytes → MB
        return cpu, mem
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return 0.0, 0.0


def _build_agent_cpu_metrics(agent_dir: Path) -> AgentCpuMetrics:
    """Build an AgentCpuMetrics object for a single agent directory."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    status = _read_status_json(agent_dir)
    pid: int | None = None
    cpu_percent = 0.0
    memory_mb = 0.0

    if status:
        pid = status.get("pid")
        if pid and _pid_alive(pid):
            cpu_percent, memory_mb = _get_process_cpu_memory(pid)
        else:
            pid = None  # process is dead — normalise to None

    return AgentCpuMetrics(
        agent_name=agent_dir.name,
        pid=pid,
        cpu_percent=round(cpu_percent, 2),
        memory_mb=round(memory_mb, 2),
        timestamp=now,
    )


# ── CPU endpoints ────────────────────────────────────────────────────────────

@router.get("/agents/cpu", response_model=list[AgentCpuMetrics])
async def list_agent_cpu():
    """Return CPU and memory usage for all agents."""
    results: list[AgentCpuMetrics] = []
    for agent_dir in sorted(AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name.startswith("_"):
            continue
        if agent_dir.name == "base":
            continue
        try:
            results.append(_build_agent_cpu_metrics(agent_dir))
        except Exception:
            pass
    return results


@router.get("/agents/{name}", response_model=AgentMetrics)
async def get_agent_metrics(name: str):
    """Return metrics for a specific agent."""
    agent_dir = AGENTS_DIR / name
    if not agent_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    try:
        return _build_agent_metrics(agent_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Cost dashboard ────────────────────────────────────────────────────────────

class AgentUsage(BaseModel):
    name: str
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    total_tool_calls: int
    total_turns: int
    by_model: dict[str, Any]
    last_updated: str | None


class CostDashboard(BaseModel):
    total_cost_usd: float
    agent_usage: list[AgentUsage]
    budget_per_task_usd: float
    budget_per_agent_usd: float


class HierarchyMetrics(BaseModel):
    generated_at: str
    total_task_records: int
    delegated_by_parent: dict[str, int]
    average_completion_seconds_by_parent: dict[str, float]


class BranchCost(BaseModel):
    agent: str
    own_cost_usd: float
    subtree_cost_usd: float
    subtree_tasks: int
    direct_children: list[str]
    depth: int


class BranchCostsResponse(BaseModel):
    generated_at: str
    branches: list[BranchCost]


def _read_usage_json(agent_dir: Path) -> dict[str, Any] | None:
    """Read and return USAGE.json data, or None if missing/corrupt."""
    usage_path = agent_dir / "USAGE.json"
    if not usage_path.exists():
        return None
    try:
        return json.loads(usage_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _build_agent_usage(name: str, data: dict[str, Any]) -> AgentUsage:
    return AgentUsage(
        name=name,
        total_cost_usd=data.get("total_cost_usd", 0.0),
        total_input_tokens=data.get("total_input_tokens", 0),
        total_output_tokens=data.get("total_output_tokens", 0),
        total_tool_calls=data.get("total_tool_calls", 0),
        total_turns=data.get("total_turns", 0),
        by_model=data.get("by_model", {}),
        last_updated=data.get("last_updated"),
    )


@router.get("/usage", response_model=CostDashboard)
async def get_cost_dashboard():
    """Return cost and usage data for all agents."""
    agent_usages: list[AgentUsage] = []
    total_cost = 0.0

    for agent_dir in sorted(AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name.startswith("_"):
            continue
        if agent_dir.name in ("base", "shared"):
            continue
        data = _read_usage_json(agent_dir)
        if data is None:
            continue
        usage = _build_agent_usage(agent_dir.name, data)
        agent_usages.append(usage)
        total_cost += usage.total_cost_usd

    return CostDashboard(
        total_cost_usd=round(total_cost, 6),
        agent_usage=agent_usages,
        budget_per_task_usd=settings.budget_per_task_usd,
        budget_per_agent_usd=settings.budget_per_agent_usd,
    )


@router.get("/usage/{name}", response_model=AgentUsage)
async def get_agent_usage(name: str):
    """Return usage data for a specific agent."""
    agent_dir = AGENTS_DIR / name
    if not agent_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    data = _read_usage_json(agent_dir)
    if data is None:
        return AgentUsage(
            name=name,
            total_cost_usd=0.0,
            total_input_tokens=0,
            total_output_tokens=0,
            total_tool_calls=0,
            total_turns=0,
            by_model={},
            last_updated=None,
        )
    return _build_agent_usage(name, data)


class ObservabilityTotals(BaseModel):
    total_cost_usd: float
    total_tasks: int
    active_agents: int
    agents_with_errors: int
    recent_error_count: int
    # Terminal task failures from SQLite in the last 24h. Counted separately
    # from `recent_error_count` (which is the deduped union with HEALTH.MD) so
    # a dashboard/DB reconciliation check has something exact to compare.
    task_failure_count: int = 0
    # Tasks that ran out of turns and were re-enqueued to continue. NOT
    # failures — the work is still in flight.
    continuation_count: int = 0


class ObservabilityAgent(BaseModel):
    name: str
    status: str
    is_alive: bool
    cost_usd: float
    input_tokens: int
    output_tokens: int
    task_count: int
    health_issues: int
    last_active_at: str | None
    models: list[str]
    task_failures: int = 0
    continuations: int = 0


class ObservabilityError(BaseModel):
    agent: str
    timestamp: str
    level: str
    message: str
    # Which system reported it: "health" (HEALTH.MD), "tasks", or "task_queue".
    source: str = "health"
    task_id: str = ""


class ObservabilityTask(BaseModel):
    agent: str
    task_id: str
    status: str
    assigned_by: str
    assigned_at: str
    completed_at: str
    duration_s: float | None
    task_summary: str
    error_summary: str
    cost_usd: float = 0.0
    continuation: int = 0
    # Verification gate (roadmap 2.5): what the task changed, the checkpoint it
    # can be rolled back to, and how verifiable those changes are.
    changed_files: list[str] = []
    checkpoint_sha: str = ""
    verification: str = ""


class ObservabilityDashboard(BaseModel):
    generated_at: str
    totals: ObservabilityTotals
    agents: list[ObservabilityAgent]
    recent_errors: list[ObservabilityError]
    recent_tasks: list[ObservabilityTask]


# Each line: `[YYYY-MM-DD HH:MM] LEVEL: MESSAGE` (optional ` | context: ...`).
_HEALTH_LINE_RE = (
    r"^\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]\s+"
    r"(?P<level>[A-Z][A-Z_]*):\s*(?P<msg>.+)$"
)


def _recent_task_incidents(hours: int = 24) -> tuple[list[ObservabilityError], dict[str, int], dict[str, int]]:
    """Terminal task failures from SQLite, as incidents the dashboard can count.

    This is the fix for the counters lying. `agents_with_errors` and
    `recent_error_count` used to be derived from HEALTH.MD alone, so a task that
    failed in the queue and never wrote a health line was invisible — the
    dashboard could read "zero errors" while tasks were failing.

    Two tables are terminal-failure sources:

    * ``tasks``      — per-agent task rows, status ``error``
    * ``task_queue`` — queue-level rows, status ``error`` or ``timeout``

    ``partial`` is deliberately NOT a failure. It means the agent ran out of
    turns and was re-enqueued to continue, so the work is still in flight;
    counting it as an error would inflate the failure rate with healthy work.
    It is returned separately as the continuation count.

    Returns ``(incidents, failures_by_agent, continuations_by_agent)``.
    """
    from app.utils.db import get_db, init_schema

    incidents: list[ObservabilityError] = []
    failures: dict[str, int] = {}
    continuations: dict[str, int] = {}
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=hours)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        init_schema()
        db = get_db()
    except Exception:
        return incidents, failures, continuations

    try:
        rows = db.execute(
            """SELECT agent, task_id, status, completed_at, error_summary
               FROM tasks
               WHERE status IN ('error', 'partial') AND completed_at >= ?
               ORDER BY completed_at DESC LIMIT 200""",
            (cutoff,),
        ).fetchall()
    except Exception:
        rows = []

    for r in rows:
        agent = r["agent"] or "unknown"
        if (r["status"] or "") == "partial":
            continuations[agent] = continuations.get(agent, 0) + 1
            continue
        failures[agent] = failures.get(agent, 0) + 1
        incidents.append(
            ObservabilityError(
                agent=agent,
                timestamp=_to_health_ts(r["completed_at"]),
                level="ERROR",
                message=(r["error_summary"] or "Task failed").strip()[:300],
                source="tasks",
                task_id=(r["task_id"] or ""),
            )
        )

    try:
        qrows = db.execute(
            """SELECT id, status, assigned_agent, completed_at, error
               FROM task_queue
               WHERE status IN ('error', 'timeout') AND completed_at >= ?
               ORDER BY completed_at DESC LIMIT 200""",
            (cutoff,),
        ).fetchall()
    except Exception:
        qrows = []

    for r in qrows:
        agent = r["assigned_agent"] or "master"
        failures[agent] = failures.get(agent, 0) + 1
        incidents.append(
            ObservabilityError(
                agent=agent,
                timestamp=_to_health_ts(r["completed_at"]),
                level=(r["status"] or "error").upper(),
                message=(r["error"] or "Queue task failed").strip()[:300],
                source="task_queue",
                task_id=(r["id"] or ""),
            )
        )

    return incidents, failures, continuations


def _parse_changed_files(raw: str | None) -> list[str]:
    """Decode the JSON list a task row stores, tolerating legacy empty values."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(x) for x in parsed] if isinstance(parsed, list) else []


def _to_health_ts(iso: str | None) -> str:
    """Normalize an ISO timestamp to the HEALTH.MD display format."""
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(
            iso.replace("Z", "+00:00")
        ).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(iso)[:16].replace("T", " ")


def _dedupe_incidents(items: list[ObservabilityError]) -> list[ObservabilityError]:
    """Collapse the same failure reported by two sources into one incident.

    A failing task usually writes BOTH a HEALTH.MD line and a `tasks` row, so a
    naive union double-counts every failure — which would replace one wrong
    number with another. Two entries are the same incident when they share an
    agent, a minute, and the opening of their message. The DB record wins,
    because it carries the task_id.
    """
    by_key: dict[tuple[str, str, str], ObservabilityError] = {}
    ordered: list[ObservabilityError] = []
    for item in items:
        key = (item.agent, item.timestamp, item.message[:60].strip().lower())
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = item
            ordered.append(item)
        elif existing.source == "health" and item.source != "health":
            ordered[ordered.index(existing)] = item
            by_key[key] = item
    return ordered


def _recent_health_lines(agent_dir: Path, max_lines: int = 50) -> list[ObservabilityError]:
    """Tail HEALTH.MD and parse timestamped lines from the last 24 hours."""
    import re

    health_path = agent_dir / "HEALTH.MD"
    if not health_path.exists():
        return []
    try:
        raw = health_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    parsed: list[ObservabilityError] = []
    pattern = re.compile(_HEALTH_LINE_RE)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    # Tail to keep parsing cheap on long logs.
    for line in raw.splitlines()[-max_lines:]:
        m = pattern.match(line.strip())
        if not m:
            continue
        try:
            ts = datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if ts < cutoff:
            continue
        parsed.append(
            ObservabilityError(
                agent=agent_dir.name,
                timestamp=m.group("ts"),
                level=m.group("level"),
                message=m.group("msg"),
            )
        )
    return parsed


@router.get("/observability", response_model=ObservabilityDashboard)
async def get_observability_dashboard():
    """Unified rollup powering the Observability tab.

    Joins per-agent status (TASK.MD / STATUS.json), per-agent usage
    (USAGE.json), HEALTH.MD tail, and the SQLite `tasks` table into a single
    payload. Designed so the frontend can render leaderboard + errors feed
    + recent-tasks feed from one fetch.
    """
    generated_at = (
        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )

    agents: list[ObservabilityAgent] = []
    all_errors: list[ObservabilityError] = []
    total_cost = 0.0
    active_count = 0
    agents_with_errors = 0

    # Terminal failures recorded in SQLite. Previously the dashboard counted
    # only HEALTH.MD lines, so a task that failed without writing one was
    # invisible and the tiles could read "zero errors" during real failures.
    task_incidents, task_failures, task_continuations = _recent_task_incidents()
    all_errors.extend(task_incidents)

    for agent_dir in sorted(AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name.startswith("_"):
            continue
        if agent_dir.name in ("base", "shared"):
            continue

        usage = _read_usage_json(agent_dir) or {}
        models = sorted((usage.get("by_model") or {}).keys())
        cost = float(usage.get("total_cost_usd", 0.0) or 0.0)
        total_cost += cost

        is_alive = _is_alive(agent_dir)
        if is_alive:
            active_count += 1

        health_issues = _count_health_issues(agent_dir)
        agent_task_failures = task_failures.get(agent_dir.name, 0)
        if health_issues or agent_task_failures:
            agents_with_errors += 1
        all_errors.extend(_recent_health_lines(agent_dir))

        agents.append(
            ObservabilityAgent(
                name=agent_dir.name,
                status=_get_current_status(agent_dir),
                is_alive=is_alive,
                cost_usd=round(cost, 6),
                input_tokens=int(usage.get("total_input_tokens", 0) or 0),
                output_tokens=int(usage.get("total_output_tokens", 0) or 0),
                task_count=_count_memory_entries(agent_dir),
                health_issues=health_issues,
                last_active_at=_last_active_at(agent_dir),
                models=models,
                task_failures=agent_task_failures,
                continuations=task_continuations.get(agent_dir.name, 0),
            )
        )

    # Order leaderboard by cost desc; ties broken by task_count desc.
    agents.sort(key=lambda a: (-a.cost_usd, -a.task_count, a.name))

    # HEALTH.MD and the task tables both report the same failure, so the union
    # must be deduped or every failure is counted twice.
    all_errors = _dedupe_incidents(all_errors)
    all_errors.sort(key=lambda e: e.timestamp, reverse=True)
    recent_errors = all_errors[:20]

    # Recent tasks from SQLite. The `tasks` table records every completed
    # task across agents; ordering by id DESC is a cheap "most recent first".
    db = get_db()
    rows = db.execute(
        """SELECT agent, task_id, status, assigned_by, assigned_at,
                  completed_at, task_summary, error_summary,
                  cost_usd, continuation, changed_files, checkpoint_sha,
                  verification
           FROM tasks
           ORDER BY id DESC
           LIMIT 20"""
    ).fetchall()
    recent_tasks: list[ObservabilityTask] = []
    for r in rows:
        assigned_at = r["assigned_at"] or ""
        completed_at = r["completed_at"] or ""
        duration: float | None = None
        if assigned_at and completed_at:
            try:
                start = datetime.fromisoformat(assigned_at.replace("Z", "+00:00"))
                end = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                duration = round(max(0.0, (end - start).total_seconds()), 3)
            except ValueError:
                duration = None
        recent_tasks.append(
            ObservabilityTask(
                agent=r["agent"] or "",
                task_id=r["task_id"] or "",
                status=r["status"] or "",
                assigned_by=r["assigned_by"] or "",
                assigned_at=assigned_at,
                completed_at=completed_at,
                duration_s=duration,
                task_summary=r["task_summary"] or "",
                error_summary=r["error_summary"] or "",
                cost_usd=round(float(r["cost_usd"] or 0.0), 6),
                continuation=int(r["continuation"] or 0),
                changed_files=_parse_changed_files(r["changed_files"]),
                checkpoint_sha=(r["checkpoint_sha"] or "")[:12],
                verification=r["verification"] or "",
            )
        )

    total_tasks = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

    return ObservabilityDashboard(
        generated_at=generated_at,
        totals=ObservabilityTotals(
            total_cost_usd=round(total_cost, 6),
            total_tasks=int(total_tasks or 0),
            active_agents=active_count,
            agents_with_errors=agents_with_errors,
            # Deduped union across HEALTH.MD + both task tables, not a slice of
            # it: the tile must reflect every incident, not just the 20 shown.
            recent_error_count=len(all_errors),
            task_failure_count=sum(task_failures.values()),
            continuation_count=sum(task_continuations.values()),
        ),
        agents=agents,
        recent_errors=recent_errors,
        recent_tasks=recent_tasks,
    )


# ── Cost history ────────────────────────────────────────────────────────────

class CostDataPoint(BaseModel):
    timestamp: str  # ISO-8601 hour bucket
    cost_usd: float
    agent: str
    model: str
    tokens_in: int
    tokens_out: int


class CostHistoryResponse(BaseModel):
    points: list[CostDataPoint]
    bucket: str  # "hour" or "day"


@router.get("/cost-history", response_model=CostHistoryResponse)
async def get_cost_history(bucket: str = "hour", hours: int = 168):
    """Return cost time-series data bucketed by hour or day.

    Reads COSTS.json from every agent directory and aggregates into
    time buckets. Default: hourly buckets for the last 7 days (168 hours).
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    # Bucket key function
    if bucket == "day":
        def bucket_key(ts: str) -> str:
            try:
                d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return d.strftime("%Y-%m-%d")
            except ValueError:
                return ts[:10]
    else:
        def bucket_key(ts: str) -> str:
            try:
                d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return d.strftime("%Y-%m-%dT%H:00:00Z")
            except ValueError:
                return ts[:13] + ":00:00Z"

    buckets: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"cost_usd": 0.0, "tokens_in": 0, "tokens_out": 0}
    )
    agent_model: dict[str, str] = {}

    for agent_dir in sorted(AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name.startswith("_"):
            continue
        if agent_dir.name in ("base", "shared"):
            continue

        costs_path = agent_dir / "COSTS.json"
        if not costs_path.exists():
            continue

        try:
            records = json.loads(costs_path.read_text(encoding="utf-8", errors="ignore"))
            if not isinstance(records, list):
                continue
        except (json.JSONDecodeError, OSError):
            continue

        for rec in records:
            ts = rec.get("timestamp", "")
            if not ts or ts < cutoff.isoformat()[:19]:
                continue

            bk = bucket_key(ts)
            agent = rec.get("agent_name", agent_dir.name)
            model = rec.get("model_used", "unknown")
            agent_model[agent] = model

            key = f"{agent}::{bk}"
            buckets[key]["cost_usd"] += float(rec.get("cost_usd", 0.0))
            buckets[key]["tokens_in"] += int(rec.get("tokens_in", 0))
            buckets[key]["tokens_out"] += int(rec.get("tokens_out", 0))

    points: list[CostDataPoint] = []
    for key, vals in buckets.items():
        agent, _, bk = key.partition("::")
        points.append(CostDataPoint(
            timestamp=bk,
            cost_usd=round(float(vals["cost_usd"]), 8),
            agent=agent,
            model=agent_model.get(agent, "unknown"),
            tokens_in=int(vals["tokens_in"]),
            tokens_out=int(vals["tokens_out"]),
        ))

    points.sort(key=lambda p: (p.timestamp, p.agent))

    return CostHistoryResponse(points=points, bucket=bucket)


@router.get("/hierarchy", response_model=HierarchyMetrics)
async def get_hierarchy_metrics():
    """Return hierarchy quality metrics from persisted task history."""
    db = get_db()
    rows = db.execute(
        "SELECT status, assigned_by, assigned_at, completed_at FROM tasks"
    ).fetchall()
    records = [dict(r) for r in rows]

    delegated_by_parent: Counter[str] = Counter()
    duration_sum_by_parent: defaultdict[str, float] = defaultdict(float)
    duration_count_by_parent: Counter[str] = Counter()

    for rec in records:
        parent = (rec.get("assigned_by") or "unknown").strip() or "unknown"
        delegated_by_parent[parent] += 1

        assigned_at = rec.get("assigned_at") or ""
        completed_at = rec.get("completed_at") or ""
        if assigned_at and completed_at:
            try:
                start = datetime.fromisoformat(assigned_at.replace("Z", "+00:00"))
                end = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                seconds = max(0.0, (end - start).total_seconds())
                duration_sum_by_parent[parent] += seconds
                duration_count_by_parent[parent] += 1
            except ValueError:
                pass

    avg_completion_by_parent: dict[str, float] = {}
    for parent, total_seconds in duration_sum_by_parent.items():
        count = duration_count_by_parent[parent]
        if count > 0:
            avg_completion_by_parent[parent] = round(total_seconds / count, 3)

    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return HierarchyMetrics(
        generated_at=generated_at,
        total_task_records=len(records),
        delegated_by_parent=dict(delegated_by_parent),
        average_completion_seconds_by_parent=avg_completion_by_parent,
    )


@router.get("/branch-costs", response_model=BranchCostsResponse)
async def get_branch_costs():
    """Return per-agent subtree cost rollups over the delegation tree.

    Joins cost onto the delegation topology: each agent's ``own_cost_usd`` is
    the sum of its own tasks, while ``subtree_cost_usd`` folds in every
    descendant's cost too, so a parent's "budget flowed" figure includes its
    whole subtree. Defensive: any DB error yields an empty branch list.
    """
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    try:
        db = get_db()
        rows = db.execute(
            "SELECT agent, assigned_by, cost_usd, status FROM tasks"
        ).fetchall()
    except Exception:
        return BranchCostsResponse(generated_at=generated_at, branches=[])

    # parent -> children adjacency, and per-agent own cost / task count.
    children: defaultdict[str, set[str]] = defaultdict(set)
    own_cost: defaultdict[str, float] = defaultdict(float)
    own_tasks: Counter[str] = Counter()
    agents: set[str] = set()

    for r in rows:
        agent = (r["agent"] or "").strip()
        if not agent:
            continue
        parent = (r["assigned_by"] or "").strip()
        agents.add(agent)
        own_cost[agent] += float(r["cost_usd"] or 0.0)
        own_tasks[agent] += 1
        if parent and parent != agent:
            children[parent].add(agent)
            agents.add(parent)

    # Memoized recursive rollup with cycle guard.
    memo: dict[str, tuple[float, int, int]] = {}

    def rollup(agent: str, visiting: set[str]) -> tuple[float, int, int]:
        """Return (subtree_cost, subtree_tasks, depth) for an agent."""
        if agent in memo:
            return memo[agent]
        if agent in visiting:
            # Cycle back-edge — skip it.
            return own_cost[agent], own_tasks[agent], 0
        visiting.add(agent)
        subtree_cost = own_cost[agent]
        subtree_tasks = own_tasks[agent]
        depth = 0
        for child in sorted(children[agent]):
            c_cost, c_tasks, c_depth = rollup(child, visiting)
            subtree_cost += c_cost
            subtree_tasks += c_tasks
            depth = max(depth, 1 + c_depth)
        visiting.discard(agent)
        memo[agent] = (subtree_cost, subtree_tasks, depth)
        return memo[agent]

    branches: list[BranchCost] = []
    for agent in agents:
        subtree_cost, subtree_tasks, depth = rollup(agent, set())
        branches.append(
            BranchCost(
                agent=agent,
                own_cost_usd=round(own_cost[agent], 8),
                subtree_cost_usd=round(subtree_cost, 8),
                subtree_tasks=subtree_tasks,
                direct_children=sorted(children[agent]),
                depth=depth,
            )
        )

    branches.sort(key=lambda b: b.subtree_cost_usd, reverse=True)
    return BranchCostsResponse(generated_at=generated_at, branches=branches)


# ── Active running time ──────────────────────────────────────────────────────

def _parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp into a timezone-aware datetime.

    Handles a trailing "Z" (which ``datetime.fromisoformat`` rejects before
    3.11) by replacing it with the UTC offset "+00:00". Defensive: returns
    None on any parse failure or falsy input.
    """
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


class ActiveTimeEntry(BaseModel):
    name: str
    running: bool
    current_elapsed_s: float
    total_active_s: float
    task_count: int


class ActiveTimesResponse(BaseModel):
    generated_at: str
    agents: list[ActiveTimeEntry]
    sessions: list[ActiveTimeEntry]


@router.get("/active-time", response_model=ActiveTimesResponse)
async def get_active_times():
    """Return cumulative "active running time" per agent and per session.

    Active time is the wall-clock duration a task actually executed, computed
    from the task_queue table — no schema change. For each task row:
      * running and started_at set  -> now - started_at (still accumulating)
      * completed_at + started_at   -> completed_at - started_at
      * otherwise                   -> 0
    Summed per assigned_agent (for agents) and per session_id (skipping NULLs,
    for sessions).
    """
    db = get_db()
    rows = db.execute(
        """SELECT id, status, assigned_agent, session_id, started_at, completed_at
           FROM task_queue"""
    ).fetchall()

    now = datetime.now(timezone.utc)
    agents: dict[str, dict] = {}
    sessions: dict[str, dict] = {}

    def _elapsed(status: str, started: str | None, completed: str | None) -> float:
        start = _parse_iso(started)
        if not start:
            return 0.0
        if status == "running":
            return max(0.0, (now - start).total_seconds())
        end = _parse_iso(completed)
        if not end:
            return 0.0
        return max(0.0, (end - start).total_seconds())

    for r in rows:
        status = r["status"] or ""
        started = r["started_at"]
        completed = r["completed_at"]
        elapsed = _elapsed(status, started, completed)
        running = bool(status == "running" and started)

        agent = r["assigned_agent"]
        if agent:
            a = agents.setdefault(
                agent, {"total": 0.0, "count": 0, "current": 0.0, "running": False}
            )
            a["total"] += elapsed
            a["count"] += 1
            if running:
                a["running"] = True
                a["current"] = elapsed

        session_id = r["session_id"]
        if session_id is not None:
            s = sessions.setdefault(
                session_id, {"total": 0.0, "count": 0, "current": 0.0, "running": False}
            )
            s["total"] += elapsed
            s["count"] += 1
            if running:
                s["running"] = True
                s["current"] = elapsed

    def _entry(key: str, agg: dict) -> ActiveTimeEntry:
        return ActiveTimeEntry(
            name=key,
            running=agg["running"],
            current_elapsed_s=round(agg["current"], 1),
            total_active_s=round(agg["total"], 1),
            task_count=agg["count"],
        )

    return ActiveTimesResponse(
        generated_at=now.isoformat().replace("+00:00", "Z"),
        agents=[_entry(k, agents[k]) for k in sorted(agents)],
        sessions=[_entry(k, sessions[k]) for k in sorted(sessions)],
    )


# The per-agent ``trace-stream`` SSE endpoint that polled LIVE.MD files
# every 2s was removed. It has been superseded by:
#   GET /agents/{name}/activity  — hydration snapshot from the relay's
#                                   in-memory ring buffer
#   WebSocket {"type": "subscribe_agent", "agent": name}
#                               — live push of per-agent activity events


# ── Reliability scorecard (Phase 2.2) ───────────────────────────────────────
#
# Turns the targets table in docs/harness-roadmap-2026-09.md into something the
# system reports about itself, instead of numbers a human re-derives with ad-hoc
# SQL. Every figure is windowed and the window is part of the response.
#
# The window is not a detail. Ranking failure causes over ALL time is exactly
# the mistake that produced a wrong first draft of that roadmap: pooling years
# of history with long-fixed bugs put turn exhaustion third when, over the
# current release, it was 68% of failures. Hence `days` defaults to 7 and the
# response always states the window it used.

_FAILURE_CLASSES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("timeout", ("timed out",)),
    ("turn_limit", ("turn limit", "turn-limit")),
    (
        "provider_config",
        ("fallback chain", "api error", "credit balance", "invalid_argument",
         "400", "401", "429"),
    ),
    ("malformed_output", ("incomplete provider response",)),
)


def _classify_failure(error_summary: str) -> str:
    """Bucket a failure by its error text. Order matters: first match wins."""
    text = (error_summary or "").lower()
    if not text.strip():
        return "unlabelled"
    for name, needles in _FAILURE_CLASSES:
        if any(n in text for n in needles):
            return name
    return "other"


class ReliabilityAgent(BaseModel):
    name: str
    tasks: int
    failures: int
    failure_rate: float
    continuations: int
    cost_usd: float
    p50_duration_s: float
    p95_duration_s: float


class ReliabilityScorecard(BaseModel):
    generated_at: str
    window_days: int
    window_start: str
    # Totals over the window.
    tasks: int
    completed: int
    failed: int
    partial: int
    failure_rate: float
    # Failure mix, newest window only — never all-time. See the note above.
    failure_mix: dict[str, int]
    # Cost. `cost_per_completed_task` is the number the roadmap tracks; it is
    # None rather than 0.0 when nothing completed, so an empty window cannot be
    # mistaken for free work.
    total_cost_usd: float
    cost_per_completed_task: float | None
    continuation_cost_usd: float
    # Queue-level view (a whole delegation tree per row).
    queue_tasks: int
    queue_failed: int
    queue_cost_usd: float
    by_agent: list[ReliabilityAgent]


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(len(ordered) * pct))
    return round(ordered[idx], 1)


@router.get("/reliability", response_model=ReliabilityScorecard)
async def get_reliability_scorecard(days: int = 7):
    """Reliability, cost and continuation metrics over a trailing window."""
    from app.utils.db import get_db, init_schema

    days = max(1, min(int(days or 7), 365))
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    start_s = start.strftime("%Y-%m-%dT%H:%M:%SZ")

    init_schema()
    db = get_db()

    rows = db.execute(
        """SELECT agent, status, error_summary, cost_usd, continuation,
                  assigned_at, completed_at
           FROM tasks WHERE assigned_at >= ?""",
        (start_s,),
    ).fetchall()

    per_agent: dict[str, dict] = {}
    failure_mix: dict[str, int] = {}
    completed = failed = partial = 0
    total_cost = 0.0
    continuation_cost = 0.0

    for r in rows:
        agent = r["agent"] or "unknown"
        status = (r["status"] or "").lower()
        cost = float(r["cost_usd"] or 0.0)
        bucket = per_agent.setdefault(
            agent,
            {"tasks": 0, "failures": 0, "continuations": 0, "cost": 0.0, "durations": []},
        )
        bucket["tasks"] += 1
        bucket["cost"] += cost
        total_cost += cost

        if int(r["continuation"] or 0) > 0:
            continuation_cost += cost

        if status == "done":
            completed += 1
        elif status == "partial":
            partial += 1
            bucket["continuations"] += 1
        elif status == "error":
            failed += 1
            bucket["failures"] += 1
            cls = _classify_failure(r["error_summary"] or "")
            failure_mix[cls] = failure_mix.get(cls, 0) + 1

        if r["assigned_at"] and r["completed_at"]:
            try:
                a = datetime.fromisoformat(r["assigned_at"].replace("Z", "+00:00"))
                c = datetime.fromisoformat(r["completed_at"].replace("Z", "+00:00"))
                delta = (c - a).total_seconds()
                if delta > 0:
                    bucket["durations"].append(delta)
            except (ValueError, TypeError):
                pass

    qrows = db.execute(
        "SELECT status, cost_usd FROM task_queue WHERE created_at >= ?", (start_s,)
    ).fetchall()
    queue_failed = sum(
        1 for q in qrows if (q["status"] or "") in ("error", "timeout")
    )
    queue_cost = sum(float(q["cost_usd"] or 0.0) for q in qrows)

    # Denominator excludes `partial`: those tasks have not reached an outcome
    # yet, so counting them either way would misstate the rate.
    terminal = completed + failed
    failure_rate = round(failed / terminal, 4) if terminal else 0.0

    by_agent = [
        ReliabilityAgent(
            name=name,
            tasks=b["tasks"],
            failures=b["failures"],
            failure_rate=round(
                b["failures"] / b["tasks"], 4
            ) if b["tasks"] else 0.0,
            continuations=b["continuations"],
            cost_usd=round(b["cost"], 6),
            p50_duration_s=_percentile(b["durations"], 0.50),
            p95_duration_s=_percentile(b["durations"], 0.95),
        )
        for name, b in sorted(
            per_agent.items(), key=lambda kv: (-kv[1]["failures"], kv[0])
        )
    ]

    return ReliabilityScorecard(
        generated_at=now.isoformat().replace("+00:00", "Z"),
        window_days=days,
        window_start=start_s,
        tasks=len(rows),
        completed=completed,
        failed=failed,
        partial=partial,
        failure_rate=failure_rate,
        failure_mix=dict(sorted(failure_mix.items(), key=lambda kv: -kv[1])),
        total_cost_usd=round(total_cost, 6),
        cost_per_completed_task=(
            round(total_cost / completed, 6) if completed else None
        ),
        continuation_cost_usd=round(continuation_cost, 6),
        queue_tasks=len(qrows),
        queue_failed=queue_failed,
        queue_cost_usd=round(queue_cost, 6),
        by_agent=by_agent,
    )


# ── Evaluator signal ledger (Phase 3.2) ─────────────────────────────────────


class LedgerSignal(BaseModel):
    signal_id: str
    title: str
    impact: str
    status: str
    rounds_open: int
    first_seen_round: int
    last_seen_round: int
    last_seen_ts: str


class SignalLedgerResponse(BaseModel):
    generated_at: str
    total: int
    open_count: int
    resolved_count: int
    # Rounds between the ledger and the newest evaluator report. Non-zero means
    # findings are being judged against stale data — the failure mode that left
    # an already-fixed bug showing as an open signal.
    staleness_rounds: int
    latest_report_round: int
    ledger_round: int
    open_signals: list[LedgerSignal]


@router.get("/signals", response_model=SignalLedgerResponse)
async def get_signal_ledger():
    """Open evaluator findings, and how far behind the ledger has drifted.

    The ledger already tracked resolution, but nothing surfaced it: the only
    consumer was `propose_goals()`, invoked by hand. Findings could sit "open"
    indefinitely after the underlying bug was fixed, with nobody able to see it.
    """
    from app.utils.signal_ledger import _load_ledger, scan_findings

    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # `ledger_snapshot()` returns aggregate counts only; the per-signal detail
    # this endpoint exists to surface lives in the raw ledger.
    try:
        entries = _load_ledger()
    except Exception:
        entries = {}
    if not isinstance(entries, dict):
        entries = {}

    signals: list[LedgerSignal] = []
    open_count = resolved_count = 0
    ledger_round = 0
    for sid, raw in entries.items():
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status", "open"))
        ledger_round = max(ledger_round, int(raw.get("last_seen_round", 0) or 0))
        if status == "resolved":
            resolved_count += 1
            continue
        open_count += 1
        signals.append(
            LedgerSignal(
                signal_id=str(raw.get("signal_id", sid)),
                title=str(raw.get("title", "")),
                impact=str(raw.get("impact", "")),
                status=status,
                rounds_open=int(raw.get("rounds_open", 0) or 0),
                first_seen_round=int(raw.get("first_seen_round", 0) or 0),
                last_seen_round=int(raw.get("last_seen_round", 0) or 0),
                last_seen_ts=str(raw.get("last_seen_ts", "")),
            )
        )

    try:
        latest_round = max((f.round_number for f in scan_findings()), default=0)
    except Exception:
        latest_round = 0

    signals.sort(key=lambda s: (-s.rounds_open, s.title))
    return SignalLedgerResponse(
        generated_at=generated_at,
        total=len(entries),
        open_count=open_count,
        resolved_count=resolved_count,
        staleness_rounds=max(0, latest_round - ledger_round),
        latest_report_round=latest_round,
        ledger_round=ledger_round,
        open_signals=signals,
    )
