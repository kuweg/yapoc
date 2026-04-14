"""Webhook entry point — accept tasks from external sources.

Provides a simple REST API for submitting tasks from anywhere:
CI/CD pipelines, Telegram bots, IFTTT, cURL scripts, etc.

Auth: Bearer token (settings.webhook_secret). No token = endpoint disabled.
"""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from app.config import settings
from app.utils.db import create_queued_task

router = APIRouter(prefix="/webhook", tags=["webhook"])


class WebhookTaskRequest(BaseModel):
    prompt: str
    callback_url: str | None = None


@router.post("/task")
async def webhook_submit_task(
    request: WebhookTaskRequest,
    authorization: str | None = Header(None),
):
    """Submit a task via webhook. Requires Bearer token auth."""
    # Check auth
    secret = settings.webhook_secret
    if not secret:
        raise HTTPException(status_code=403, detail="Webhook endpoint disabled (no webhook_secret configured)")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = authorization[7:]  # Strip "Bearer "
    if token != secret:
        raise HTTPException(status_code=401, detail="Invalid webhook token")

    # Create task
    task_id = str(uuid4())
    metadata = None
    if request.callback_url:
        metadata = json.dumps({"callback_url": request.callback_url})

    task = create_queued_task(
        id=task_id,
        prompt=request.prompt,
        source="webhook",
        metadata=metadata,
    )

    # Push WebSocket event
    try:
        from app.backend.websocket import ws_manager
        await ws_manager.push_event("task_created", {"task": task})
    except Exception:
        pass

    return {"task_id": task_id, "status": "pending"}
