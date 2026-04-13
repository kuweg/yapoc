"""Files router — project file tree + file content reader."""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/files")

_MAX_DEPTH = 6
_MAX_FILE_SIZE = 50_000  # chars

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

    truncated = len(content) > _MAX_FILE_SIZE
    return {
        "path": path,
        "content": content[:_MAX_FILE_SIZE],
        "truncated": truncated,
        "size": len(content),
    }
