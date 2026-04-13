import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.backend.services import _pid_alive, _read_status_json, _parse_health_log, _parse_task
from app.config import settings
from app.utils import AGENTS_DIR

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
    """Count non-blank lines in HEALTH.MD (0 if file doesn't exist)."""
    health_path = agent_dir / "HEALTH.MD"
    if not health_path.exists():
        return 0
    try:
        lines = [
            line.strip()
            for line in health_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip()
        ]
        return len(lines)
    except OSError:
        return 0


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
