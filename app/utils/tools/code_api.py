"""The RPC surface available to ``execute_code`` scripts, as ``yapoc.*``.

A script run by :class:`ExecuteCodeTool` gets this module injected as ``yapoc``.
It is deliberately narrow: the same file operations the agent already has as
tools, exposed as plain Python functions so a *mechanical* pipeline can run as
one call instead of one LLM turn per step.

Helpers validate project paths and forbidden writes for useful errors. The
actual security boundary is the OS namespace in process_sandbox: generated
Python can bypass helpers, so helper validation alone is not isolation.

Not a general-purpose SDK. If a script needs reasoning, it should have been a
delegated agent task instead — that is exactly the split this tool exists to
make explicit.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

# Populated from the environment by the bootstrap in ExecuteCodeTool.
_ROOT = Path(os.environ.get("YAPOC_PROJECT_ROOT", ".")).resolve()
_FORBIDDEN: list[str] = json.loads(os.environ.get("YAPOC_FORBIDDEN_PATHS", "[]"))

# Mirrors FileDeleteTool's protected set — a mechanical script must not be able
# to remove an agent's identity or the project's config.
_PROTECTED_NAMES = {
    ".env", ".git", ".gitignore", "PROMPT.MD", "TASK.MD",
    "MEMORY.MD", "NOTES.MD", "HEALTH.MD", "CONFIG.yaml",
}


class SandboxError(RuntimeError):
    """Raised when a script attempts I/O outside its permitted area."""


def _resolve(path_str: str) -> Path:
    """Resolve inside the project root, rejecting escapes."""
    resolved = (_ROOT / path_str).resolve()
    if not resolved.is_relative_to(_ROOT):
        raise SandboxError(f"path escapes project root: {path_str}")
    return resolved


def _check_writable(path_str: str) -> Path:
    resolved = _resolve(path_str)
    rel = str(resolved.relative_to(_ROOT))
    for prefix in _FORBIDDEN:
        if rel == prefix or rel.startswith(prefix.rstrip("/") + "/"):
            raise SandboxError(f"path is forbidden for this agent: {rel}")
    if resolved.name in _PROTECTED_NAMES:
        raise SandboxError(f"protected file: {resolved.name}")
    return resolved


# ── The surface ─────────────────────────────────────────────────────────────

def read(path: str, tail_lines: int = 0) -> str:
    """Return a file's text. ``tail_lines`` returns only the last N lines."""
    p = _resolve(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    if tail_lines and tail_lines > 0:
        return "\n".join(text.splitlines()[-tail_lines:])
    return text


def write(path: str, content: str) -> str:
    """Write a file atomically. Creates parent directories."""
    p = _check_writable(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, p)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return f"wrote {len(content)} chars to {path}"


def edit(path: str, old: str, new: str) -> str:
    """Replace ``old`` with ``new``. ``old`` must appear exactly once."""
    p = _check_writable(path)
    text = p.read_text(encoding="utf-8")
    n = text.count(old)
    if n == 0:
        raise ValueError(f"old_string not found in {path}")
    if n > 1:
        raise ValueError(f"old_string appears {n} times in {path}; must be unique")
    write(path, text.replace(old, new, 1))
    return f"edited {path}"


def delete(path: str) -> str:
    """Delete a file."""
    p = _check_writable(path)
    p.unlink()
    return f"deleted {path}"


def ls(path: str = ".", pattern: str = "*") -> list[str]:
    """List entries under ``path`` relative to the project root."""
    p = _resolve(path)
    if not p.is_dir():
        raise NotADirectoryError(path)
    return sorted(
        str(c.relative_to(_ROOT)) + ("/" if c.is_dir() else "")
        for c in p.glob(pattern)
    )


def grep(pattern: str, path: str = ".", glob: str = "**/*", max_results: int = 200) -> list[str]:
    """Search file contents. Returns ``path:lineno:line``.

    Pure Python on purpose — the shell `grep` tool in this project has a
    documented false-negative problem (recorded in the negative-knowledge
    store), and a mechanical pipeline should not inherit it.
    """
    rx = re.compile(pattern)
    base = _resolve(path)
    out: list[str] = []
    files = [base] if base.is_file() else base.glob(glob)
    for f in files:
        if not f.is_file():
            continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    out.append(f"{f.relative_to(_ROOT)}:{i}:{line.rstrip()[:200]}")
                    if len(out) >= max_results:
                        return out
        except OSError:
            continue
    return out


def exists(path: str) -> bool:
    """True if the path exists inside the project root."""
    try:
        return _resolve(path).exists()
    except SandboxError:
        return False
