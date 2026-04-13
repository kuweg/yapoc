import time
from datetime import datetime, timezone

from fastapi import APIRouter

from app.config import settings

router = APIRouter()

_start_time = time.time()


@router.get("/health")
async def health():
    return {"status": "ok", "uptime": round(time.time() - _start_time, 2)}


@router.get("/ping")
async def ping():
    return {"pong": True, "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/health/summary")
async def health_summary():
    """Return the Doctor agent's latest HEALTH_SUMMARY.MD content."""
    summary_path = settings.agents_dir / "doctor" / "HEALTH_SUMMARY.MD"
    if not summary_path.exists():
        return {"status": "ok", "content": ""}
    content = summary_path.read_text(encoding="utf-8", errors="replace")
    return {"status": "ok", "content": content}
