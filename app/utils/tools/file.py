import base64
import csv
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import aiofiles

from app.config import settings
from app.utils.secrets import scrub_pii

from . import BaseTool, RiskTier, TOOL_OUTPUT_CHAR_CAP, truncate_tool_output

_MAX_READ_CHARS = 18000

# Protected file patterns that FileDeleteTool refuses to remove
_PROTECTED_NAMES = {".env", ".git", ".gitignore"}
_PROTECTED_AGENT_FILES = {
    "PROMPT.MD",
    "TASK.MD",
    "MEMORY.MD",
    "NOTES.MD",
    "HEALTH.MD",
    "CONFIG.md",
}


def _sandbox(path_str: str) -> Path:
    """Resolve path relative to project root, rejecting escapes."""
    root = settings.project_root.resolve()
    resolved = (root / path_str).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Path escapes project root: {path_str}")
    return resolved


class FileReadTool(BaseTool):
    name = "file_read"
    description = (
        "Read a file relative to the project root. Content is truncated at 8000 chars."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to project root",
            },
        },
        "required": ["path"],
    }

    async def execute(self, **params: Any) -> str:
        try:
            resolved = _sandbox(params["path"])
        except ValueError as exc:
            return f"ERROR: {exc}"

        if not resolved.exists():
            return f"ERROR: File not found: {params['path']}"
        if not resolved.is_file():
            return f"ERROR: Not a file: {params['path']}"

        try:
            async with aiofiles.open(resolved, encoding="utf-8") as f:
                content = await f.read(_MAX_READ_CHARS + 1)
        except Exception as exc:
            return f"ERROR: {exc}"

        if len(content) > _MAX_READ_CHARS:
            return content[:_MAX_READ_CHARS] + "\n... (truncated)"
        return content


class FileListTool(BaseTool):
    name = "file_list"
    description = "List directory contents relative to the project root."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path relative to project root (default: root)",
                "default": ".",
            },
            "recursive": {
                "type": "boolean",
                "description": "List recursively (default: false)",
                "default": False,
            },
        },
        "required": [],
    }

    async def execute(self, **params: Any) -> str:
        path_str = params.get("path", ".")
        recursive = params.get("recursive", False)

        try:
            resolved = _sandbox(path_str)
        except ValueError as exc:
            return f"ERROR: {exc}"

        if not resolved.exists():
            return f"ERROR: Directory not found: {path_str}"
        if not resolved.is_dir():
            return f"ERROR: Not a directory: {path_str}"

        entries: list[str] = []
        try:
            if recursive:
                for p in sorted(resolved.rglob("*")):
                    if any(
                        part.startswith(".") for part in p.relative_to(resolved).parts
                    ):
                        continue
                    rel = p.relative_to(settings.project_root.resolve())
                    suffix = "/" if p.is_dir() else ""
                    entries.append(f"{rel}{suffix}")
            else:
                for p in sorted(resolved.iterdir()):
                    if p.name.startswith("."):
                        continue
                    suffix = "/" if p.is_dir() else ""
                    entries.append(f"{p.name}{suffix}")
        except Exception as exc:
            return f"ERROR: {exc}"

        if not entries:
            return "(empty directory)"

        # Truncate if too many entries
        if len(entries) > 200:
            entries = entries[:200]
            entries.append(f"... ({len(entries)} more entries)")

        return "\n".join(entries)


