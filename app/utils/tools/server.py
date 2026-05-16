import asyncio
import json
import os
import signal
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.utils.crash import server_exit_watcher

from . import BaseTool

_PID_FILE = settings.project_root / ".yapoc.pid"
_RESUME_FILE = settings.agents_dir / "master" / "RESUME.MD"
_SERVER_OUTPUT = settings.agents_dir / "master" / "SERVER_OUTPUT.MD"
_SERVER_CRASH = settings.agents_dir / "master" / "SERVER_CRASH.MD"


def _build_uvicorn_cmd() -> list[str]:
    return [
        sys.executable, "-m", "uvicorn", "app.backend.main:app",
        "--host", settings.host,
        "--port", str(settings.port),
    ]


def _spawn_server(cmd: list[str]) -> subprocess.Popen:
    """Start a new uvicorn server, append logs to SERVER_OUTPUT.MD."""
    _SERVER_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(_SERVER_OUTPUT, "a", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdout=log_fh, stderr=log_fh)
    _PID_FILE.write_text(str(proc.pid))
    server_exit_watcher(proc, _SERVER_OUTPUT, _SERVER_CRASH)
    return proc


def _schedule_deferred_restart(old_pid: int, cmd: list[str], delay: float = 3.0) -> None:
    cmd_json = json.dumps(cmd)
    pid_file = str(_PID_FILE)
    server_output = str(_SERVER_OUTPUT)

    script = textwrap.dedent(f"""\
        import json, os, signal, subprocess, sys, time
        time.sleep({delay})
        try:
            os.kill({old_pid}, signal.SIGTERM)
        except ProcessLookupError:
            pass
        time.sleep(1.5)
        cmd = json.loads({cmd_json!r})
        log = open({server_output!r}, "a")
        p = subprocess.Popen(cmd, stdout=log, stderr=log)
        open({pid_file!r}, "w").write(str(p.pid))
    """)
    subprocess.Popen(
        [sys.executable, "-c", script],
        start_new_session=True,
        close_fds=True,
    )


async def _save_resume_state(reason: str = "", next_action: str = "", session_id: str = "") -> str:
    """Gather agent state and write a structured RESUME.MD for post-restart continuity."""
    agents_dir = settings.agents_dir
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    active: list[str] = []
    for agent_dir in sorted(agents_dir.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name in ("base",):
            continue
        status_path = agent_dir / "STATUS.json"
        task_path = agent_dir / "TASK.MD"
        if status_path.exists():
            try:
                sj = json.loads(status_path.read_text())
                state = sj.get("state", "")
                if state in ("running", "idle", "spawning"):
                    task_summary = sj.get("task_summary", "")
                    fm = {}
                    if task_path.exists():
                        t = task_path.read_text(encoding="utf-8")
                        for line in t.splitlines():
                            if ":" in line:
                                k, _, v = line.partition(":")
                                fm[k.strip()] = v.strip()
                    tid = fm.get("task_id", "")
                    sid = fm.get("session_id", "")
                    active.append(
                        f"  - {agent_dir.name} (state: {state}, task_id: {tid[:16] if tid else 'none'}, session: {sid[:8] if sid else 'none'})"
                    )
            except Exception:
                pass

    content = (
        f"---\n"
        f"restart_at: {now}\n"
        f"restart_reason: {reason}\n"
        f"next_action: {next_action}\n"
        f"session_id: {session_id}\n"
        f"---\n\n"
        f"## Active agents\n"
        + ("\n".join(active) if active else "  (none)\n")
    )

    _RESUME_FILE.parent.mkdir(parents=True, exist_ok=True)
    _RESUME_FILE.write_text(content)
    return content


async def _notify_agents_pre_shutdown() -> None:
    """Publish prepare_shutdown to all active agent Redis inboxes."""
    agents_dir = settings.agents_dir
    try:
        from app.backend.message_bus import bus
    except Exception:
        return

    if not bus.connected:
        return

    for agent_dir in agents_dir.iterdir():
        if not agent_dir.is_dir() or agent_dir.name in ("base", "master"):
            continue
        status_path = agent_dir / "STATUS.json"
        if not status_path.exists():
            continue
        try:
            sj = json.loads(status_path.read_text())
            if sj.get("state") in ("running", "idle"):
                await bus.stream_add(
                    f"agent:{agent_dir.name}:inbox",
                    {"type": "prepare_shutdown", "reason": "server restart"},
                    agent_name="master",
                )
        except Exception:
            pass


class ServerRestartTool(BaseTool):
    name = "server_restart"
    description = (
        "Restart the YAPOC backend server. Saves active agent state to RESUME.MD "
        "and notifies sub-agents before shutdown so work can be resumed after restart."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Why the server is being restarted (e.g. 'applying config changes')",
            },
            "next_action": {
                "type": "string",
                "description": "What to do after restart (e.g. 'wait for keeper then summarize')",
            },
        },
        "required": [],
    }

    def __init__(
        self,
        agent_dir: "Path | None" = None,
        session_id: str | None = None,
    ) -> None:
        self._session_id = session_id

    async def execute(self, **params: Any) -> str:
        reason = str(params.get("reason", "user requested"))
        next_action = str(params.get("next_action", "check RESUME.MD for pending work"))

        # 1. Save structured resume state
        await _save_resume_state(
            reason=reason,
            next_action=next_action,
            session_id=self._session_id or "",
        )

        # 2. Notify sub-agents to save their state
        await _notify_agents_pre_shutdown()

        old_pid: int | None = None
        if _PID_FILE.exists():
            try:
                old_pid = int(_PID_FILE.read_text().strip())
            except ValueError:
                pass

        cmd = _build_uvicorn_cmd()

        # Self-restart: hand off to detached helper
        if old_pid is not None and old_pid == os.getpid():
            _schedule_deferred_restart(old_pid, cmd, delay=3.0)
            return (
                f"Server self-restart scheduled (fires in ~3 s). "
                f"RESUME.MD saved with {reason!r}. "
                f"Sub-agents notified. New backend will be at http://{settings.host}:{settings.port}."
            )

        # Normal restart (CLI-initiated)
        if old_pid is not None:
            try:
                os.kill(old_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            _PID_FILE.unlink(missing_ok=True)

        await asyncio.sleep(1)
        proc = _spawn_server(cmd)
        return f"Server restarted. Old PID: {old_pid or 'none'}, New PID: {proc.pid}"


class ProcessRestartTool(BaseTool):
    name = "process_restart"
    description = (
        "Restart the YAPOC CLI process itself (the interactive shell you are running in). "
        "This kills and re-launches the entire 'poetry run yapoc' process. "
        "Use ONLY when the user wants to reload code, refresh imports, or restart YOU (the agent). "
        "Do NOT use this for restarting the backend/API server — use server_restart for that."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Why the process is being restarted"},
            "task": {"type": "string", "description": "What to do after restart (the pending task to continue)"},
        },
        "required": ["reason", "task"],
    }

    async def execute(self, **params: Any) -> str:
        reason = params.get("reason", "user requested")
        task = params.get("task", "Inform the user the restart is complete.")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        _RESUME_FILE.parent.mkdir(parents=True, exist_ok=True)
        existing = _RESUME_FILE.read_text() if _RESUME_FILE.exists() else ""
        if not existing.strip():
            _RESUME_FILE.write_text(
                f"time: {timestamp}\n"
                f"reason: {reason}\n"
                f"task: {task}\n"
            )

        print("\n↺ Reloading YAPOC...")
        os.execvp(sys.executable, [sys.executable, "-m", "app.cli.main"])
