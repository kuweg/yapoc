"""Upload router — multi-file attachment upload + owner-scoped serving.

Mounted under the app's ``/api`` proxy convention, so these are reached as
``/api/upload`` and ``/api/upload/{id}`` from the frontend.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from app.backend.services import uploads as store

router = APIRouter(prefix="/upload")

# Single-user local app: one logical owner. Pluggable later (auth/session).
def _owner(_request: Request) -> str:
    return "local"


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


# ── per-IP rate limiting ─────────────────────────────────────────────────────
_RATE_MAX_PER_MIN = 60
_RATE_MAX_CONCURRENT = 3
_rl_lock = threading.Lock()
_rl_times: dict[str, deque[float]] = defaultdict(deque)
_rl_active: dict[str, int] = defaultdict(int)


class _RateGate:
    def __init__(self, ip: str) -> None:
        self.ip = ip

    def __enter__(self) -> "_RateGate":
        now = time.monotonic()
        with _rl_lock:
            q = _rl_times[self.ip]
            while q and now - q[0] > 60.0:
                q.popleft()
            if len(q) >= _RATE_MAX_PER_MIN:
                raise HTTPException(status_code=429, detail="Upload rate limit exceeded (60/min)")
            if _rl_active[self.ip] >= _RATE_MAX_CONCURRENT:
                raise HTTPException(status_code=429, detail="Too many concurrent uploads (max 3)")
            q.append(now)
            _rl_active[self.ip] += 1
        return self

    def __exit__(self, *exc: object) -> None:
        with _rl_lock:
            _rl_active[self.ip] = max(0, _rl_active[self.ip] - 1)


@router.post("")
async def upload(request: Request, files: list[UploadFile] = File(...)):
    """Accept one or more files, store + index them, return their metadata.

    Returns ``{"files": [public_meta, ...], "errors": [{"name", "error"}, ...]}``.
    Responds 400 only when nothing succeeded.
    """
    owner = _owner(request)
    ip = _client_ip(request)
    results: list[dict] = []
    errors: list[dict] = []
    with _RateGate(ip):
        for f in files:
            try:
                content = await f.read()
                rec = store.store_upload(f.filename or "paste.png", content, owner=owner, client_ip=ip)
                results.append(store.public_meta(rec))
            except ValueError as exc:
                errors.append({"name": f.filename, "error": str(exc)})
            except Exception as exc:  # pragma: no cover
                errors.append({"name": f.filename, "error": f"upload failed: {exc}"})
    if not results and errors:
        raise HTTPException(status_code=400, detail=errors[0]["error"])
    return {"files": results, "errors": errors}


@router.get("/{file_id}")
async def serve(request: Request, file_id: str, thumb: int = Query(default=0)):
    """Serve an uploaded file (owner-scoped). ``?thumb=1`` returns a cached
    320x320 JPEG thumbnail for images. 404 for missing or not-owned files."""
    rec = store.resolve_upload(file_id, owner=_owner(request))
    if not rec:
        raise HTTPException(status_code=404, detail="Attachment not found")
    store.touch_accessed(file_id)

    if thumb:
        tpath = store.get_thumbnail(rec)
        if tpath and tpath.exists():
            return FileResponse(str(tpath), media_type="image/jpeg")
        # Non-image or thumbnail unavailable → fall through to the original.

    path = store.upload_path(rec)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Attachment file missing")
    return FileResponse(str(path), media_type=rec.get("mime") or "application/octet-stream", filename=rec.get("name"))


@router.get("/{file_id}/vision")
async def get_vision(request: Request, file_id: str):
    """Read the cached VL OCR/caption for an image (Phase 3 writes these). Empty
    string when none exists yet."""
    rec = store.resolve_upload(file_id, owner=_owner(request))
    if not rec:
        raise HTTPException(status_code=404, detail="Attachment not found")
    vpath = store._root() / ".vision" / f"{file_id}.txt"
    text = ""
    if vpath.exists():
        try:
            text = vpath.read_text(encoding="utf-8")
        except OSError:
            text = ""
    return {"id": file_id, "text": text}
