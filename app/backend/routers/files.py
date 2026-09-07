"""Files router — project file tree + file content reader + image upload."""

import uuid
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import io
import docx

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

# Textual file extensions that can be previewed inline in the chat sidebar.
_TEXT_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".text", ".rst",
    ".json", ".jsonl", ".csv", ".tsv", ".yaml", ".yml", ".xml", ".toml", ".ini", ".cfg", ".conf",
    ".html", ".htm", ".css", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
    ".py", ".pyw", ".sh", ".bash", ".zsh", ".rb", ".go", ".rs", ".java", ".c", ".h", ".cpp", ".hpp",
    ".sql", ".log", ".gitignore", ".dockerfile",
}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
_PREVIEW_MAX_CHARS = 200_000


class FileNode(BaseModel):
    name: str
    path: str  # relative to project_root
    is_dir: bool
    children: Optional[list["FileNode"]] = None


FileNode.model_rebuild()


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    allowed_ext = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".txt", ".md", ".docx"}
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 5MB)")

    # For text files, extract content inline
    text_content = None
    if suffix in {".txt", ".md"}:
        try:
            text_content = contents.decode("utf-8")
        except UnicodeDecodeError:
            text_content = contents.decode("utf-8", errors="replace")
        # Cap at 50KB to prevent context overflow
        if len(text_content) > 50 * 1024:
            text_content = text_content[:50 * 1024] + f"\n\n[... truncated: {len(text_content) - 50 * 1024} more bytes]"
    elif suffix == ".docx":
        try:
            doc = docx.Document(io.BytesIO(contents))
            paragraphs = [p.text for p in doc.paragraphs]
            text_content = "\n".join(paragraphs)
            if len(text_content) > 50 * 1024:
                text_content = text_content[:50 * 1024] + f"\n\n[... truncated: {len(text_content) - 50 * 1024} more bytes]"
        except Exception as e:
            text_content = f"[Error extracting .docx content: {e}]"

    dest_dir = settings.project_root / "data" / "telegram_media"
    dest_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid.uuid4()}_{Path(file.filename or 'upload').name}"
    dest = dest_dir / fname
    dest.write_bytes(contents)
    result = {"path": f"data/telegram_media/{fname}", "type": "text" if text_content else "image"}
    if text_content:
        result["content"] = text_content
    return result


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
    if not resolved.is_relative_to(root):
        raise ValueError(f"Path '{path}' escapes project root")
    if any(part.startswith(".env") and part != ".env.example" for part in resolved.relative_to(root).parts) or resolved.suffix.lower() in {".pem", ".key"} or ".git" in resolved.relative_to(root).parts:
        raise ValueError("Sensitive files are not available through the file browser")
    return resolved


def _classify(abs_path: Path) -> str:
    """Classify a file for the chat sidebar: text|image|pdf|pptx|binary."""
    suffix = abs_path.suffix.lower()
    if suffix in _TEXT_EXTENSIONS:
        return "text"
    if suffix in _IMAGE_EXTENSIONS:
        return "image"
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".pptx":
        return "pptx"
    return "binary"


def _media_type(abs_path: Path) -> str:
    """Best-effort MIME type for serving a file; octet-stream fallback."""
    import mimetypes
    return mimetypes.guess_type(str(abs_path))[0] or "application/octet-stream"


def _build_tree(abs_path: Path, rel_base: Path, depth: int, max_depth: int) -> list[FileNode]:
    nodes: list[FileNode] = []
    try:
        entries = sorted(abs_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        return nodes

    for entry in entries:
        if entry.name.startswith("."):
            continue
        if entry.name in _SKIP_DIRS:
            continue
        try:
            _sandbox(str(entry.relative_to(rel_base)))
        except ValueError:
            continue
        if entry.is_symlink():
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


@router.get("/download")
async def download_file(
    path: str = Query(..., description="Path relative to project root"),
    inline: int = Query(default=0, description="Serve inline (browser preview) instead of attachment download"),
):
    """Serve a sandboxed project file. Default is an attachment download; pass
    inline=1 to stream it inline (used for PDF/image preview in an iframe)."""
    try:
        abs_path = _sandbox(path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    if abs_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is a directory: {path}")
    return FileResponse(
        str(abs_path),
        media_type=_media_type(abs_path),
        filename=None if inline else abs_path.name,
    )


@router.get("/preview")
async def preview_file(path: str = Query(..., description="Path relative to project root")):
    """Return metadata + (for text files) content for the chat file-viewer sidebar."""
    try:
        abs_path = _sandbox(path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    if abs_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is a directory: {path}")

    kind = _classify(abs_path)
    size = abs_path.stat().st_size
    result = {
        "path": path,
        "name": abs_path.name,
        "size": size,
        "ext": abs_path.suffix.lower(),
        "kind": kind,
    }
    if kind == "text":
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise HTTPException(status_code=500, detail=str(e))
        if len(content) > _PREVIEW_MAX_CHARS:
            content = content[:_PREVIEW_MAX_CHARS] + f"\n\n[... truncated: {len(content) - _PREVIEW_MAX_CHARS} more chars]"
        result["content"] = content
    return result
