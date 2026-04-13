"""Vault router — app/projects/ folder viewer.

GET /vault/tree?depth=N  → directory tree
GET /vault/read?path=    → file content (text / image / pdf)
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/vault")

_VAULT_ROOT: Path = settings.project_root / "app" / "projects"
_MAX_TEXT = 500_000  # 500 KB
_MAX_DEPTH = 8

_SKIP_DIRS = {
    "__pycache__", ".git", ".venv", "node_modules",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".ruff_cache",
}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tiff"}
_BINARY_EXTS = {
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".bin",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".db", ".sqlite",
}
_LANG_MAP: dict[str, str] = {
    ".py": "python",  ".pyi": "python",
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript",
    ".json": "json",  ".jsonc": "json",
    ".yaml": "yaml",  ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown", ".mdx": "markdown",
    ".css": "css",    ".scss": "scss",
    ".html": "html",  ".htm": "html",
    ".xml": "xml",    ".svg": "xml",
    ".sh": "bash",    ".bash": "bash", ".zsh": "bash",
    ".sql": "sql",
    ".rs": "rust",
    ".go": "go",
    ".rb": "ruby",
    ".php": "php",
    ".java": "java",
    ".c": "c",    ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".txt": "plaintext",
    ".env": "bash",
    ".dockerfile": "dockerfile",
}
_MIME_MAP: dict[str, str] = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".ico": "image/x-icon",
    ".bmp": "image/bmp", ".tiff": "image/tiff",
}


class FileNode(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    children: Optional[list["FileNode"]] = None


FileNode.model_rebuild()


def _sandbox(path: str) -> Path:
    root = _VAULT_ROOT.resolve()
    resolved = (root / path).resolve() if path else root
    if not str(resolved).startswith(str(root)):
        raise ValueError("Path escapes vault root")
    return resolved


def _build_tree(abs_path: Path, root: Path, depth: int, max_depth: int) -> list[FileNode]:
    nodes: list[FileNode] = []
    try:
        entries = sorted(abs_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        return nodes
    for entry in entries:
        if entry.name.startswith(".") and entry.name != ".env":
            continue
        if entry.name in _SKIP_DIRS:
            continue
        rel = str(entry.relative_to(root))
        if entry.is_dir():
            children = _build_tree(entry, root, depth + 1, max_depth) if depth < max_depth else None
            nodes.append(FileNode(name=entry.name, path=rel, is_dir=True, children=children))
        else:
            try:
                sz = entry.stat().st_size
            except OSError:
                sz = None
            nodes.append(FileNode(name=entry.name, path=rel, is_dir=False, size=sz))
    return nodes


@router.get("/tree", response_model=list[FileNode])
async def vault_tree(depth: int = Query(default=5, ge=1, le=_MAX_DEPTH)):
    _VAULT_ROOT.mkdir(parents=True, exist_ok=True)
    root = _VAULT_ROOT.resolve()
    return _build_tree(root, root, 1, depth)


@router.get("/read")
async def vault_read(path: str = Query(...)):
    try:
        abs_path = _sandbox(path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not abs_path.exists():
        raise HTTPException(404, f"Not found: {path}")
    if abs_path.is_dir():
        raise HTTPException(400, f"Is a directory: {path}")

    ext = abs_path.suffix.lower()
    name_lower = abs_path.name.lower()

    # Images → base64
    if ext in _IMAGE_EXTS:
        try:
            data = base64.b64encode(abs_path.read_bytes()).decode()
        except OSError as e:
            raise HTTPException(500, str(e))
        return {
            "path": path, "type": "image",
            "mime": _MIME_MAP.get(ext, "image/octet-stream"),
            "data": data, "size": abs_path.stat().st_size,
        }

    # SVG → read as text, render as image via data-uri on the client
    if ext == ".svg":
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise HTTPException(500, str(e))
        return {
            "path": path, "type": "svg",
            "content": content, "size": len(content),
        }

    # PDF → base64
    if ext == ".pdf":
        try:
            data = base64.b64encode(abs_path.read_bytes()).decode()
        except OSError as e:
            raise HTTPException(500, str(e))
        return {"path": path, "type": "pdf", "data": data, "size": abs_path.stat().st_size}

    # Unsupported binary
    if ext in _BINARY_EXTS:
        raise HTTPException(422, f"Binary not supported: {name_lower}")

    # Text
    try:
        content = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise HTTPException(500, str(e))

    lang = _LANG_MAP.get(ext, "plaintext")
    if not ext:
        if name_lower == "dockerfile":
            lang = "dockerfile"
        elif name_lower == "makefile":
            lang = "makefile"

    truncated = len(content) > _MAX_TEXT
    return {
        "path": path, "type": "text",
        "content": content[:_MAX_TEXT],
        "truncated": truncated,
        "size": len(content),
        "lang": lang,
    }