class FileWriteTool(BaseTool):
    name = "file_write"
    description = "Create or overwrite a file relative to the project root. Creates parent directories automatically."
    risk_tier = RiskTier.CONFIRM
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to project root",
            },
            "content": {"type": "string", "description": "Content to write"},
        },
        "required": ["path", "content"],
    }

    def __init__(self, sandbox: Any = None) -> None:
        self._policy = sandbox

    async def execute(self, **params: Any) -> str:
        try:
            resolved = _sandbox(params["path"])
        except ValueError as exc:
            return f"ERROR: {exc}"

        if self._policy is not None and self._policy.is_forbidden(params["path"]):
            return f"ERROR: path '{params['path']}' is forbidden by this agent's sandbox policy"

        content = params["content"]

        # Create parent dirs
        resolved.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: write to temp file then rename
        try:
            fd, tmp_path = tempfile.mkstemp(dir=resolved.parent, suffix=".tmp")
            try:
                async with aiofiles.open(
                    fd, mode="w", encoding="utf-8", closefd=True
                ) as f:
                    await f.write(content)
                os.replace(tmp_path, resolved)
            except Exception:
                # Clean up temp file on failure
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise
        except Exception as exc:
            return f"ERROR: {exc}"

        return f"Written {len(content)} chars to {params['path']}"


class FileEditTool(BaseTool):
    name = "file_edit"
    description = "Replace a unique string in a file. The old_string must appear exactly once in the file."
    risk_tier = RiskTier.CONFIRM
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to project root",
            },
            "old_string": {
                "type": "string",
                "description": "Exact string to find (must be unique in file)",
            },
            "new_string": {"type": "string", "description": "Replacement string"},
        },
        "required": ["path", "old_string", "new_string"],
    }

    def __init__(self, sandbox: Any = None) -> None:
        self._policy = sandbox

    async def execute(self, **params: Any) -> str:
        try:
            resolved = _sandbox(params["path"])
        except ValueError as exc:
            return f"ERROR: {exc}"

        if self._policy is not None and self._policy.is_forbidden(params["path"]):
            return f"ERROR: path '{params['path']}' is forbidden by this agent's sandbox policy"

        if not resolved.exists():
            return f"ERROR: File not found: {params['path']}"
        if not resolved.is_file():
            return f"ERROR: Not a file: {params['path']}"

        old_string = params["old_string"]
        new_string = params["new_string"]

        try:
            async with aiofiles.open(resolved, encoding="utf-8") as f:
                content = await f.read()
        except Exception as exc:
            return f"ERROR: {exc}"

        count = content.count(old_string)
        if count == 0:
            return "ERROR: old_string not found in file"
        if count > 1:
            return f"ERROR: old_string appears {count} times — must be unique"

        new_content = content.replace(old_string, new_string, 1)

        # Atomic write
        try:
            fd, tmp_path = tempfile.mkstemp(dir=resolved.parent, suffix=".tmp")
            try:
                async with aiofiles.open(
                    fd, mode="w", encoding="utf-8", closefd=True
                ) as f:
                    await f.write(new_content)
                os.replace(tmp_path, resolved)
            except Exception:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise
        except Exception as exc:
            return f"ERROR: {exc}"

        return f"Replaced 1 occurrence in {params['path']}"


class FileDeleteTool(BaseTool):
    name = "file_delete"
    description = "Delete a file relative to the project root. Refuses directories and protected files."
    risk_tier = RiskTier.CONFIRM
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to project root",
            },
        },
        "required": ["path"],
    }

    def __init__(self, sandbox: Any = None) -> None:
        self._policy = sandbox

    async def execute(self, **params: Any) -> str:
        try:
            resolved = _sandbox(params["path"])
        except ValueError as exc:
            return f"ERROR: {exc}"

        if self._policy is not None and self._policy.is_forbidden(params["path"]):
            return f"ERROR: path '{params['path']}' is forbidden by this agent's sandbox policy"

        if not resolved.exists():
            return f"ERROR: File not found: {params['path']}"
        if resolved.is_dir():
            return "ERROR: Cannot delete directories — only files"

        # Check protected names
        if resolved.name in _PROTECTED_NAMES:
            return f"ERROR: Refusing to delete protected file: {resolved.name}"
        if resolved.name in _PROTECTED_AGENT_FILES:
            return f"ERROR: Refusing to delete core agent file: {resolved.name}"

        try:
            resolved.unlink()
        except Exception as exc:
            return f"ERROR: {exc}"

        return f"Deleted {params['path']}"


