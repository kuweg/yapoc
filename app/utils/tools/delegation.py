"""Delegation tools — spawn, ping, kill sub-agents and check task results."""

import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any

import aiofiles

from app.config import settings
from app.utils.crash import agent_exit_watcher, count_crashes

from . import BaseTool, RiskTier, truncate_tool_output


def _status_path(agent_name: str):
    return settings.agents_dir / agent_name / "STATUS.json"


def _task_path(agent_name: str):
    return settings.agents_dir / agent_name / "TASK.MD"


def _read_status(agent_name: str) -> dict | None:
    path = _status_path(agent_name)
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


def _is_stale(status: dict) -> bool:
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


def _count_live_agents(exclude: str | None = None) -> int:
    """Return the number of sub-agents currently in a 'live' state.

    Reads every ``STATUS.json`` under ``agents_dir`` and counts those whose
    state is ``idle``, ``running``, or ``spawning`` **and** whose recorded
    PID is alive. Excludes ``exclude`` (the agent about to be spawned, to
    avoid double-counting when reassigning a task to an already-running
    process).
    """
    live = 0
    try:
        for agent_dir in settings.agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            if agent_dir.name in ("base", "master"):
                continue  # master is the spawner, base is internal
            if exclude and agent_dir.name == exclude:
                continue
            status = _read_status(agent_dir.name)
            if not status:
                continue
            state = status.get("state", "")
            if state not in ("idle", "running", "spawning"):
                continue
            pid = status.get("pid")
            if pid and _pid_alive(pid) and not _is_stale(status):
                live += 1
    except OSError:
        pass
    return live


def _is_temporary_agent(agent_name: str) -> bool:
    """Check if an agent has lifecycle.temporary set in CONFIG.md."""
    config_path = settings.agents_dir / agent_name / "CONFIG.md"
    if not config_path.exists():
        return False
    # Inline parse to avoid circular import with app.agents.base.context
    in_lifecycle = False
    for line in config_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "lifecycle:":
            in_lifecycle = True
            continue
        if in_lifecycle:
            m = re.match(r"\s+temporary:\s*(true|false)", line, re.IGNORECASE)
            if m:
                return m.group(1).lower() == "true"
            if stripped and not stripped.startswith("#") and not line.startswith(" "):
                break
    return False


