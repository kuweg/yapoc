import asyncio
import json
import os
import signal
import subprocess
import sys
import textwrap
from datetime import datetime
from typing import Any

from app.config import settings
from app.utils.crash import server_exit_watcher

from . import BaseTool, RiskTier

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
    """
    Spawn a detached helper process that kills *old_pid* and starts a new server
    after *delay* seconds.

    Used when server_restart is called from inside the running backend — the
    deferred approach lets the current HTTP response complete before the kill fires.
    """
    # Encode the command as JSON so the inline script can parse it safely.
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


class ServerRestartTool(BaseTool):
    name = "server_restart"
    description = "Restart the YAPOC backend server. Use when the user asks to restart, reboot, or reset the server."
    input_schema: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
    risk_tier: RiskTier = RiskTier.AUTO

    async def execute(self, **params: Any) -> str:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        _RESUME_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RESUME_FILE.write_text(
            f"[{timestamp}] action: restart_server | context: user asked to restart | status: pending\n"
        )

        old_pid: int | None = None
        if _PID_FILE.exists():
            try:
                old_pid = int(_PID_FILE.read_text().strip())
            except ValueError:
                pass

        cmd = _build_uvicorn_cmd()

        # ── Self-restart: called from within the running backend ─────────────
        # Killing ourselves synchronously would tear down the event loop before
        # the response is sent.  Hand off to a detached helper that fires after
        # a short delay, giving the SSE stream time to deliver this message.
        if old_pid is not None and old_pid == os.getpid():
            _schedule_deferred_restart(old_pid, cmd, delay=3.0)
            _RESUME_FILE.write_text("")
            return (
                f"Server self-restart scheduled (fires in ~3 s). "
                f"Old PID: {old_pid}. "
                f"New backend will be at http://{settings.host}:{settings.port}."
            )

        # ── Normal restart: called from CLI, killing a daemon ────────────────
        if old_pid is not None:
            try:
                os.kill(old_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            _PID_FILE.unlink(missing_ok=True)

        await asyncio.sleep(1)

        proc = _spawn_server(cmd)
        _RESUME_FILE.write_text("")
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
    risk_tier: RiskTier = RiskTier.AUTO

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
