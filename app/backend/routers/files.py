"""Files router — project file tree + file content reader + image upload."""

import uuid
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/files")

_MAX_DEPTH = 6

# Directories to skip in the tree
_SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "node_modules", ".mypy_cache",
    ".pytest_cache", "dist", ".next", ".nuxt", "build", "coverage",
    ".ruff_cache", ".DS_Store",
}

# Binary/large file extensions to skip reading
_BINARY_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".bin",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".bz2", ".7z",
    ".pdf", ".db", ".sqlite",
}


class FileNode(BaseModel):
    name: str
    path: str  # relative to project_root
    is_dir: bool
    children: Optional[list["FileNode"]] = None


FileNode.model_rebuild()


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    allowed_ext = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 5MB)")
    dest_dir = settings.project_root / "data" / "telegram_media"
    dest_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid.uuid4()}_{file.filename}"
    dest = dest_dir / fname
    dest.write_bytes(contents)
    return {"path": f"data/telegram_media/{fname}"}


@router.get("/image")
async def serve_image(path: str = Query(..., description="Path relative to project root")):
    try:
        abs_path = _sandbox(path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    image_extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    if abs_path.suffix.lower() not in image_extensions:
        raise HTTPException(status_code=422, detail="Not an image file")
    return FileResponse(str(abs_path))


def _sandbox(path: str) -> Path:
    """Resolve path relative to project_root and ensure it stays within."""
    root = settings.project_root.resolve()
    resolved = (root / path).resolve()
    if not str(resolved).startswith(str(root)):
        raise ValueError(f"Path '{path}' escapes project root")
    return resolved


def _build_tree(abs_path: Path, rel_base: Path, depth: int, max_depth: int) -> list[FileNode]:
    nodes: list[FileNode] = []
    try:
        entries = sorted(abs_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        return nodes

    for entry in entries:
        if entry.name.startswith(".") and entry.name not in (".env",):
            continue
        if entry.name in _SKIP_DIRS:
            continue
        rel = entry.relative_to(rel_base)
        if entry.is_dir():
            children = None
            if depth < max_depth:
                children = _build_tree(entry, rel_base, depth + 1, max_depth)
            nodes.append(FileNode(name=entry.name, path=str(rel), is_dir=True, children=children))
        else:
            nodes.append(FileNode(name=entry.name, path=str(rel), is_dir=False))
    return nodes


@router.get("/tree", response_model=list[FileNode])
async def get_file_tree(depth: int = Query(default=3, ge=1, le=_MAX_DEPTH)):
    root = settings.project_root.resolve()
    return _build_tree(root, root, 1, depth)


@router.get("/read")
async def read_file(path: str = Query(..., description="Path relative to project root")):
    try:
        abs_path = _sandbox(path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not abs_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    if abs_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is a directory: {path}")

    if abs_path.suffix.lower() in _BINARY_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"Binary file not readable: {path}")

    try:
        content = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "path": path,
        "content": content,
        "size": len(content),
    }