def _cleanup_temporary_agent(agent_name: str) -> str:
    """Kill PID if alive (defensive) and remove the agent directory."""
    agent_dir = settings.agents_dir / agent_name
    # Best-effort kill
    status = _read_status(agent_name)
    if status and status.get("pid"):
        try:
            os.kill(status["pid"], signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    # Remove directory
    try:
        shutil.rmtree(agent_dir)
        return f"Temporary agent '{agent_name}' auto-deleted."
    except OSError:
        return f"Temporary agent '{agent_name}': directory already removed."


def _parse_delegation_targets(agent_name: str) -> list[str]:
    """Read the delegation_targets list from an agent's CONFIG.md.

    Expected format::

        delegation_targets:
          - builder
          - keeper
    """
    config_path = settings.agents_dir / agent_name / "CONFIG.md"
    if not config_path.exists():
        return []
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return []

    targets: list[str] = []
    in_block = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped == "delegation_targets:" or stripped.startswith("delegation_targets:"):
            in_block = True
            continue
        if not in_block:
            continue
        # Top-level key exits the block
        if stripped and not raw_line.startswith(" ") and not stripped.startswith("#"):
            break
        m = re.match(r"^\s+-\s+(.+?)\s*$", raw_line)
        if m:
            targets.append(m.group(1).strip())
    return targets


# Agents that can spawn any agent without delegation_targets checks
_UNRESTRICTED_SPAWNERS = {"master", "planning"}


class SpawnAgentTool(BaseTool):
    name = "spawn_agent"
    description = (
        "Spawn a sub-agent process (or assign a new task to an already-running agent). "
        "Writes TASK.MD with frontmatter and starts the agent subprocess if needed."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Name of the agent to spawn (e.g. 'planning', 'builder')",
            },
            "task": {
                "type": "string",
                "description": "Task description for the agent",
            },
            "context": {
                "type": "string",
                "description": "Optional context for the task",
            },
        },
        "required": ["agent_name", "task"],
    }
    risk_tier = RiskTier.AUTO

    def __init__(self, agent_dir: "Path | None" = None) -> None:
        self._caller = agent_dir.name if agent_dir else "master"

    async def execute(self, **params: Any) -> str:
        agent_name = params["agent_name"]
        task = params["task"]
        context = params.get("context", "")

        agent_dir = settings.agents_dir / agent_name
        if not agent_dir.is_dir():
            return f"Error: agent directory not found: {agent_dir}"

        # Peer delegation check — master and planning have unrestricted
        # spawn rights (existing behavior). All other agents must have the
        # target in their CONFIG.md delegation_targets list.
        if self._caller not in _UNRESTRICTED_SPAWNERS:
            allowed = _parse_delegation_targets(self._caller)
            if not allowed:
                return (
                    f"Error: agent '{self._caller}' has no delegation_targets in CONFIG.md. "
                    f"Only master and planning can spawn agents without explicit delegation_targets."
                )
            if agent_name not in allowed:
                return (
                    f"Error: agent '{self._caller}' is not authorized to delegate to '{agent_name}'. "
                    f"Allowed targets: {allowed}. Add '{agent_name}' to delegation_targets in "
                    f"app/agents/{self._caller}/CONFIG.md to enable this delegation."
                )
            # Log peer delegation to master's HEALTH.MD for audit trail
            try:
                master_health = settings.agents_dir / "master" / "HEALTH.MD"
                ts = datetime.now().strftime("%Y-%m-%d %H:%M")
                log_line = f"[{ts}] INFO: [PEER DELEGATION] {self._caller} -> {agent_name}: {task[:100]}\n"
                master_health.open("a", encoding="utf-8").write(log_line)
            except OSError:
                pass  # never block delegation on audit failure

        # Check if process is already alive
        status = _read_status(agent_name)
        process_alive = False
        if status and status.get("pid"):
            process_alive = _pid_alive(status["pid"])
        if process_alive and status and _is_stale(status):
            process_alive = False  # PID likely recycled after server restart

        # Enforce the concurrent-agent cap unless we are just re-assigning
        # to an already-running agent (no new process spawned in that case).
        if not process_alive:
            live = _count_live_agents(exclude=agent_name)
            cap = settings.max_concurrent_agents
            if live >= cap:
                return (
                    f"Error: refusing to spawn '{agent_name}' — {live} sub-agents "
                    f"already live (cap: {cap}). Wait for some to finish via "
                    f"wait_for_agent / wait_for_agents, or increase "
                    f"settings.max_concurrent_agents."
                )

        # Reject assignment to a mid-task agent — the running task's completion
        # would overwrite status:pending → done, silently dropping the new task.
        if process_alive and status.get("state") == "running":
            return (
                f"Agent '{agent_name}' is currently processing a task "
                f"(PID {status['pid']}, state: running). "
                f"Use wait_for_agent('{agent_name}') to wait for it to finish, "
                f"then spawn again."
            )

        # Write TASK.MD with frontmatter
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        task_content = (
            f"---\n"
            f"status: pending\n"
            f"assigned_by: {self._caller}\n"
            f"assigned_at: {now}\n"
            f"completed_at:\n"
            f"---\n\n"
            f"## Task\n{task}\n\n"
            f"## Context\n{context}\n\n"
            f"## Result\n\n\n"
            f"## Error\n\n"
        )
        async with aiofiles.open(_task_path(agent_name), "w", encoding="utf-8") as f:
            await f.write(task_content)

        # Register spawn relationship for notification delivery
        try:
            from app.backend.services.spawn_registry import registry as _registry
            _registry.register_spawn(parent_agent=self._caller, child_agent=agent_name)
        except Exception:
            pass  # never let registry errors block spawning

        # If process is alive (idle or spawning), the watchdog picks up the new pending task
        if process_alive and status.get("state") in ("idle", "spawning"):
            return (
                f"Agent '{agent_name}' already running (PID {status['pid']}, "
                f"state: {status.get('state')}). New task assigned."
            )

        # Spawn new subprocess with output capture
        output_path = agent_dir / "OUTPUT.MD"
        crash_path = agent_dir / "CRASH.MD"
        log_fh = open(output_path, "a", encoding="utf-8")
        restart_count = count_crashes(crash_path)
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.agents.base.runner_entry", "--agent", agent_name],
            start_new_session=True,
            stdout=log_fh,
            stderr=log_fh,
        )
        agent_exit_watcher(proc, output_path, crash_path, agent_name, restart_count)

        # Poll STATUS.json for spawn confirmation
        deadline = time.monotonic() + settings.agent_spawn_timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(0.5)
            s = _read_status(agent_name)
            if s and s.get("state") != "spawning" and s.get("pid") == proc.pid:
                return (
                    f"Agent '{agent_name}' spawned (PID {proc.pid}, state: {s['state']}). "
                    f"Task assigned."
                )

        # Timeout — process may still be starting
        return (
            f"Agent '{agent_name}' spawned (PID {proc.pid}) but did not confirm "
            f"within {settings.agent_spawn_timeout}s. Check STATUS.json."
        )


