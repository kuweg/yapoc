"""Admin endpoints — privileged backend operations.

Auth: Bearer token (settings.webhook_secret). No token configured = endpoints
disabled. Reuses the same secret as /webhook for now; split into a dedicated
admin secret if these surfaces start diverging.

Routes here intentionally bypass the agent system and reach directly into
process state. Treat anything you add here as production-impact.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_bearer(authorization: str | None) -> None:
    """Match the /webhook auth pattern: 403 if no secret configured,
    401 if missing/invalid token."""
    secret = settings.webhook_secret
    if not secret:
        raise HTTPException(
            status_code=403,
            detail="Admin endpoints disabled (no webhook_secret configured)",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )
    token = authorization[7:]
    if token != secret:
        raise HTTPException(status_code=401, detail="Invalid admin token")


@router.post("/plugins/reload")
async def reload_plugins(authorization: str | None = Header(None)) -> dict:
    """Re-scan plugins/ and register any BaseTool subclasses found.

    Idempotent. Plugin files edited between calls are picked up because
    the loader drops cached modules from sys.modules before re-import.
    Core tools cannot be shadowed.
    """
    _require_bearer(authorization)

    from app.utils.tools import TOOL_REGISTRY
    from app.utils.tools.plugin_loader import load_plugins, loaded_plugin_names

    before = set(TOOL_REGISTRY.keys())
    count = load_plugins()
    after = set(TOOL_REGISTRY.keys())
    plugin_names = sorted(loaded_plugin_names())
    return {
        "status": "ok",
        "plugins_loaded": count,
        "plugin_tool_names": plugin_names,
        "added": sorted(after - before),
        "removed": sorted(before - after),
        "total_tools": len(TOOL_REGISTRY),
    }
