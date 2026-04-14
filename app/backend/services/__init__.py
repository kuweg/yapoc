import json
import os
import re
from datetime import datetime, timezone

from app.agents.base import BaseAgent
from app.backend.models import AgentStatus, AgentDetail, HealthLogEntry, TaskDetail
from app.config import settings
from app.utils import AGENTS_DIR


def _read_status_json(agent_dir) -> dict | None:
    path = agent_dir / "STATUS.json"
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _is_stale_status(status: dict) -> bool:
    """Return True if STATUS.json hasn't been updated within the agent's expected lifetime."""
    updated_at_str = status.get("updated_at")
    if not updated_at_str:
        return False
    try:
        updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - updated_at).total_seconds()
        return age > settings.agent_idle_timeout + 60  # e.g. 360s
    except Exception:
        return False


def _parse_config(agent_dir) -> tuple[str, str]:
    """Return (model, adapter) from CONFIG.md, falling back to agent.py."""
    model = ""
    adapter = ""

    config_path = agent_dir / "CONFIG.md"
    if config_path.exists():
        text = config_path.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"model[:\s]+([^\s\n]+)", text, re.IGNORECASE)
        if m:
            model = m.group(1).strip("`").strip()
        a = re.search(r"adapter[:\s]+([^\s\n]+)", text, re.IGNORECASE)
        if a:
            adapter = a.group(1).strip("`").strip()

    if not model:
        agent_py = agent_dir / "agent.py"
        if agent_py.exists():
            text = agent_py.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r'model\s*=\s*["\']([^"\']+)["\']', text)
            if m:
                model = m.group(1)
            a = re.search(r'adapter\s*=\s*["\']([^"\']+)["\']', text)
            if a:
                adapter = a.group(1)

    return model or "unknown", adapter or "anthropic"


HEALTH_LINE_RE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]\s*"
    r"(?:\[(\w+)\]\s*)?"
    r"(INFO|WARNING|ERROR|CRITICAL|AUDIT)?:?\s*(.*?)(?:\s*\|\s*context:\s*(.*))?$"
)


def _parse_health_log(agent_dir, last_n: int = 20) -> tuple[list[HealthLogEntry], str, int]:
    """Return (entries[-last_n], health_status, error_count)."""
    path = agent_dir / "HEALTH.MD"
    entries: list[HealthLogEntry] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            m = HEALTH_LINE_RE.match(line)
            if m:
                level = m.group(2) or m.group(3) or "INFO"
                entries.append(
                    HealthLogEntry(
                        timestamp=m.group(1),
                        level=level,
                        message=(m.group(4) or line).strip(),
                        context=m.group(5),
                    )
                )

    recent = entries[-10:]
    error_count = sum(1 for e in recent if e.level in ("ERROR", "CRITICAL"))
    warning_count = sum(1 for e in recent if e.level == "WARNING")
    if error_count > 0:
        health = "critical"
    elif warning_count > 0:
        health = "warning"
    else:
        health = "ok"

    return entries[-last_n:], health, error_count


