"""Grep tool — safe, read-only text search across project files.

Wraps ``grep -rn`` with path-safety constraints so no agent can
accidentally read sensitive files or leave the project root.
"""

import subprocess
from pathlib import Path
from typing import Any

from app.utils.tools import BaseTool, SandboxPolicy


class GrepTool(BaseTool):
    name = "grep"
    description = "Search for text patterns across project files using grep. Safe, read-only, sandboxed to project root. Use this instead of shell_exec for file content searches."
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Search pattern (passed to grep -E, so basic regex works).",
            },
            "path": {
                "type": "string",
                "description": "Directory or file to search in, relative to project root (default: project root).",
                "default": "",
            },
            "include": {
                "type": "string",
                "description": "Only search files matching this glob pattern (e.g. '*.py', '*.md'). Passed to --include.",
                "default": "",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of matching lines to return (default: 30). Use --max-count internally, not head, so grep stops early.",
                "default": 30,
            },
            "ignore_case": {
                "type": "boolean",
                "description": "Case-insensitive search (-i flag, default: false).",
                "default": False,
            },
        },
        "required": ["pattern"],
    }

    def __init__(self, sandbox: SandboxPolicy | None = None):
        self._sandbox = sandbox or SandboxPolicy()
        self._project_root = self._resolve_project_root()

    @staticmethod
    def _resolve_project_root() -> Path:
        """Walk up from cwd until we find a marker file."""
        cwd = Path.cwd()
        for ancestor in [cwd] + list(cwd.parents):
            if (ancestor / "pyproject.toml").exists() or (ancestor / ".git").exists():
                return ancestor
        return cwd

    def _verify_path(self, rel_path: str) -> Path:
        """Resolve a project-relative path and verify it stays within project root."""
        if rel_path:
            resolved = (self._project_root / rel_path).resolve()
        else:
            resolved = self._project_root.resolve()
        # Jail: must be inside project root
        try:
            resolved.relative_to(self._project_root.resolve())
        except ValueError:
            raise ValueError(f"Path escapes project root: {rel_path}")
        # Forbidden paths check
        if resolved.is_file():
            check = str(resolved.relative_to(self._project_root.resolve()))
        else:
            # For directories, check the sandbox's forbidden list indirectly
            check = str(resolved.relative_to(self._project_root.resolve())) if resolved != self._project_root else ""
        if check and any(check == prefix or check.startswith(prefix + "/") for prefix in self._sandbox.forbidden_paths):
            raise ValueError(f"Path is forbidden by sandbox policy: {rel_path}")
        return resolved

    async def execute(
        self,
        pattern: str,
        path: str = "",
        include: str = "",
        max_results: int = 30,
        ignore_case: bool = False,
    ) -> str:
        target = self._verify_path(path)
        cmd = ["grep", "-rn"]
        if ignore_case:
            cmd.append("-i")
        if include:
            cmd.extend(["--include", include])
        cmd.extend(["-m", str(max_results), pattern, str(target)])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return "grep timed out after 30s (result was too large). Narrow your search."

        if result.returncode == 0:
            output = result.stdout
            if len(output) > 50000:
                output = output[:50000] + "\n... (truncated at 50KB)"
            if not output.strip():
                return "No matches found."
            return output
        elif result.returncode == 1:
            return "No matches found."
        else:
            return f"grep failed (exit {result.returncode}): {result.stderr.strip() or 'unknown error'}"