class PingAgentTool(BaseTool):
    name = "ping_agent"
    description = "Check the status of a sub-agent process by reading its STATUS.json and verifying PID liveness."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Name of the agent to ping",
            },
        },
        "required": ["agent_name"],
    }
    risk_tier = RiskTier.AUTO

    async def execute(self, **params: Any) -> str:
        agent_name = params["agent_name"]
        status = _read_status(agent_name)
        if not status:
            return f"Agent '{agent_name}': no STATUS.json found (not running)"

        pid = status.get("pid")
        state = status.get("state", "unknown")
        alive = _pid_alive(pid) if pid else False

        if not alive and state not in ("terminated",):
            return (
                f"Agent '{agent_name}': STATUS.json says '{state}' (PID {pid}) "
                f"but process is NOT alive — stale status."
            )

        return (
            f"Agent '{agent_name}': state={state}, pid={pid}, alive={alive}, "
            f"task={status.get('task_summary', '')!r}, "
            f"updated={status.get('updated_at', '?')}"
        )


class KillAgentTool(BaseTool):
    name = "kill_agent"
    description = "Send SIGTERM to a sub-agent process to request graceful shutdown."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Name of the agent to kill",
            },
        },
        "required": ["agent_name"],
    }
    risk_tier = RiskTier.AUTO

    async def execute(self, **params: Any) -> str:
        agent_name = params["agent_name"]
        status = _read_status(agent_name)
        if not status:
            return f"Agent '{agent_name}': no STATUS.json — not running"

        pid = status.get("pid")
        if not pid or not _pid_alive(pid):
            return f"Agent '{agent_name}': PID {pid} is not alive"

        try:
            os.kill(pid, signal.SIGTERM)
            return f"Agent '{agent_name}': SIGTERM sent to PID {pid}"
        except ProcessLookupError:
            return f"Agent '{agent_name}': PID {pid} already exited"
        except PermissionError:
            return f"Agent '{agent_name}': permission denied sending SIGTERM to PID {pid}"


class CheckTaskStatusTool(BaseTool):
    name = "check_task_status"
    description = "Read the frontmatter 'status' field from a sub-agent's TASK.MD."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Name of the agent to check",
            },
        },
        "required": ["agent_name"],
    }
    risk_tier = RiskTier.AUTO

    async def execute(self, **params: Any) -> str:
        agent_name = params["agent_name"]
        path = _task_path(agent_name)
        if not path.exists():
            return f"Agent '{agent_name}': no TASK.MD"

        async with aiofiles.open(path, encoding="utf-8") as f:
            content = await f.read()

        # Parse frontmatter
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", content, re.DOTALL)
        if not m:
            return f"Agent '{agent_name}': TASK.MD has no frontmatter"

        fields: dict[str, str] = {}
        for line in m.group(1).splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                fields[key.strip()] = val.strip()

        status = fields.get("status", "unknown")
        assigned_by = fields.get("assigned_by", "?")
        assigned_at = fields.get("assigned_at", "?")
        completed_at = fields.get("completed_at", "")

        parts = [f"Agent '{agent_name}': status={status}, assigned_by={assigned_by}, assigned_at={assigned_at}"]
        if completed_at:
            parts.append(f"completed_at={completed_at}")
        return ", ".join(parts)


