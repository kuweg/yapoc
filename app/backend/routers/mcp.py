"""MCP run endpoint — let external MCP clients (e.g. Claude Code) hire YAPOC.

This is the single synchronous entrypoint the stdio MCP server
(``app/mcp_server/``) calls over HTTP. It does NOT re-implement master or the
dispatcher: it just submits a task to the existing task_queue and blocks
(polls ``get_queued_task``) until that task reaches a terminal state.

Auth mirrors ``app/backend/routers/webhook.py`` (Bearer header) but gates on
``settings.mcp_server_enabled`` — when that is falsy the endpoint refuses to
serve at all. An empty ``settings.mcp_api_key`` means local dev mode (no auth).
"""

from __future__ import annotations

import asyncio
import time
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.utils.db import create_queued_task, get_queued_task

router = APIRouter(prefix="/mcp", tags=["mcp"])

_POLL_INTERVAL_S = 0.5
_TERMINAL_STATUSES = {"done", "error", "timeout", "cancelled"}


class McpRunRequest(BaseModel):
    task: str
    agent: str | None = None
    timeout_s: int = 600


def _authorized(authorization: str | None) -> None:
    """Enforce Bearer auth per settings.mcp_api_key. Raises 401 on mismatch."""
    secret = settings.mcp_api_key
    if not secret:
        return  # local dev mode — no auth required
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization[7:]  # Strip "Bearer "
    if token != secret:
        raise HTTPException(status_code=401, detail="Invalid MCP token")


@router.post("/run")
async def mcp_run(
    request: McpRunRequest,
    authorization: str | None = Header(None),
) -> dict:
    """Submit a task to the queue and block until it completes (or times out)."""
    if not settings.mcp_server_enabled:
        raise HTTPException(status_code=403, detail="MCP endpoint disabled (set mcp_server_enabled=true)")

    _authorized(authorization)

    # Optional delegation wrapper so master performs the spawn for us — the
    # MCP process never talks to non-master agents directly.
    final_prompt = request.task
    if request.agent and request.agent.lower() != "master":
        final_prompt = (
            f"Delegate this task to the '{request.agent}' agent. "
            f"Spawn it, wait for its result, and return that result verbatim.\n\n{request.task}"
        )

    task_id = str(uuid4())
    create_queued_task(id=task_id, prompt=final_prompt, source="mcp", session_id=None, metadata=None)

    total = max(int(request.timeout_s or 600), 0)
    deadline = time.monotonic() + total

    while True:
        row = get_queued_task(task_id)
        status = (row or {}).get("status")
        if status in _TERMINAL_STATUSES:
            if row and status == "done" and not row.get("result"):
                # Still a done row — return whatever the queue holds.
                pass
            break

        if total and time.monotonic() >= deadline:
            return {
                "task_id": task_id,
                "status": "timeout",
                "result": None,
            }

        await asyncio.sleep(_POLL_INTERVAL_S)

    row = get_queued_task(task_id) or {}
    return {
        "task_id": task_id,
        "status": row.get("status"),
        "result": row.get("result"),
        "error": row.get("error"),
    }