def _parse_memory(agent_dir) -> tuple[int, str | None, list[str]]:
    """Return (entry_count, last_entry_truncated, last_5_entries)."""
    path = agent_dir / "MEMORY.MD"
    if not path.exists():
        return 0, None, []
    lines = [l.strip() for l in path.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
    count = len(lines)
    last = lines[-1][:100] if lines else None
    last_5 = lines[-5:] if lines else []
    return count, last, last_5


def _parse_task(agent_dir) -> TaskDetail | None:
    """Parse TASK.MD into a TaskDetail object."""
    path = agent_dir / "TASK.MD"
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    if not content.strip():
        return None

    # Parse YAML frontmatter
    fm: dict[str, str | None] = {}
    fm_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).splitlines():
            if ": " in line:
                key, _, value = line.partition(": ")
                fm[key.strip()] = value.strip() or None

    # Parse sections
    def get_section(name: str) -> str | None:
        m = re.search(rf"## {name}\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
        return m.group(1).strip() if m else None

    task_text = get_section("Task") or ""
    result_text = get_section("Result")
    error_text = get_section("Error")

    if not task_text and not fm:
        return None

    return TaskDetail(
        status=fm.get("status") or "",
        assigned_by=fm.get("assigned_by") or "",
        assigned_at=fm.get("assigned_at") or "",
        completed_at=fm.get("completed_at"),
        task_text=task_text,
        result_text=result_text if result_text else None,
        error_text=error_text if error_text else None,
    )


def _compute_uptime(started_at: str | None) -> int | None:
    if not started_at:
        return None
    try:
        dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return int((now - dt).total_seconds())
    except Exception:
        return None


def _build_agent_status(agent_dir) -> AgentStatus | None:
    """Build an AgentStatus for a single agent directory."""
    try:
        agent = BaseAgent(agent_dir)
        raw = agent.get_status_sync() if hasattr(agent, "get_status_sync") else None
    except Exception:
        raw = None

    # Read process info from STATUS.json
    proc_status = _read_status_json(agent_dir)
    pid = None
    task_summary = ""
    started_at = None
    updated_at = None
    idle_since = None
    state = "idle"

    tokens_per_second: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    if proc_status:
        pid = proc_status.get("pid")
        task_summary = proc_status.get("task_summary", "")
        started_at = proc_status.get("started_at")
        updated_at = proc_status.get("updated_at")
        idle_since = proc_status.get("idle_since")
        tokens_per_second = proc_status.get("tokens_per_second")
        input_tokens = proc_status.get("input_tokens")
        output_tokens = proc_status.get("output_tokens")
        raw_state = proc_status.get("state", "")
        if raw_state == "terminated" or (pid and not _pid_alive(pid)):
            state = "idle"
            pid = None
        else:
            state = raw_state or "idle"
        # Stale PID check: agent died on server restart, PID may be recycled
        if state in ("idle", "running") and pid and _is_stale_status(proc_status):
            state = "idle"
            pid = None

    # Health
    _, health, health_errors = _parse_health_log(agent_dir)

    # Memory
    memory_entries, last_memory_entry, _ = _parse_memory(agent_dir)

    # Model/adapter
    model, adapter = _parse_config(agent_dir)

    # has_task
    task = _parse_task(agent_dir)
    has_task = bool(task and task.task_text)

    # Legacy status field
    if state == "running":
        legacy_status = "running"
    elif health_errors > 0:
        legacy_status = "error"
    elif has_task:
        legacy_status = "busy"
    else:
        legacy_status = "idle"

    _INFRA_AGENTS = {"base", "doctor", "model_manager"}
    is_infrastructure = agent_dir.name in _INFRA_AGENTS

    return AgentStatus(
        name=agent_dir.name,
        status=legacy_status,
        model=model,
        has_task=has_task,
        memory_entries=memory_entries,
        health_errors=health_errors,
        process_state=state,
        pid=pid,
        task_summary=task_summary[:120] if task_summary else "",
        adapter=adapter,
        state=state,
        health=health,
        started_at=started_at,
        updated_at=updated_at,
        idle_since=idle_since,
        last_memory_entry=last_memory_entry,
        tokens_per_second=tokens_per_second,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        is_infrastructure=is_infrastructure,
    )


class AgentService:
    async def get_all_statuses(self) -> list[AgentStatus]:
        statuses = []
        for agent_dir in sorted(AGENTS_DIR.iterdir()):
            if not agent_dir.is_dir() or agent_dir.name.startswith("_"):
                continue
            if agent_dir.name == "base":
                continue
            try:
                status = _build_agent_status(agent_dir)
                if status:
                    statuses.append(status)
            except Exception:
                pass

        # Sort: running first, then error/critical, then idle, then done
        order = {"running": 0, "error": 1, "idle": 2, "done": 3}
        statuses.sort(key=lambda a: order.get(a.state, 2))
        return statuses

    async def get_agent_detail(self, name: str) -> AgentDetail:
        agent_dir = AGENTS_DIR / name
        if not agent_dir.is_dir():
            raise FileNotFoundError(f"Agent '{name}' not found")

        status = _build_agent_status(agent_dir)
        if not status:
            raise FileNotFoundError(f"Agent '{name}' could not be read")

        health_log, _, _ = _parse_health_log(agent_dir, last_n=20)
        _, _, memory_log = _parse_memory(agent_dir)
        task = _parse_task(agent_dir)
        uptime = _compute_uptime(status.started_at)

        return AgentDetail(
            **status.model_dump(),
            task=task,
            health_log=health_log,
            memory_log=memory_log,
            uptime_seconds=uptime,
        )

    async def get_agent_file(self, name: str, filename: str) -> str:
        agent_dir = AGENTS_DIR / name
        if not agent_dir.is_dir():
            raise FileNotFoundError(f"Agent '{name}' not found")
        agent = BaseAgent(agent_dir)
        return await agent._read_file(filename)

    async def restart_agent(self, name: str) -> None:
        agent_dir = AGENTS_DIR / name
        if not agent_dir.is_dir():
            raise FileNotFoundError(f"Agent '{name}' not found")
        agent = BaseAgent(agent_dir)
        await agent._write_file("TASK.MD", "")
        await agent._write_file("HEALTH.MD", "")
