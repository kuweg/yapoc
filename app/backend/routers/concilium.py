"""Concilium API router — deliberation endpoints for the YAPOC backend.

Provides REST + SSE endpoints for the Concilium multi-agent deliberation
framework. Used by the ConciliumTab UI component.
"""

from __future__ import annotations

import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from loguru import logger

from app.utils.concilium import (
    CONCILIUM_DIR,
    ConciliumOrchestrator,
    DeliberationResult,
    DeliberationStatus,
    COUNSELOR_ROLES,
)

concilium_router = APIRouter(prefix="/concilium", tags=["concilium"])


# ── Request/Response models (inline dicts, no pydantic dep) ──────────────────

def _session_info(session_dir: Path) -> dict | None:
    """Read session metadata from events.jsonl."""
    events_path = session_dir / "events.jsonl"
    if not events_path.exists():
        return None

    events = []
    with open(events_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not events:
        return None

    first = events[0]
    last = events[-1]

    return {
        "session_id": session_dir.name,
        "started_at": first.get("timestamp", ""),
        "last_event_at": last.get("timestamp", ""),
        "event_count": len(events),
        "status": _infer_status(events),
        "roles": first.get("data", {}).get("roles", list(COUNSELOR_ROLES.keys())),
    }


def _infer_status(events: list[dict]) -> str:
    """Infer deliberation status from event types."""
    types = [e.get("type", "") for e in events]
    if "approved" in types:
        return "approved"
    if "rejected" in types:
        return "rejected"
    if "escalated" in types:
        return "escalated"
    if any("round_" in t for t in types):
        return "in_progress"
    return "pending"


# ── Endpoints ────────────────────────────────────────────────────────────────


@concilium_router.post("/deliberate")
async def start_deliberation(body: dict) -> dict:
    """Start a new deliberation on a plan.

    Request body:
    {
        "plan_text": "...",
        "roles": ["architect", "critic", ...],  # optional, defaults to all
        "max_rounds": 3  # optional
    }

    Returns session_id for polling.
    """
    plan_text = body.get("plan_text", "").strip()
    if not plan_text:
        raise HTTPException(status_code=400, detail="plan_text is required")

    roles = body.get("roles")
    max_rounds = body.get("max_rounds", 3)

    orchestrator = ConciliumOrchestrator(
        session_id=None,  # auto-generate
        max_rounds=max_rounds,
        counselor_roles=roles,
    )

    # Run deliberation
    result = await orchestrator.deliberate(plan_text)

    return {
        "session_id": orchestrator.session_id,
        "status": result.status.value,
        "rounds_completed": len(result.rounds),
        "duration_s": result.duration_s,
        "approved_plan": result.approved_plan if result.status == DeliberationStatus.APPROVED else None,
        "escalation_summary": result.escalation_summary if result.status == DeliberationStatus.ESCALATED else None,
    }


@concilium_router.get("/status/{session_id}")
async def get_status(session_id: str) -> dict:
    """Get the current status of a deliberation session."""
    session_dir = CONCILIUM_DIR / session_id
    if not session_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    info = _session_info(session_dir)
    if not info:
        raise HTTPException(status_code=404, detail=f"No events for session {session_id}")

    return info


@concilium_router.get("/result/{session_id}")
async def get_result(session_id: str) -> dict:
    """Return the full DeliberationResult-shaped payload for a past session.

    Reads ``result.json`` written by the orchestrator at deliberation exit.
    The fields match what ``POST /concilium/deliberate`` returns so the UI
    can re-populate its Result panel without special-casing.
    """
    session_dir = CONCILIUM_DIR / session_id
    if not session_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    result_path = session_dir / "result.json"
    if not result_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No persisted result for session {session_id} (likely an old session predating result.json)",
        )
    try:
        return json.loads(result_path.read_text())
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"result.json for {session_id} is corrupt: {exc}",
        )


@concilium_router.get("/logs/{session_id}")
async def get_logs(
    session_id: str,
    limit: int = Query(200, ge=1, le=2000),
    since: str | None = None,
) -> dict:
    """Get deliberation log events for a session."""
    session_dir = CONCILIUM_DIR / session_id
    if not session_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    events_path = session_dir / "events.jsonl"
    if not events_path.exists():
        return {"events": [], "count": 0}

    events = []
    with open(events_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                if since and event.get("timestamp", "") <= since:
                    continue
                events.append(event)
            except json.JSONDecodeError:
                continue

    # Newest first
    events.reverse()
    events = events[:limit]

    return {"events": events, "count": len(events)}


@concilium_router.get("/sessions")
async def list_sessions(
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """List recent deliberation sessions."""
    if not CONCILIUM_DIR.is_dir():
        return {"sessions": [], "count": 0}

    session_dirs = sorted(
        [d for d in CONCILIUM_DIR.iterdir() if d.is_dir() and not d.name.startswith("_")],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )[:limit]

    sessions = []
    for sd in session_dirs:
        info = _session_info(sd)
        if info:
            sessions.append(info)

    return {"sessions": sessions, "count": len(sessions)}


@concilium_router.get("/trace-stream")
async def trace_stream(
    session_id: str = Query("", description="Filter to a specific session"),
) -> StreamingResponse:
    """SSE endpoint for live deliberation trace events.

    Streams events from events.jsonl as they are written.
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        last_position = 0
        last_mtime = 0.0

        while True:
            try:
                if session_id:
                    targets = [CONCILIUM_DIR / session_id / "events.jsonl"]
                else:
                    # Watch all session dirs
                    if not CONCILIUM_DIR.is_dir():
                        targets = []
                    else:
                        targets = []
                        for sd in sorted(CONCILIUM_DIR.iterdir()):
                            if not sd.is_dir() or sd.name.startswith("_"):
                                continue
                            ev_path = sd / "events.jsonl"
                            if ev_path.exists():
                                targets.append(ev_path)

                for ev_path in targets:
                    if not ev_path.exists():
                        continue

                    current_mtime = ev_path.stat().st_mtime
                    if current_mtime <= last_mtime:
                        continue

                    last_mtime = current_mtime

                    with open(ev_path) as f:
                        f.seek(last_position)
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                # Validate JSON
                                json.loads(line)
                                yield f"data: {line}\n\n"
                            except json.JSONDecodeError:
                                continue
                        last_position = f.tell()

            except Exception:
                pass

            await asyncio.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