# ── Image & CSV tools ────────────────────────────────────────────────────────

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


class ImageReadTool(BaseTool):
    name = "image_read"
    description = (
        "Read an image file, base64-encode it, and return metadata + encoded data. "
        "Supports PNG, JPG, JPEG, GIF, WEBP. Max 5MB."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Image file path relative to project root",
            },
        },
        "required": ["path"],
    }

    async def execute(self, **params: Any) -> str:
        try:
            resolved = _sandbox(params["path"])
        except ValueError as exc:
            return f"ERROR: {exc}"

        if not resolved.exists():
            return f"ERROR: File not found: {params['path']}"
        if not resolved.is_file():
            return f"ERROR: Not a file: {params['path']}"

        ext = resolved.suffix.lower()
        if ext not in _IMAGE_EXTENSIONS:
            return (
                f"ERROR: Unsupported image extension '{ext}'. "
                f"Supported: {', '.join(sorted(_IMAGE_EXTENSIONS))}"
            )

        size = resolved.stat().st_size
        if size > _MAX_IMAGE_BYTES:
            return (
                f"ERROR: Image too large ({size:,} bytes). "
                f"Maximum: {_MAX_IMAGE_BYTES:,} bytes (5MB)"
            )

        try:
            data = resolved.read_bytes()
        except Exception as exc:
            return f"ERROR: {exc}"

        b64 = base64.b64encode(data).decode("ascii")
        media_type = _MIME_MAP[ext]

        result = json.dumps({
            "type": "image_read",
            "media_type": media_type,
            "data": b64,
            "size_bytes": size,
            "path": params["path"],
        })
        return result


class ParseCsvTool(BaseTool):
    name = "parse_csv"
    description = (
        "Parse a CSV file and return its contents as a markdown table. "
        "Supports column filtering and row limiting. PII is automatically scrubbed."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "CSV file path relative to project root",
            },
            "max_rows": {
                "type": "integer",
                "description": "Maximum rows to return (default: 100)",
                "default": 100,
            },
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Column names to include (default: all columns)",
            },
        },
        "required": ["path"],
    }

    async def execute(self, **params: Any) -> str:
        try:
            resolved = _sandbox(params["path"])
        except ValueError as exc:
            return f"ERROR: {exc}"

        if not resolved.exists():
            return f"ERROR: File not found: {params['path']}"
        if not resolved.is_file():
            return f"ERROR: Not a file: {params['path']}"

        max_rows = params.get("max_rows", 100)
        col_filter = params.get("columns") or []

        try:
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"ERROR: {exc}"

        # Scrub PII from data files
        text = scrub_pii(text)

        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            return "ERROR: CSV file has no headers"

        # Apply column filter
        columns = [c for c in reader.fieldnames if c in col_filter] if col_filter else list(reader.fieldnames)
        if col_filter and not columns:
            return (
                f"ERROR: None of the requested columns found. "
                f"Available: {', '.join(reader.fieldnames)}"
            )

        # Read rows
        rows: list[dict[str, str]] = []
        total_in_file = 0
        for row in reader:
            total_in_file += 1
            if len(rows) < max_rows:
                rows.append({c: (row.get(c) or "") for c in columns})

        # Build markdown table
        header = "| " + " | ".join(columns) + " |"
        separator = "| " + " | ".join("---" for _ in columns) + " |"
        lines = [header, separator]
        for row in rows:
            line = "| " + " | ".join(row.get(c, "") for c in columns) + " |"
            lines.append(line)

        table = "\n".join(lines)

        # Summary
        truncated = total_in_file > max_rows
        summary = (
            f"\n\n**Summary:** {len(rows)} rows shown"
            f" (of {total_in_file} total)"
            f" | {len(columns)} columns: {', '.join(columns)}"
        )
        if truncated:
            summary += f" | Truncated at max_rows={max_rows}"

        result = table + summary
        return truncate_tool_output(result)
