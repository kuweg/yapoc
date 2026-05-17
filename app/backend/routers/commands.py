"""Router for slash commands in the UI chat.

Reuses the logic from app/cli/main.py's _do_* helper functions but returns
strings instead of printing to console.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
from fastapi import APIRouter
from loguru import logger
from pydantic import BaseModel

from app.config import settings

router = APIRouter()

_PID_FILE = settings.project_root / ".yapoc.pid"
_SERVER_OUTPUT = settings.agents_dir / "master" / "SERVER_OUTPUT.MD"


class CommandRequest(BaseModel):
    command: str
    args: str = ""


class CommandResponse(BaseModel):
    response: str


# ── Helpers ──────────────────────────────────────────────────────────────────

def _read_pid() -> int | None:
    if _PID_FILE.exists():
        try:
            return int(_PID_FILE.read_text().strip())
        except ValueError:
            return None
    return None


def _write_pid(pid: int) -> None:
    _PID_FILE.write_text(str(pid))


def _remove_pid() -> None:
    if _PID_FILE.exists():
        _PID_FILE.unlink()


def _client() -> httpx.Client:
    return httpx.Client(base_url=settings.base_url, timeout=30)


# ── Command implementations (return strings, not console.print) ──────────────

def _do_help() -> str:
    return (
        "**Available commands:**\n\n"
        "| Command | Description |\n"
        "|---------|-------------|\n"
        "| `/help` | Show this help |\n"
        "| `/start` | Start the backend server |\n"
        "| `/stop` | Stop the backend server |\n"
        "| `/restart` | Restart the backend server |\n"
        "| `/status` | Show server & agent status |\n"
        "| `/ping` | Ping the server |\n"
        "| `/agents` | List all agents |\n"
        "| `/model` | Show current adapter/model |\n"
        "| `/sessions` | List recent sessions |\n"
        "| `/clear` | Clear conversation history |\n"
        "| `/cost` | Show session cost |\n"
        "| `/doctor` | Run doctor health check |\n"
        "| `/exit` | No-op in UI |\n"
    )


def _do_start() -> str:
    pid = _read_pid()
    if pid:
        return f"Server already running (PID {pid})"
    _SERVER_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(_SERVER_OUTPUT, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.backend.main:app", "--host", settings.host, "--port", str(settings.port)],
        stdout=log_fh,
        stderr=log_fh,
    )
    _write_pid(proc.pid)
    return f"Server started (PID {proc.pid}) on http://{settings.host}:{settings.port}"


def _do_stop() -> str:
    pid = _read_pid()
    if not pid:
        return "No running server found"
    try:
        os.kill(pid, signal.SIGTERM)
        _remove_pid()
        return f"Server stopped (PID {pid})"
    except ProcessLookupError:
        _remove_pid()
        return f"Process {pid} not found — cleaned up PID file"


def _do_restart() -> str:
    stop_msg = _do_stop()
    time.sleep(1)
    start_msg = _do_start()
    return f"{stop_msg}\n{start_msg}"


def _do_ping() -> str:
    t0 = time.perf_counter()
    try:
        with _client() as client:
            resp = client.get("/health")
            resp.raise_for_status()
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.TimeoutException):
        return "Server is not running"
    ms = (time.perf_counter() - t0) * 1000
    return f"pong — {ms:.1f}ms"


def _do_status() -> str:
    try:
        with _client() as client:
            health = client.get("/health").json()
            agents_data = client.get("/agents").json()
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.TimeoutException):
        return "Server is not running"

    lines = [f"**Server OK** — uptime {health.get('uptime', '?')}s", ""]
    lines.append("| Name | Status | Process | PID | Model | Task | Memory | Errors |")
    lines.append("|------|--------|---------|-----|-------|------|--------|--------|")

    for ag in agents_data:
        pid_str = str(ag["pid"]) if ag.get("pid") else "-"
        lines.append(
            f"| {ag['name']} | {ag['status']} | {ag.get('process_state', '-')} | {pid_str} "
            f"| {ag['model']} | {'yes' if ag['has_task'] else 'no'} "
            f"| {ag['memory_entries']} | {ag['health_errors']} |"
        )

    return "\n".join(lines)


def _do_agents_list() -> str:
    try:
        with _client() as client:
            data = client.get("/agents").json()
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.TimeoutException):
        return "Server is not running"

    lines = ["| Name | Status | Process | PID | Model | Task |", "|------|--------|---------|-----|-------|------|"]
    for ag in data:
        pid_str = str(ag["pid"]) if ag.get("pid") else "-"
        lines.append(
            f"| {ag['name']} | {ag['status']} | {ag.get('process_state', '-')} | {pid_str} "
            f"| {ag['model']} | {'yes' if ag['has_task'] else '-'} |"
        )
    return "\n".join(lines)


def _do_models_info() -> str:
    return f"**Adapter:** {settings.default_adapter}\n**Model:** {settings.default_model}"


def _do_sessions() -> str:
    from app.cli.sessions import list_sessions
    sessions = list_sessions()
    if not sessions:
        return "No sessions found"
    lines = ["| ID | Name | Messages | Created |", "|----|------|----------|---------|"]
    for s in sessions:
        lines.append(f"| {s.id} | {s.name} | {s.message_count} | {s.created_at} |")
    return "\n".join(lines)


def _do_doctor(args: str = "") -> str:
    """Run doctor health check by spawning the doctor agent."""
    import asyncio
    from app.utils.tools.delegation import SpawnAgentTool

    async def _run():
        spawn = SpawnAgentTool()
        args_lower = args.strip().lower()
        if "hard" in args_lower or "fix" in args_lower:
            task = "hard-fix: Read all agents' HEALTH.MD files, fix any stale errors or issues found, and notify master agent of the results via notify_parent tool."
        else:
            task = "run-health-check: Execute a full health check of all agents and report findings."
        result = await spawn.execute(
            agent_name="doctor",
            task=task,
        )
        return result

    return asyncio.run(_run())


# ── Router endpoint ─────────────────────────────────────────────────────────

@router.post("/commands", response_model=CommandResponse)
async def handle_command(req: CommandRequest) -> CommandResponse:
    """Handle a slash command and return the response text."""
    cmd = req.command.lower().strip()
    args = req.args.strip()

    logger.info("Slash command: {} args={!r}", cmd, args)

    if cmd in ("/help",):
        return CommandResponse(response=_do_help())
    elif cmd in ("/start",):
        return CommandResponse(response=_do_start())
    elif cmd in ("/stop",):
        return CommandResponse(response=_do_stop())
    elif cmd in ("/restart",):
        return CommandResponse(response=_do_restart())
    elif cmd in ("/status",):
        return CommandResponse(response=_do_status())
    elif cmd in ("/ping",):
        return CommandResponse(response=_do_ping())
    elif cmd in ("/agents",):
        return CommandResponse(response=_do_agents_list())
    elif cmd in ("/model",):
        return CommandResponse(response=_do_models_info())
    elif cmd in ("/sessions",):
        return CommandResponse(response=_do_sessions())
    elif cmd in ("/clear",):
        return CommandResponse(response="Conversation history cleared (client-side)")
    elif cmd in ("/cost",):
        return CommandResponse(response="Cost tracking is available in the UI cost bar")
    elif cmd in ("/doctor",):
        return CommandResponse(response=_do_doctor(args))
    elif cmd in ("/exit", "/quit"):
        return CommandResponse(response="Exit is a no-op in the web UI")
    else:
        return CommandResponse(response=f"Unknown command: {cmd} — type /help for available commands")
