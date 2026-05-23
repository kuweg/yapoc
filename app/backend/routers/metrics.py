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


class ObservabilityError(BaseModel):
    agent: str
    timestamp: str
    level: str
    message: str


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
        if health_issues:
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
            )
        )

    # Order leaderboard by cost desc; ties broken by task_count desc.
    agents.sort(key=lambda a: (-a.cost_usd, -a.task_count, a.name))

    all_errors.sort(key=lambda e: e.timestamp, reverse=True)
    recent_errors = all_errors[:20]

    # Recent tasks from SQLite. The `tasks` table records every completed
    # task across agents; ordering by id DESC is a cheap "most recent first".
    db = get_db()
    rows = db.execute(
        """SELECT agent, task_id, status, assigned_by, assigned_at,
                  completed_at, task_summary, error_summary
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
            recent_error_count=len(recent_errors),
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


# The per-agent ``trace-stream`` SSE endpoint that polled LIVE.MD files
# every 2s was removed. It has been superseded by:
#   GET /agents/{name}/activity  — hydration snapshot from the relay's
#                                   in-memory ring buffer
#   WebSocket {"type": "subscribe_agent", "agent": name}
#                               — live push of per-agent activity events
