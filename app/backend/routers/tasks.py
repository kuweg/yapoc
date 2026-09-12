import asyncio
import json
import re
import uuid as _uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.backend.models import TaskRequest, TaskResponse
from app.utils.adapters import CompactEvent, Message, MessageBoundary, ModelSwapped, TextDelta, ThinkingDelta, ToolDone, ToolStart, UsageStats
from app.utils.db import create_queued_task, get_queued_task, recent_tasks_queue

from app.backend.services.task_progress import present_task

router = APIRouter()


def _build_whiteboard_context(task: str) -> tuple[str, list[dict[str, str]]]:
    from app.utils.whiteboard import build_whiteboard_context
    try:
        return build_whiteboard_context(task)
    except (KeyError, ValueError) as exc:
        detail = exc.args[0] if isinstance(exc, KeyError) and exc.args else str(exc)
        raise HTTPException(400, detail) from exc


def _book_context(task: str) -> str:
    from app.backend.services.books import build_book_context
    return build_book_context(task)


def _parse_history(raw: list[dict] | None) -> list[Message] | None:
    if not raw:
        return None
    return [Message(role=m["role"], content=m["content"]) for m in raw]


def _event_to_dict(event: Any) -> dict | None:
    if isinstance(event, MessageBoundary):
        return {"type": "message_boundary"}
    if isinstance(event, ThinkingDelta):
        return {"type": "thinking", "text": event.text}
    if isinstance(event, TextDelta):
        return {"type": "text", "text": event.text}
    if isinstance(event, ToolStart):
        return {"type": "tool_start", "name": event.name, "input": event.input}
    if isinstance(event, ToolDone):
        return {"type": "tool_done", "name": event.name, "result": event.result, "is_error": event.is_error}
    if isinstance(event, CompactEvent):
        return {
            "type": "compact",
            "reason": event.reason,
            "tokens_before": event.tokens_before,
            "tokens_after": event.tokens_after,
        }
    if isinstance(event, ModelSwapped):
        return {
            "type": "model_swapped",
            "agent": event.agent,
            "adapter": event.adapter,
            "model": event.model,
        }
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
    from app.backend.services.notes import build_note_context
    note_context, notes = build_note_context(request.task, request.note_ids)
    whiteboard_context, whiteboards = _build_whiteboard_context(request.task)
    metadata = json.dumps({"history": request.history, "notes": notes, "whiteboards": whiteboards})
    task = create_queued_task(
        id=task_id,
        prompt=request.task + note_context + whiteboard_context + _book_context(request.task),
        source=request.source or "ui",
        session_id=request.session_id or task_id,
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
    session_id: str | None = Query(None),
):
    """List recent tasks from the queue."""
    if session_id:
        from app.utils.db import session_tasks_queue
        rows = session_tasks_queue(session_id, limit=limit)
        if status:
            rows = [row for row in rows if row['status'] == status]
    else:
        rows = recent_tasks_queue(limit=limit, status=status)
    return [present_task(row) for row in rows]


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Get a single task by ID."""
    task = get_queued_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return present_task(task)


@router.get("/tasks/{task_id}/evidence/{seq}")
async def task_evidence(task_id: str, seq: int):
    """Return a captured tool result, scoped to its exact execution ID."""
    from fastapi.responses import PlainTextResponse
    from app.utils.db import get_db
    row = get_db().execute('SELECT payload FROM task_events WHERE task_id=? AND seq=?', (task_id, seq)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail='Evidence not found')
    event = json.loads(row['payload'])
    if event.get('type') != 'tool_done':
        raise HTTPException(status_code=404, detail='Evidence not found')
    return PlainTextResponse(str(event.get('result', '')), headers={'X-Content-Type-Options': 'nosniff'})


@router.get("/sessions/{session_id}/events")
async def get_session_events(
    session_id: str,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Return recent events from a session's event log for playback."""
    from app.config import settings

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session_id):
        raise HTTPException(400, "Invalid session ID")
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


@router.post("/tasks/{task_id}/cancel")
async def cancel_queued_task(task_id: str):
    from app.backend.dispatcher import cancel_task
    if not get_queued_task(task_id):
        raise HTTPException(404, "Task not found")
    await cancel_task(task_id)
    return get_queued_task(task_id)


@router.post("/task/stream")
async def submit_task_stream(request: TaskRequest):
    """SSE is a replayable view of a durable run, not its execution owner."""
    from app.backend.services.task_runtime import read_events
    task_id = request.task_id or str(_uuid.uuid4())
    session_id = request.session_id or task_id
    row = get_queued_task(task_id)
    if row and row.get("session_id") != session_id:
        raise HTTPException(409, "Task ID belongs to another session")
    if not row:
        from app.backend.services.notes import build_note_context
        from app.backend.services.uploads import build_attachment_injection, resolve_file_refs_in_text
        note_context, notes = build_note_context(request.task, request.note_ids)
        whiteboard_context, whiteboards = _build_whiteboard_context(request.task)
        # Resolve attachment IDs from two sources: (1) the explicit `attachments`
        # list the frontend sends, and (2) any `@file:<id>` / `@file:<name>`
        # references embedded in the prompt text itself. The latter is a fallback
        # for when the frontend failed to resolve a reference (e.g. a full
        # `@file:<hex32>` pasted directly, which never populates the client's
        # upload list) — the reference must still resolve to the real file.
        attachment_ids: list[str] = list(request.attachments or [])
        for fid in resolve_file_refs_in_text(request.task or "", owner="local"):
            if fid not in attachment_ids:
                attachment_ids.append(fid)
        suffix, attachments = "", []
        if attachment_ids:
            suffix, attachments = build_attachment_injection(attachment_ids, owner="local")
        row = create_queued_task(id=task_id, prompt=request.task + suffix + note_context + whiteboard_context + _book_context(request.task),
                                 source=request.source or "ui", session_id=session_id,
                                 metadata=json.dumps({"history": request.history, "attachments": attachments, "notes": notes, "whiteboards": whiteboards, "transport": "sse"}))
    metadata = json.loads(row.get("metadata") or "{}")

    async def event_generator():
        cursor = request.after_seq
        yield f'data: {json.dumps({"type": "status", "state": "queued", "task_id": task_id, "text": "Queued for master"})}\n\n'
        if metadata.get("attachments"):
            yield f'data: {json.dumps({"type": "attachments", "data": metadata["attachments"]})}\n\n'
        while True:
            events = read_events(task_id, cursor)
            for event in events:
                cursor = event["seq"]
                yield f"data: {json.dumps(event)}\n\n"
            state = get_queued_task(task_id)
            if state and state["status"] not in {"pending", "running"}:
                if events:
                    continue  # exhaust the final page before closing
                if state["status"] != "done":
                    yield f'data: {json.dumps({"type": "error", "error": state.get("error") or state["status"]})}\n\n'
                state = present_task(state)
                if state.get('structured_result'):
                    yield f'data: {json.dumps({"type": "task_result", "result": state["structured_result"]})}\n\n'
                yield "data: [DONE]\n\n"
                return
            yield ": keepalive\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post('/tasks/{task_id}/recover')
async def recover_task(task_id: str):
    from app.backend.services.recovery import recover_interrupted_tasks
    row = get_queued_task(task_id)
    if not row:
        raise HTTPException(404, 'Task not found')
    if row['status'] not in {'interrupted', 'blocked', 'error', 'timeout', 'failed'} and present_task(row)['progress']['state'] != 'blocked':
        raise HTTPException(409, 'Only interrupted or unsuccessful tasks can resume')
    recover_interrupted_tasks(task_id, manual=True)
    return present_task(get_queued_task(task_id))
