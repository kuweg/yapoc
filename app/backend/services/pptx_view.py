"""Safe PPTX-to-PDF conversion for in-chat presentation viewing."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import threading
from pathlib import Path

from app.config import settings

_lock = threading.Lock()
_MAX_PPTX_SIZE = 50 * 1024 * 1024


def _cache_dir() -> Path:
    """Return the persistent PPTX PDF cache directory."""
    path = settings.project_root / "data" / "pptx_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def convert_pptx_to_pdf(src: Path) -> Path:
    """Convert a local PPTX to a cached PDF using LibreOffice headlessly."""
    if not src.exists() or src.suffix.lower() != ".pptx":
        raise ValueError("Not a .pptx file")
    if src.stat().st_size > _MAX_PPTX_SIZE:
        raise ValueError("PPTX too large to view")

    src = src.resolve()
    stat = src.stat()
    key_input = f"{src}|{stat.st_mtime_ns}|{stat.st_size}"
    key = hashlib.sha256(key_input.encode("utf-8")).hexdigest()[:16]
    cache_dir = _cache_dir()
    output = cache_dir / f"{src.stem}_{key}.pdf"
    if output.exists():
        return output

    with _lock:
        if output.exists():
            return output
        temp_dir = cache_dir / f".tmp_{key}"
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                [
                    "soffice", "--headless", "--convert-to", "pdf",
                    "--outdir", str(temp_dir), str(src),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            produced = temp_dir / f"{src.stem}.pdf"
            if result.returncode != 0 or not produced.exists():
                raise RuntimeError(result.stderr.strip() or "LibreOffice failed to produce a PDF")
            if output.exists():
                return output
            shutil.move(str(produced), str(output))
            return output
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


def resolve_upload_source(upload_id: str) -> Path:
    """Resolve a local-owner upload to its stored source file."""
    from app.backend.services import uploads as store

    rec = store.resolve_upload(upload_id, owner="local")
    if not rec:
        raise ValueError("Attachment not found")
    path = store.upload_path(rec)
    if not path.exists():
        raise ValueError("Attachment file missing")
    return path


def resolve_generated_source(rel_path: str) -> Path:
    """Resolve a PPTX under data/generated without allowing path traversal."""
    root = settings.project_root / "data" / "generated"
    resolved = (root / rel_path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("Path escapes data/generated")
    if resolved.suffix.lower() != ".pptx":
        raise ValueError("Not a .pptx file")
    if not resolved.exists():
        raise ValueError("File not found")
    return resolved
