"""A small async HTTP client for the YAPOC backend.

The MCP server uses this to talk to the already-running FastAPI backend over
HTTP rather than re-implementing master/dispatch logic in-process.

Config is read from the environment at call time:
- YAPOC_DASHBOARD_URL (default http://localhost:8000)
- MCP_API_KEY (optional) — when set, sent as ``Authorization: Bearer <key>``
- YAPOC_TASK_TIMEOUT (optional int, default 900) — cap on blocking run/hold polls
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

_DEFAULT_BASE = "http://localhost:8000"
_DEFAULT_TIMEOUT = 900
_POLL_INTERVAL_S = 3.0
_TERMINAL_STATES = {"approved", "rejected", "escalated", "error"}


def _base_url() -> str:
    return os.environ.get("YAPOC_DASHBOARD_URL", _DEFAULT_BASE).rstrip("/")


def _auth_headers() -> dict[str, str]:
    key = os.environ.get("MCP_API_KEY", "")
    return {"Authorization": f"Bearer {key}"} if key else {}


def _default_timeout() -> int:
    try:
        return max(int(os.environ.get("YAPOC_TASK_TIMEOUT", _DEFAULT_TIMEOUT)), 0)
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT


def _raise_for_status(resp: httpx.Response, detail: str) -> None:
    if resp.status_code >= 200 and resp.status_code < 300:
        return
    body = resp.text[:2000]
    raise RuntimeError(
        f"{detail} failed: HTTP {resp.status_code} — {body or '(empty body)'}"
    )


async def run_task(
    task: str,
    agent: str | None = None,
    timeout_s: int | None = None,
) -> dict[str, Any]:
    """Submit a task via POST {base}/mcp/run and return the JSON response."""
    cap = timeout_s if timeout_s and timeout_s > 0 else _default_timeout()
    payload: dict[str, Any] = {"task": task, "timeout_s": cap}
    if agent:
        payload["agent"] = agent
    async with httpx.AsyncClient(timeout=cap + 30) as client:
        resp = await client.post(
            f"{_base_url()}/mcp/run", json=payload, headers=_auth_headers()
        )
        _raise_for_status(resp, "run_task")
        return resp.json()


async def search_memory(
    query: str,
    agent: str = "",
    top_k: int = 8,
) -> dict[str, Any]:
    """Search backend memory via GET {base}/memory/search."""
    params: dict[str, Any] = {"q": query, "top_k": top_k}
    if agent:
        params["agent"] = agent
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{_base_url()}/memory/search", params=params, headers=_auth_headers()
        )
        _raise_for_status(resp, "memory search")
        return resp.json()


async def deliberate(
    proposal: str,
    max_rounds: int = 3,
    timeout_s: int | None = None,
) -> dict[str, Any]:
    """Kick off a Concilium deliberation, then poll until it is terminal.

    POST {base}/concilium/deliberate returns 202 with ``{"session_id", ...}``
    and the deliberation runs in the background. We poll
    GET {base}/concilium/status/{session_id} every few seconds until its
    ``state`` (or ``status``) field lands in a terminal set, then fetch the
    persisted result via GET {base}/concilium/result/{session_id}.
    """
    cap = timeout_s if timeout_s and timeout_s > 0 else _default_timeout()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{_base_url()}/concilium/deliberate",
            json={"plan_text": proposal, "max_rounds": max_rounds},
            headers=_auth_headers(),
        )
        _raise_for_status(resp, "deliberate start")
        data: dict[str, Any] = resp.json()

    session_id = data.get("session_id")
    if not session_id:
        return data

    deadline = asyncio.get_event_loop().time() + cap
    while True:
        if asyncio.get_event_loop().time() >= deadline:
            return {
                "session_id": session_id,
                "status": "still_running",
                "note": f"deliberation still in progress after {cap}s; "
                        f"poll /concilium/result/{session_id}",
            }
        async with httpx.AsyncClient(timeout=30) as client:
            sresp = await client.get(
                f"{_base_url()}/concilium/status/{session_id}",
                headers=_auth_headers(),
            )
        _raise_for_status(sresp, "deliberation status")
        status_data: dict[str, Any] = sresp.json()
        state = status_data.get("state") or status_data.get("status")
        if state in _TERMINAL_STATES:
            break
        await asyncio.sleep(_POLL_INTERVAL_S)

    async with httpx.AsyncClient(timeout=30) as client:
        rresp = await client.get(
            f"{_base_url()}/concilium/result/{session_id}",
            headers=_auth_headers(),
        )
    _raise_for_status(rresp, "deliberation result")
    return rresp.json()
