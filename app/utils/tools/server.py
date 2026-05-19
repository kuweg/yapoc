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
    port = settings.port

    # The old helper slept a flat 1.5s after SIGTERM, then spawned the new
    # uvicorn unconditionally. If the old process's lifespan shutdown took
    # longer than 1.5s (real for any non-trivial dep tree, especially the
    # Telegram bot's 30s long-poll), the new uvicorn launched while the
    # old one was still on :8000. Result: two uvicorns alive, two Telegram
    # bots polling, user sees duplicate replies.
    #
    # The new helper waits for the port to actually free (up to 25s) before
    # spawning. If SIGTERM didn't take, escalates to SIGKILL.
    script = textwrap.dedent(f"""\
        import json, os, signal, socket, subprocess, sys, time

        OLD_PID = {old_pid}
        PORT = {port}
        CMD = json.loads({cmd_json!r})
        PID_FILE = {pid_file!r}
        SERVER_OUTPUT = {server_output!r}

        def _alive(p):
            try:
                os.kill(p, 0)
                return True
            except (ProcessLookupError, PermissionError):
                return False

        def _port_held():
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.2)
            try:
                s.connect(("127.0.0.1", PORT))
                return True
            except OSError:
                return False
            finally:
                try: s.close()
                except OSError: pass

        time.sleep({delay})

        # 1. Graceful SIGTERM.
        try:
            os.kill(OLD_PID, signal.SIGTERM)
        except ProcessLookupError:
            pass

        # 2. Wait up to 10s for clean exit.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if not _alive(OLD_PID) and not _port_held():
                break
            time.sleep(0.3)

        # 3. Force-kill if it ignored SIGTERM (Telegram bot can pin the loop).
        if _alive(OLD_PID):
            try:
                os.kill(OLD_PID, signal.SIGKILL)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if not _alive(OLD_PID):
                    break
                time.sleep(0.2)

        # 4. Wait for the port to actually free (TCP TIME_WAIT + slow close).
        deadline = time.monotonic() + 10.0
        while _port_held() and time.monotonic() < deadline:
            time.sleep(0.3)

        # 5. Spawn the new uvicorn.
        log = open(SERVER_OUTPUT, "a")
        p = subprocess.Popen(CMD, stdout=log, stderr=log)
        open(PID_FILE, "w").write(str(p.pid))
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

        # Normal restart (CLI-initiated). Wait for the old uvicorn to fully
        # exit AND release the port before spawning a replacement, so we don't
        # accumulate orphaned instances (each of which would run its own
        # Telegram bot and cause duplicate message processing).
        if old_pid is not None:
            try:
                os.kill(old_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            _PID_FILE.unlink(missing_ok=True)

            deadline = asyncio.get_event_loop().time() + 10.0
            while asyncio.get_event_loop().time() < deadline:
                try:
                    os.kill(old_pid, 0)
                except ProcessLookupError:
                    break
                await asyncio.sleep(0.3)
            else:
                # Escalate to SIGKILL if still alive.
                try:
                    os.kill(old_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        # Wait for port to actually free before spawning replacement.
        import socket as _socket
        port_deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < port_deadline:
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            s.settimeout(0.2)
            try:
                s.connect(("127.0.0.1", settings.port))
                s.close()
                await asyncio.sleep(0.3)
            except OSError:
                s.close()
                break

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
