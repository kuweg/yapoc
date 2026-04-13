import asyncio
import json
import os
import signal
import subprocess
import sys

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.backend.models import AgentStatus, AgentDetail
from app.backend.services import AgentService, _read_status_json, _pid_alive, _is_stale_status
from app.config import settings
from app.utils.crash import agent_exit_watcher, count_crashes

router = APIRouter(prefix="/agents")
_service = AgentService()


@router.get("", response_model=list[AgentStatus])
async def list_agents():
    return await _service.get_all_statuses()


@router.get("/{name}/memory")
async def get_memory(name: str):
    try:
        content = await _service.get_agent_file(name, "MEMORY.MD")
        return {"name": name, "content": content}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{name}/result")
async def get_result(name: str):
    try:
        content = await _service.get_agent_file(name, "RESULT.MD")
        return {"name": name, "content": content}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{name}/health")
async def get_health(name: str):
    try:
        content = await _service.get_agent_file(name, "HEALTH.MD")
        return {"name": name, "content": content}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{name}/restart")
async def restart_agent(name: str):
    try:
        await _service.restart_agent(name)
        return {"status": "ok", "name": name}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{name}/status")
async def get_agent_status(name: str):
    agent_dir = settings.agents_dir / name
    if not agent_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    status = _read_status_json(agent_dir)
    if not status:
        return {"name": name, "process_state": "", "pid": None, "task_summary": ""}
    pid = status.get("pid")
    alive = _pid_alive(pid) if pid else False
    state = status.get("state", "")
    if state != "terminated" and pid and not alive:
        state = "terminated"
    return {
        "name": name,
        "process_state": state,
        "pid": pid,
        "alive": alive,
        "task_summary": status.get("task_summary", ""),
        "started_at": status.get("started_at"),
        "updated_at": status.get("updated_at"),
        "idle_since": status.get("idle_since"),
    }


@router.post("/{name}/ping")
async def ping_agent(name: str):
    """Ping an agent and return detailed diagnostic info."""
    from datetime import datetime, timezone

    agent_dir = settings.agents_dir / name
    if not agent_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    status = _read_status_json(agent_dir)
    if not status:
        return {
            "name": name,
            "alive": False,
            "state": "idle",
            "pid": None,
            "stale": False,
            "last_heartbeat": None,
            "diagnostic": "Agent has no STATUS.json — never started or status cleared",
        }

    pid = status.get("pid")
    alive = _pid_alive(pid) if pid else False
    state = status.get("state", "")
    stale = _is_stale_status(status)
    last_heartbeat = status.get("updated_at")

    # Normalise state the same way get_agent_status does
    if state != "terminated" and pid and not alive:
        state = "terminated"

    # Build human-readable diagnostic
    if alive and pid:
        diagnostic = f"Agent is alive and running (PID {pid})"
    elif pid and not alive:
        diagnostic = f"Agent process is dead (PID {pid} not found)"
    elif stale and last_heartbeat:
        # Calculate how long ago the heartbeat was
        try:
            updated_at = datetime.fromisoformat(last_heartbeat.replace("Z", "+00:00"))
            age_seconds = int((datetime.now(timezone.utc) - updated_at).total_seconds())
            if age_seconds >= 60:
                age_str = f"{age_seconds // 60}m ago"
            else:
                age_str = f"{age_seconds}s ago"
            diagnostic = f"Agent status is stale (last seen {age_str})"
        except Exception:
            diagnostic = "Agent status is stale (last heartbeat timestamp unreadable)"
    elif state == "idle" or not state:
        diagnostic = "Agent is idle"
    else:
        diagnostic = f"Agent state: {state}"

    return {
        "name": name,
        "alive": alive,
        "state": state,
        "pid": pid,
        "stale": stale,
        "last_heartbeat": last_heartbeat,
        "diagnostic": diagnostic,
    }


@router.post("/{name}/spawn")
async def spawn_agent(name: str):
    agent_dir = settings.agents_dir / name
    if not agent_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    # Check if already running
    status = _read_status_json(agent_dir)
    if status and status.get("pid") and _pid_alive(status["pid"]):
        return {"status": "already_running", "name": name, "pid": status["pid"]}

    output_path = agent_dir / "OUTPUT.MD"
    crash_path = agent_dir / "CRASH.MD"
    log_fh = open(output_path, "a", encoding="utf-8")
    restart_count = count_crashes(crash_path)
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.agents.base.runner_entry", "--agent", name],
        start_new_session=True,
        stdout=log_fh,
        stderr=log_fh,
    )
    agent_exit_watcher(proc, output_path, crash_path, name, restart_count)
    return {"status": "spawned", "name": name, "pid": proc.pid}


@router.post("/{name}/kill")
async def kill_agent(name: str):
    agent_dir = settings.agents_dir / name
    if not agent_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    status = _read_status_json(agent_dir)
    if not status or not status.get("pid"):
        raise HTTPException(status_code=400, detail=f"Agent '{name}' has no known PID")

    pid = status["pid"]
    if not _pid_alive(pid):
        return {"status": "not_running", "name": name, "pid": pid}

    try:
        os.kill(pid, signal.SIGTERM)
        return {"status": "killed", "name": name, "pid": pid}
    except ProcessLookupError:
        return {"status": "not_running", "name": name, "pid": pid}


# --- New endpoints ---

@router.get("/events/stream")
async def agent_events_stream():
    """SSE endpoint that streams agent state changes as events."""
    import asyncio
    import uuid
    from datetime import datetime, timezone

    async def event_generator():
        prev_states: dict[str, str] = {}
        while True:
            try:
                statuses = await _service.get_all_statuses()
                events = []
                for agent in statuses:
                    prev = prev_states.get(agent.name)
                    curr = agent.state or agent.status
                    if prev is not None and prev != curr:
                        event_type = "status_changed"
                        if curr == "running":
                            event_type = "task_assigned"
                        elif curr in ("done", "idle") and prev == "running":
                            event_type = "task_completed"
                        elif curr == "error":
                            event_type = "task_failed"
                        events.append({
                            "id": str(uuid.uuid4()),
                            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "agent_name": agent.name,
                            "event_type": event_type,
                            "message": f"{agent.name} changed from {prev} to {curr}",
                            "level": "error" if curr == "error" else "info",
                        })
                    prev_states[agent.name] = curr

                for ev in events:
                    import json as _json
                    yield f"data: {_json.dumps(ev)}\n\n"

                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{name}/output")
async def get_agent_output(name: str, lines: int = 200):
    """Return last N lines of OUTPUT.MD (subprocess stdout/stderr)."""
    agent_dir = settings.agents_dir / name
    if not agent_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    output_path = agent_dir / "OUTPUT.MD"
    if not output_path.exists():
        return {"name": name, "content": "", "lines": 0}
    text = output_path.read_text(encoding="utf-8", errors="replace")
    all_lines = text.splitlines()
    tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
    return {"name": name, "content": "\n".join(tail), "lines": len(tail), "total_lines": len(all_lines)}


@router.get("/{name}/live")
async def get_agent_live(name: str):
    """Return current model generation buffer (LIVE.MD) — empty when agent is idle."""
    agent_dir = settings.agents_dir / name
    if not agent_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    live_path = agent_dir / "LIVE.MD"
    content = live_path.read_text(encoding="utf-8", errors="replace") if live_path.exists() else ""
    return {"name": name, "content": content}


@router.get("/{name}", response_model=AgentDetail)
async def get_agent_detail(name: str):
    agent_dir = settings.agents_dir / name
    if not agent_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    detail = await _service.get_agent_detail(name)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    return detail