class WaitForAgentTool(BaseTool):
    name = "wait_for_agent"
    description = (
        "Wait for a sub-agent to finish its task. Polls TASK.MD internally "
        "and returns the full result (or error) when done. Replaces manual "
        "check_task_status + sleep loops."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Name of the agent to wait for",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait (default 300)",
                "default": 300,
            },
            "poll_interval": {
                "type": "integer",
                "description": "Seconds between polls (default 3)",
                "default": 3,
            },
        },
        "required": ["agent_name"],
    }
    risk_tier = RiskTier.AUTO

    async def execute(self, **params: Any) -> str:
        agent_name = params["agent_name"]
        timeout = params.get("timeout", 300)
        poll_interval = params.get("poll_interval", 3)

        path = _task_path(agent_name)
        if not path.exists():
            return f"Error: no TASK.MD for agent '{agent_name}'"

        deadline = time.monotonic() + timeout
        polls = 0
        last_status = "unknown"

        while time.monotonic() < deadline:
            polls += 1
            async with aiofiles.open(path, encoding="utf-8") as f:
                content = await f.read()

            # Parse frontmatter status
            m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", content, re.DOTALL)
            if m:
                for line in m.group(1).splitlines():
                    if line.startswith("status:"):
                        last_status = line.partition(":")[2].strip()
                        break

                if last_status == "done":
                    # Extract ## Result section
                    rm = re.search(r"## Result\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
                    result = rm.group(1).strip() if rm else ""
                    msg = result if result else f"Agent '{agent_name}' finished but ## Result is empty."
                    if _is_temporary_agent(agent_name):
                        msg += f"\n[{_cleanup_temporary_agent(agent_name)}]"
                    return truncate_tool_output(
                        msg,
                        cap=20_000,
                        note=f"read file://app/agents/{agent_name}/TASK.MD for full result",
                    )

                if last_status == "error":
                    # Extract ## Error section
                    em = re.search(r"## Error\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
                    error = em.group(1).strip() if em else ""
                    msg = f"Agent '{agent_name}' failed:\n{error}" if error else f"Agent '{agent_name}' status is 'error' but ## Error is empty."
                    if _is_temporary_agent(agent_name):
                        msg += f"\n[{_cleanup_temporary_agent(agent_name)}]"
                    return truncate_tool_output(
                        msg,
                        cap=20_000,
                        note=f"read file://app/agents/{agent_name}/TASK.MD for full error",
                    )

                # Fast-fail: if the process has terminated but the task never reached
                # a terminal state, the agent crashed — don't burn the full timeout.
                if last_status in ("running", "pending"):
                    agent_status = _read_status(agent_name)
                    if agent_status and agent_status.get("state") == "terminated":
                        pid = agent_status.get("pid", "?")
                        return (
                            f"Agent '{agent_name}' process terminated (PID {pid}) "
                            f"while task was still '{last_status}' — agent likely crashed. "
                            f"Check app/agents/{agent_name}/CRASH.MD or OUTPUT.MD for details."
                        )

            await asyncio.sleep(poll_interval)

        return (
            f"Timeout waiting for agent '{agent_name}' after {timeout}s "
            f"({polls} polls). Last status: {last_status}."
        )


_PER_AGENT_WAIT_SECTION_CAP = 8000


def _format_wait_results(results: dict[str, dict], polls: int, early_exit: str | None = None) -> str:
    lines: list[str] = []
    if early_exit:
        lines.append(f"[fail_fast] Agent '{early_exit}' errored — returning early after {polls} polls.\n")
    else:
        lines.append(f"Completed waiting for {len(results)} agents ({polls} polls).\n")
    for name, r in results.items():
        status = r["status"]
        # Per-agent sections are capped so a single noisy agent can't blow
        # up the fan-in result. The caller can always read_task_result for
        # any one agent directly if they need full detail.
        if status == "done":
            body = truncate_tool_output(
                r["result"],
                cap=_PER_AGENT_WAIT_SECTION_CAP,
                note=f"read_task_result {name} for full output",
            )
            lines.append(f"### {name}: done\n{body}\n")
        elif status == "error":
            body = truncate_tool_output(
                r["error"],
                cap=_PER_AGENT_WAIT_SECTION_CAP,
                note=f"read_task_result {name} for full error",
            )
            lines.append(f"### {name}: error\n{body}\n")
        elif status == "timeout":
            lines.append(f"### {name}: timeout\n{r['error']}\n")
        else:
            lines.append(f"### {name}: {status}\n")
    return truncate_tool_output("\n".join(lines))


class WaitForAgentsTool(BaseTool):
    name = "wait_for_agents"
    description = (
        "Wait for multiple sub-agents to finish their tasks in parallel. "
        "Polls all agents' TASK.MD simultaneously using asyncio.gather and returns "
        "when all complete. If fail_fast=true (default), returns immediately when any "
        "agent reports an error status. Returns a structured per-agent result summary."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agent_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of agent names to wait for",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait for all agents (default 300)",
                "default": 300,
            },
            "poll_interval": {
                "type": "integer",
                "description": "Seconds between polls (default 3)",
                "default": 3,
            },
            "fail_fast": {
                "type": "boolean",
                "description": "Return immediately if any agent reports error status (default true)",
                "default": True,
            },
        },
        "required": ["agent_names"],
    }
    risk_tier = RiskTier.AUTO

    async def execute(self, **params: Any) -> str:
        agent_names: list[str] = params["agent_names"]
        timeout: int = params.get("timeout", 300)
        poll_interval: int = params.get("poll_interval", 3)
        fail_fast: bool = params.get("fail_fast", True)

        if not agent_names:
            return "Error: agent_names list is empty"

        results: dict[str, dict] = {
            name: {"status": "pending", "result": "", "error": ""} for name in agent_names
        }
        done: set[str] = set()
        deadline = time.monotonic() + timeout
        polls = 0

        async def poll_one(agent_name: str) -> tuple[str, str, str, str]:
            path = _task_path(agent_name)
            if not path.exists():
                return agent_name, "error", "", f"No TASK.MD for agent '{agent_name}'"
            async with aiofiles.open(path, encoding="utf-8") as f:
                content = await f.read()
            status = "unknown"
            m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", content, re.DOTALL)
            if m:
                for line in m.group(1).splitlines():
                    if line.startswith("status:"):
                        status = line.partition(":")[2].strip()
                        break
            if status == "done":
                rm = re.search(r"## Result\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
                result = rm.group(1).strip() if rm else ""
                return agent_name, "done", result, ""
            if status == "error":
                em = re.search(r"## Error\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
                error = em.group(1).strip() if em else ""
                return agent_name, "error", "", error
            return agent_name, status, "", ""

        while time.monotonic() < deadline:
            polls += 1
            pending = [name for name in agent_names if name not in done]
            if not pending:
                break

            poll_results = await asyncio.gather(*[poll_one(name) for name in pending])

            for agent_name, status, result, error in poll_results:
                if status in ("done", "error"):
                    done.add(agent_name)
                    results[agent_name] = {"status": status, "result": result, "error": error}
                    if status == "done" and _is_temporary_agent(agent_name):
                        cleanup_msg = _cleanup_temporary_agent(agent_name)
                        results[agent_name]["result"] += f"\n[{cleanup_msg}]"
                    if status == "error" and fail_fast:
                        for remaining in agent_names:
                            if remaining not in done:
                                results[remaining] = {
                                    "status": "interrupted",
                                    "result": "",
                                    "error": "interrupted by fail_fast",
                                }
                        return _format_wait_results(results, polls, early_exit=agent_name)
                else:
                    results[agent_name]["status"] = status

            if not [name for name in agent_names if name not in done]:
                break

            await asyncio.sleep(poll_interval)

        for name in agent_names:
            if name not in done:
                results[name] = {
                    "status": "timeout",
                    "result": "",
                    "error": f"Timed out after {timeout}s",
                }

        return _format_wait_results(results, polls)


_NOTIFY_TRIGGER_TASK = (
    "---\n"
    "status: pending\n"
    "assigned_by: {assigned_by}\n"
    "assigned_at: {ts}\n"
    "---\n\n"
    "## Task\n"
    "[Process incoming notifications from sub-agents]\n\n"
    "## Result\n\n"
    "## Error\n"
)


async def _read_assigned_by(task_path: "Path") -> str:
    """Read the assigned_by field from a TASK.MD frontmatter."""
    if not task_path.exists():
        return ""
    async with aiofiles.open(task_path, encoding="utf-8") as f:
        content = await f.read()
    m = re.search(r"^assigned_by:\s*(.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else ""


async def _get_task_status_from_file(task_path: "Path") -> str:
    """Return the status field from a TASK.MD frontmatter, or empty string."""
    if not task_path.exists():
        return ""
    async with aiofiles.open(task_path, encoding="utf-8") as f:
        content = await f.read()
    m = re.search(r"^status:\s*(.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else ""


async def _wake_agent_if_idle(agent_name: str) -> None:
    """Write a trigger TASK.MD to wake an idle AgentRunner."""
    agent_dir = settings.agents_dir / agent_name
    status_path = agent_dir / "STATUS.json"
    if not status_path.exists():
        return
    try:
        state = json.loads(status_path.read_text(encoding="utf-8")).get("state", "")
    except (json.JSONDecodeError, OSError):
        return
    if state != "idle":
        return  # running or terminated — queue will be drained on next turn naturally

    task_path = agent_dir / "TASK.MD"
    status = await _get_task_status_from_file(task_path)

    if status == "pending":
        return  # already pending — AgentRunner will drain queue when it picks it up

    if status in ("done", "error"):
        # Don't overwrite an unconsumed real-task result UNLESS there are pending
        # notifications that need processing.  Notification trigger tasks
        # (assigned_by: notification) carry no result the parent needs to poll,
        # so they are always safe to overwrite.
        try:
            async with aiofiles.open(task_path, encoding="utf-8") as f:
                content = await f.read()
            assigned_by_m = re.search(r"^assigned_by:\s*(.+)$", content, re.MULTILINE)
            assigned_by_val = assigned_by_m.group(1).strip() if assigned_by_m else ""
            if assigned_by_val != "notification":
                consumed_m = re.search(r"^consumed_at:\s*\S", content, re.MULTILINE)
                if not consumed_m:
                    # Check if there are pending notifications — if so, we must
                    # wake the agent even though the previous result is unconsumed.
                    # The result is already captured in the notification queue.
                    try:
                        from app.backend.services.notification_queue import notification_queue as _nq
                        if _nq.pending_count(agent_name) == 0:
                            return  # no notifications, result not consumed — don't overwrite
                    except Exception:
                        return  # err on side of caution
        except Exception:
            return  # err on side of caution

    original_parent = await _read_assigned_by(task_path) or "master"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    async with aiofiles.open(task_path, "w", encoding="utf-8") as f:
        await f.write(_NOTIFY_TRIGGER_TASK.format(ts=ts, assigned_by=original_parent))


class NotifyParentTool(BaseTool):
    name = "notify_parent"
    description = (
        "Notify your parent agent that you have completed your work. "
        "Call this when done to push your result to the parent immediately "
        "instead of making the parent poll for it. "
        "The parent will be woken if idle, or receive the result on its next turn."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "result": {
                "type": "string",
                "description": "Summary of what you accomplished and key outputs.",
            },
            "status": {
                "type": "string",
                "enum": ["done", "error"],
                "description": "Whether you completed successfully or encountered an error.",
            },
        },
        "required": ["result", "status"],
    }
    risk_tier = RiskTier.AUTO

    def __init__(self, agent_dir: "Path") -> None:
        self._agent_dir = agent_dir

    async def execute(self, **params: Any) -> str:
        from app.backend.services.notification_queue import notification_queue

        result_text: str = params["result"]
        status: str = params.get("status", "done")

        task_path = self._agent_dir / "TASK.MD"
        parent_name = await _read_assigned_by(task_path)

        if not parent_name or parent_name in ("", "notification"):
            return "Error: no parent found in TASK.MD (assigned_by is missing or 'notification')."

        # "User" is the terminal sentinel — route through master
        if parent_name.lower() == "user":
            parent_name = "master"

        notification_queue.enqueue(
            parent_agent=parent_name,
            child_agent=self._agent_dir.name,
            status=status,
            result=result_text if status == "done" else "",
            error=result_text if status == "error" else "",
        )

        await _wake_agent_if_idle(parent_name)

        return f"Parent '{parent_name}' notified ({status})."


class ReadTaskResultTool(BaseTool):
    name = "read_task_result"
    description = "Read the '## Result' section from a sub-agent's TASK.MD."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Name of the agent whose result to read",
            },
        },
        "required": ["agent_name"],
    }
    risk_tier = RiskTier.AUTO

    async def execute(self, **params: Any) -> str:
        agent_name = params["agent_name"]
        path = _task_path(agent_name)
        if not path.exists():
            return f"Agent '{agent_name}': no TASK.MD"

        async with aiofiles.open(path, encoding="utf-8") as f:
            content = await f.read()

        m = re.search(r"## Result\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
        if not m:
            return f"Agent '{agent_name}': no ## Result section found"

        result = m.group(1).strip()
        msg = result if result else f"Agent '{agent_name}': ## Result section is empty"
        if _is_temporary_agent(agent_name):
            msg += f"\n[{_cleanup_temporary_agent(agent_name)}]"
        msg = truncate_tool_output(
            msg,
            cap=20_000,
            note=f"read file://app/agents/{agent_name}/TASK.MD for full result",
        )
        return msg
