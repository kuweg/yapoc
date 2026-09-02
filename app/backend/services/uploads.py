"""Upload store — disk persistence, dedup, indexing and resolution for chat
attachments (Phase 1 of the attachment system).

Layout under ``settings.upload_dir`` (``data/uploads/``):
  {YYYY}/{MM}/{DD}/{uuid.hex}.{safe_ext}   the stored bytes
  uploads.json                              id -> metadata index (atomic write)
  .thumbs/{id}.jpg                          cached 320x320 JPEG thumbnails
  .vision/{id}.txt                          cached VL OCR/caption text (Phase 3)

Every record is owner-scoped; ``resolve_upload`` drops anything the caller does
not own so attachments can't leak across users.
"""
from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import settings

# libmagic is optional — fall back to extension-based detection if unavailable.
try:
    import magic as _libmagic  # python-magic
    _HAVE_MAGIC = True
except Exception:  # pragma: no cover - environment dependent
    _HAVE_MAGIC = False

try:
    from PIL import Image, ImageOps
    _HAVE_PIL = True
except Exception:  # pragma: no cover
    _HAVE_PIL = False

MAX_SIZE = 10 * 1024 * 1024  # 10 MB
THUMB_SIZE = (320, 320)

# Reject obviously dangerous executables/scripts (defence in depth — these are
# never something a chat attachment legitimately needs).
_DANGEROUS_EXT = {
    ".exe", ".dll", ".bat", ".cmd", ".com", ".scr", ".msi", ".vbs", ".vbe",
    ".js", ".jse", ".ps1", ".psm1", ".jsp", ".asp", ".aspx", ".jar", ".sh",
    ".bash", ".csh", ".pif", ".cpl", ".hta", ".wsf",
}
_DANGEROUS_MIME = {
    "application/x-msdownload", "application/x-dosexec", "application/x-executable",
    "application/x-sh", "application/x-shellscript", "application/javascript",
    "text/javascript", "application/x-msdos-program", "application/vnd.microsoft.portable-executable",
}

_lock = threading.Lock()


# ── paths ────────────────────────────────────────────────────────────────────
def _root() -> Path:
    return settings.upload_dir


def _index_path() -> Path:
    return _root() / "uploads.json"


def _safe_ext(filename: str, mime: str) -> str:
    ext = Path(filename or "").suffix.lower()
    ext = re.sub(r"[^a-z0-9.]", "", ext)[:10]
    if not ext:
        guessed = mimetypes.guess_extension(mime or "") or ""
        ext = re.sub(r"[^a-z0-9.]", "", guessed.lower())[:10]
    return ext or ".bin"


# ── mime / validation ────────────────────────────────────────────────────────
def detect_mime(content: bytes, filename: str) -> str:
    if _HAVE_MAGIC:
        try:
            m = _libmagic.from_buffer(content[:8192], mime=True)
            if m and m != "application/octet-stream":
                return m
        except Exception:
            pass
    guessed, _ = mimetypes.guess_type(filename or "")
    return guessed or "application/octet-stream"


def is_dangerous(mime: str, filename: str) -> bool:
    ext = Path(filename or "").suffix.lower()
    return ext in _DANGEROUS_EXT or (mime or "").lower() in _DANGEROUS_MIME


def image_dimensions(content: bytes, mime: str) -> tuple[Optional[int], Optional[int]]:
    if not (mime or "").startswith("image/") or not _HAVE_PIL:
        return None, None
    try:
        im = Image.open(io.BytesIO(content))
        im = ImageOps.exif_transpose(im)  # honour EXIF orientation
        return int(im.width), int(im.height)
    except Exception:
        return None, None


# ── index (atomic) ───────────────────────────────────────────────────────────
def _load_index() -> dict[str, dict[str, Any]]:
    p = _index_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        bak = p.with_suffix(".json.bak")
        if bak.exists():
            try:
                return json.loads(bak.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}


def _save_index(index: dict[str, dict[str, Any]]) -> None:
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    p = _index_path()
    if p.exists():
        try:
            p.replace(p.with_suffix(".json.bak"))
        except OSError:
            pass
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, indent=2), encoding="utf-8")
    os.replace(tmp, p)


# ── public meta projection (what the API returns) ────────────────────────────
def public_meta(rec: dict[str, Any]) -> dict[str, Any]:
    out = {
        "id": rec["id"],
        "name": rec.get("name") or rec.get("original_name"),
        "mime": rec.get("mime"),
        "size": rec.get("size"),
        "hash": rec.get("hash"),
        "is_duplicate": rec.get("is_duplicate", False),
    }
    if rec.get("width") is not None:
        out["width"] = rec["width"]
    if rec.get("height") is not None:
        out["height"] = rec["height"]
    return out


