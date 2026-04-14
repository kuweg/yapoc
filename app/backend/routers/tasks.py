import asyncio
import json
import uuid as _uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.agents.master.agent import master_agent
from app.backend.models import ApprovalRequest, TaskRequest, TaskResponse
from app.backend.services.agent_results import build_result_injection, collect_agent_results
from app.utils.adapters import Message, TextDelta, ThinkingDelta, ToolDone, ToolStart, UsageStats
from app.utils.db import create_queued_task, get_queued_task, recent_tasks_queue

router = APIRouter()

# Module-level store for pending tool approvals.
# Keys are request UUIDs; safe for single-process uvicorn.
_pending_approvals: dict[str, asyncio.Event] = {}
_approval_results: dict[str, bool] = {}


def _parse_history(raw: list[dict] | None) -> list[Message] | None:
    if not raw:
        return None
    return [Message(role=m["role"], content=m["content"]) for m in raw]


def _event_to_dict(event: Any) -> dict | None:
    if isinstance(event, ThinkingDelta):
        return {"type": "thinking", "text": event.text}
    if isinstance(event, TextDelta):
        return {"type": "text", "text": event.text}
    if isinstance(event, ToolStart):
        return {"type": "tool_start", "name": event.name, "input": event.input}
    if isinstance(event, ToolDone):
        return {"type": "tool_done", "name": event.name, "result": event.result, "is_error": event.is_error}
    if isinstance(event, UsageStats):
        return {
            "type": "usage_stats",
            "input_tokens": event.input_tokens,
            "output_tokens": event.output_tokens,
            "tokens_per_second": event.tokens_per_second,
            "context_window": event.context_window,
        }
    return None


@router.post("/task")
async def submit_task(request: TaskRequest):
    """Fire-and-forget: enqueue a task and return immediately.

    The background dispatcher picks it up and executes it asynchronously.
    Poll GET /tasks/{task_id} for status/result, or subscribe via WebSocket.
    """
    task_id = str(_uuid.uuid4())
    metadata = json.dumps({"history": request.history}) if request.history else None
    task = create_queued_task(
        id=task_id,
        prompt=request.task,
        source=request.source or "ui",
        metadata=metadata,
    )
    # Push WebSocket event
    try:
        from app.backend.websocket import ws_manager
        await ws_manager.push_event("task_created", {"task": task})
    except Exception:
        pass
    return {"task_id": task_id, "status": "pending"}


@router.get("/tasks")
async def list_tasks(
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
):
    """List recent tasks from the queue."""
    return recent_tasks_queue(limit=limit, status=status)


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Get a single task by ID."""
    task = get_queued_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/approvals")
async def list_approvals():
    """List pending approval requests."""
    from app.backend.approval_queue import get_pending
    return get_pending()


@router.post("/approvals/{request_id}/resolve")
async def resolve_approval_endpoint(request_id: str, body: ApprovalRequest):
    """Approve or deny a queued tool execution."""
    from app.backend.approval_queue import resolve_approval
    result = resolve_approval(request_id, body.approved)
    if not result:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return result


@router.get("/sessions/{session_id}/events")
async def get_session_events(
    session_id: str,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Return recent events from a session's event log for playback."""
    from app.config import settings

    event_file = settings.project_root / "data" / "sessions" / session_id / "events.jsonl"
    if not event_file.exists():
        return []
    try:
        lines = event_file.read_text(encoding="utf-8").strip().split("\n")
        events = []
        for line in lines[offset:offset + limit]:
            if line.strip():
                events.append(json.loads(line))
        return events
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/task/approve/{request_id}")
async def approve_tool(request_id: str, body: ApprovalRequest):
    ev = _pending_approvals.get(request_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="No pending approval with that ID")
    _approval_results[request_id] = body.approved
    ev.set()
    return {"status": "ok"}


@router.post("/task/stream")
async def submit_task_stream(request: TaskRequest):
    history = _parse_history(request.history)

    # Collect completed background agent results and inject as system context
    # rather than concatenating into the user task string.
    finished = await collect_agent_results()
    task = request.task
    if finished:
        notifications_text = build_result_injection(finished)
        if history is None:
            history = []
        history = history + [Message(role="system", content=notifications_text)]

    # run_stream_with_tools expects history to already contain the current user
    # message as its last entry (matching CLI behaviour in _send_to_agent).
    if history is not None:
        history = history + [Message(role="user", content=task)]

    merged: asyncio.Queue[dict | None] = asyncio.Queue()

    # Track request-local pending approvals for cleanup on disconnect
    local_pending: dict[str, asyncio.Event] = {}

    async def approval_gate(name: str, input_data: dict) -> bool:
        req_id = str(_uuid.uuid4())
        ev = asyncio.Event()
        local_pending[req_id] = ev
        _pending_approvals[req_id] = ev

        await merged.put({
            "type": "tool_approval_request",
            "request_id": req_id,
            "name": name,
            "input": input_data,
        })

        try:
            await asyncio.wait_for(ev.wait(), timeout=300.0)
        except asyncio.TimeoutError:
            pass

        approved = _approval_results.pop(req_id, False)
        _pending_approvals.pop(req_id, None)
        local_pending.pop(req_id, None)

        await merged.put({
            "type": "tool_approval_result",
            "request_id": req_id,
            "approved": approved,
        })
        return approved

    async def drain_agent() -> None:
        try:
            async for event in master_agent.handle_task_stream(
                task, history=history, approval_gate=approval_gate,
                source=request.source,
            ):
                item = _event_to_dict(event)
                if item:
                    await merged.put(item)
        except Exception as exc:
            await merged.put({"type": "error", "error": str(exc)})
        finally:
            await merged.put(None)  # sentinel

    # Sentinel value used to signal the heartbeat loop to stop
    _HEARTBEAT_STOP = object()
    _heartbeat_done = asyncio.Event()

    async def heartbeat() -> None:
        """Emit SSE keepalive pings every 15 s to prevent proxy/browser timeouts.

        Long agent tasks (sub-agents running for minutes) produce no SSE data
        during tool execution.  Without periodic data, reverse proxies and
        browsers drop the connection after 30-120 s of silence, causing the
        "network error" the user sees.  SSE comment lines (': keepalive') are
        invisible to the client but reset the idle timer on every intermediary.
        """
        try:
            while True:
                try:
                    await asyncio.wait_for(_heartbeat_done.wait(), timeout=15.0)
                    return  # agent finished — stop heartbeat
                except asyncio.TimeoutError:
                    # Queue a keepalive sentinel; event_generator handles it
                    await merged.put({"type": "keepalive"})
        except asyncio.CancelledError:
            pass

    agent_task = asyncio.create_task(drain_agent())
    heartbeat_task = asyncio.create_task(heartbeat())

    async def event_generator():
        try:
            while True:
                item = await merged.get()
                if item is None:
                    # Agent finished — stop heartbeat and send DONE
                    _heartbeat_done.set()
                    yield "data: [DONE]\n\n"
                    return
                if item.get("type") == "keepalive":
                    # SSE comment line — keeps connection alive, invisible to client
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(item)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            _heartbeat_done.set()
            agent_task.cancel()
            heartbeat_task.cancel()
            # Deny any pending approvals so the agent task unblocks and exits
            for req_id, ev in list(local_pending.items()):
                _approval_results[req_id] = False
                ev.set()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
