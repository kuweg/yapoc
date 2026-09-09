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
import json
import time
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException
from loguru import logger
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


# ── MCP server management ──────────────────────────────────────────────────

servers_router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])

_REDACTED = "********"


def _mcp_servers_path() -> Path:
    """Path to the mcp-servers.json config file at the project root."""
    return settings.project_root / "mcp-servers.json"


def _read_mcp_servers_raw() -> dict:
    """Read the raw mcp-servers.json dict. Returns {'mcp_servers': []} if missing."""
    path = _mcp_servers_path()
    if not path.exists():
        return {"mcp_servers": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read mcp-servers.json: {}", exc)
        return {"mcp_servers": []}
    if not isinstance(data, dict):
        return {"mcp_servers": []}
    if not isinstance(data.get("mcp_servers"), list):
        data["mcp_servers"] = []
    return data


def _write_mcp_servers_raw(data: dict) -> None:
    """Write the raw mcp-servers.json dict back to disk."""
    path = _mcp_servers_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _redact_env(env: dict | None) -> dict:
    """Return env keys with all values redacted (env vars are often secrets)."""
    if not isinstance(env, dict):
        return {}
    return {str(k): _REDACTED for k in env}


@servers_router.get("/servers")
async def list_mcp_servers() -> dict:
    """List all MCP servers, merging config with live host state (secrets redacted)."""
    from app.utils.mcp.config import load_mcp_config
    from app.utils.mcp.host import mcp_host_manager

    config = load_mcp_config()
    servers: list[dict] = []
    for cfg in config.mcp_servers:
        name = cfg.name
        servers.append(
            {
                "name": name,
                "transport": cfg.transport,
                "command": cfg.command,
                "url": cfg.url,
                "enabled": cfg.enabled,
                "auth": cfg.auth,
                "tools_allowlist": cfg.tools_allowlist,
                "timeout_s": cfg.timeout_s,
                "auto_reconnect": cfg.auto_reconnect,
                "env": _redact_env(cfg.env),
                "state": mcp_host_manager.get_state(name),
                "error": mcp_host_manager.get_error(name),
                "tool_count": len(mcp_host_manager.get_server_tools(name)),
                "tools": [
                    {"name": str(getattr(t, "name", "")), "description": str(getattr(t, "description", "") or "")}
                    for t in mcp_host_manager.get_server_tools(name)
                ],
            }
        )
    return {"servers": servers}


@servers_router.post("/servers")
async def add_mcp_server(payload: dict) -> dict:
    """Add (or update) an MCP server in mcp-servers.json."""
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(status_code=422, detail="'name' is required and must be non-empty")

    transport = payload.get("transport", "stdio")
    if not isinstance(transport, str):
        transport = "stdio"

    if transport == "stdio":
        if not payload.get("command"):
            raise HTTPException(status_code=422, detail="'command' is required for stdio transport")
    elif transport in ("sse", "streamable_http", "http"):
        if not payload.get("url"):
            raise HTTPException(
                status_code=422,
                detail=f"'url' is required for '{transport}' transport",
            )

    data = _read_mcp_servers_raw()
    servers = data["mcp_servers"]

    # Build the new server entry, preserving unknown fields on existing ones.
    entry: dict = {}
    existing = next((s for s in servers if isinstance(s, dict) and s.get("name") == name), None)
    if existing is not None:
        entry = dict(existing)
    entry["name"] = name
    entry["transport"] = transport

    for field in ("command", "url", "auth", "api_key", "token"):
        if field in payload:
            entry[field] = payload[field]
    if "args" in payload:
        entry["args"] = payload["args"]
    if "env" in payload:
        entry["env"] = payload["env"]
    if "enabled" in payload:
        entry["enabled"] = payload["enabled"]
    if "timeout_s" in payload:
        entry["timeout_s"] = payload["timeout_s"]
    if "auto_reconnect" in payload:
        entry["auto_reconnect"] = payload["auto_reconnect"]

    if existing is not None:
        servers[servers.index(existing)] = entry
    else:
        servers.append(entry)

    data["mcp_servers"] = servers
    _write_mcp_servers_raw(data)
    return {"status": "ok", "name": name}


@servers_router.delete("/servers/{name}")
async def delete_mcp_server(name: str) -> dict:
    """Remove an MCP server by name from mcp-servers.json."""
    data = _read_mcp_servers_raw()
    servers = data["mcp_servers"]

    remaining = [s for s in servers if not (isinstance(s, dict) and s.get("name") == name)]
    if len(remaining) == len(servers):
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")

    data["mcp_servers"] = remaining
    _write_mcp_servers_raw(data)
    return {"status": "ok", "name": name}