# ── store / resolve ──────────────────────────────────────────────────────────
def store_upload(filename: str, content: bytes, owner: str, client_ip: str = "") -> dict[str, Any]:
    """Validate + persist one file, dedup per owner, index it. Returns the record
    (with ``is_duplicate`` reflecting whether the owner already had these bytes).

    Raises ValueError on validation failure (caller maps to HTTP 4xx).
    """
    if len(content) > MAX_SIZE:
        raise ValueError(f"File too large (max {MAX_SIZE // (1024 * 1024)}MB)")
    if len(content) == 0:
        raise ValueError("Empty file")

    mime = detect_mime(content, filename)
    if is_dangerous(mime, filename):
        raise ValueError(f"Disallowed file type: {filename} ({mime})")

    digest = hashlib.sha256(content).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    width, height = image_dimensions(content, mime)

    with _lock:
        index = _load_index()
        # Dedup: same owner + same bytes → return the existing record.
        for rec in index.values():
            if rec.get("owner") == owner and rec.get("hash") == digest:
                rec = dict(rec)
                rec["is_duplicate"] = True
                rec["last_accessed"] = now
                index[rec["id"]] = {**index[rec["id"]], "last_accessed": now}
                _save_index(index)
                return rec

        file_id = uuid.uuid4().hex
        ext = _safe_ext(filename, mime)
        dt = datetime.now(timezone.utc)
        rel_dir = Path(f"{dt:%Y}") / f"{dt:%m}" / f"{dt:%d}"
        abs_dir = _root() / rel_dir
        abs_dir.mkdir(parents=True, exist_ok=True)
        stored = abs_dir / f"{file_id}{ext}"
        stored.write_bytes(content)

        rec = {
            "id": file_id,
            "name": Path(filename or "file").name or "file",
            "original_name": filename,
            "mime": mime,
            "size": len(content),
            "hash": digest,
            "width": width,
            "height": height,
            "path": str(stored.relative_to(_root())),
            "owner": owner,
            "client_ip": client_ip,
            "uploaded_at": now,
            "last_accessed": now,
            "is_duplicate": False,
        }
        index[file_id] = rec
        _save_index(index)
        return rec


def resolve_upload(file_id: str, owner: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Look up a record by id, owner-scoped. Returns None if missing or not owned
    (admin/None owner bypasses the scope check)."""
    with _lock:
        index = _load_index()
        rec = index.get(file_id)
        if not rec:
            return None
        if owner is not None and rec.get("owner") not in (owner, None, ""):
            return None
        return dict(rec)


def upload_path(rec: dict[str, Any]) -> Path:
    return _root() / rec["path"]


# ── thumbnails ───────────────────────────────────────────────────────────────
def get_thumbnail(rec: dict[str, Any]) -> Optional[Path]:
    """Return a cached 320x320 JPEG thumbnail for an image record, generating it
    on first request. None for non-images or when Pillow is unavailable."""
    if not (rec.get("mime") or "").startswith("image/") or not _HAVE_PIL:
        return None
    thumbs = _root() / ".thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    out = thumbs / f"{rec['id']}.jpg"
    if out.exists():
        return out
    src = upload_path(rec)
    if not src.exists():
        return None
    try:
        im = Image.open(src)
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail(THUMB_SIZE)
        im.save(out, "JPEG", quality=82)
        return out
    except Exception:
        return None


def touch_accessed(file_id: str) -> None:
    with _lock:
        index = _load_index()
        rec = index.get(file_id)
        if rec:
            rec["last_accessed"] = datetime.now(timezone.utc).isoformat()
            _save_index(index)


# ── message injection (Phase 1 — image_read marker path + inline text) ───────
TEXT_BUDGET = 24_000  # total inlined chars across all attachments in one message
_TEXT_MIMES = ("text/", "application/json", "application/xml", "application/x-yaml")


def project_rel_path(rec: dict[str, Any]) -> str:
    """Path of the stored file relative to project_root, so the agent's
    ``image_read`` / ``file_read`` tools (which sandbox to project_root) can load
    it directly."""
    return f"data/uploads/{rec['path']}"


def _extract_text(rec: dict[str, Any]) -> Optional[str]:
    """Best-effort text extraction for Phase 1 (text/code/markdown/docx). Returns
    None for formats handled by later phases (pdf/office-non-docx/audio)."""
    mime = (rec.get("mime") or "").lower()
    name = (rec.get("name") or "").lower()
    path = upload_path(rec)
    if not path.exists():
        return None
    is_text = mime.startswith(_TEXT_MIMES) or name.endswith(
        (".txt", ".md", ".markdown", ".json", ".yaml", ".yml", ".csv", ".log",
         ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".sh", ".toml", ".ini")
    )
    if is_text:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    if name.endswith(".docx"):
        try:
            import io as _io
            import docx  # python-docx
            doc = docx.Document(_io.BytesIO(path.read_bytes()))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception:
            return None
    return None


def build_attachment_injection(ids: list[str], owner: str) -> tuple[str, list[dict[str, Any]]]:
    """Resolve attachment IDs (owner-scoped) and build the text to append to the
    user message: an ``image_read`` marker per image, inline text for
    text/docx, and a note for formats not yet extracted. Returns
    ``(suffix, meta_list)`` where meta_list is the public metadata for the SSE
    ``attachments`` event + bubble rendering.
    """
    parts: list[str] = []
    meta: list[dict[str, Any]] = []
    budget = TEXT_BUDGET
    for fid in ids or []:
        rec = resolve_upload(fid, owner=owner)
        if not rec:
            continue
        meta.append(public_meta(rec))
        mime = (rec.get("mime") or "")
        name = rec.get("name") or "file"
        rel = project_rel_path(rec)
        if mime.startswith("image/"):
            # Master loads it via image_read; normalize.py formats per-adapter.
            parts.append(f"[📎 photo attached: {rel}]")
            continue
        text = _extract_text(rec)
        if text is not None:
            if budget <= 0:
                parts.append(f"\n\n[Attachment omitted (budget exceeded): {name}]")
                continue
            snippet = text[:budget]
            budget -= len(snippet)
            trunc = "\n[… truncated]" if len(text) > len(snippet) else ""
            ext = name.rsplit(".", 1)[-1] if "." in name else ""
            fence = f"```{ext}\n" if ext and ext not in ("txt", "md", "markdown") else ""
            close = "```" if fence else ""
            parts.append(f"\n\n--- Attachment: {name} ---\n{fence}{snippet}{trunc}\n{close}\n--- end {name} ---")
        else:
            parts.append(f"\n\n[Attachment: {name} ({mime}) — content extraction not available yet]")
    return ("\n".join(parts) if parts else ""), meta
