import asyncio
import os
import signal
from typing import Any

from app.config import settings

from . import BaseTool, RiskTier

_MAX_OUTPUT_CHARS = 10_000


class ShellExecTool(BaseTool):
    name = "shell_exec"
    description = "Run a shell command in the project directory. Returns stdout, stderr, and exit code."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)", "default": 30},
            "cwd": {"type": "string", "description": "Working directory relative to project root (default: project root)"},
        },
        "required": ["command"],
    }
    risk_tier: RiskTier = RiskTier.AUTO

    def __init__(self, sandbox: Any = None) -> None:
        self._policy = sandbox

    async def execute(self, **params: Any) -> str:
        command = params["command"]
        timeout = min(params.get("timeout", 30), settings.max_shell_timeout)
        cwd = params.get("cwd", "")

        if self._policy is not None and not self._policy.is_shell_allowed(command):
            allow = ", ".join(self._policy.shell_allowlist) or "(empty)"
            return (
                f"ERROR: shell command '{command.split()[0] if command else ''}' "
                f"is not in this agent's allowlist: [{allow}]"
            )

        work_dir = settings.project_root
        if cwd:
            work_dir = settings.project_root / cwd
            if not work_dir.resolve().is_relative_to(settings.project_root.resolve()):
                return "ERROR: cwd escapes project root"

        try:
            proc = await asyncio.create_subprocess_exec(
                "/bin/sh", "-c", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(work_dir),
                start_new_session=True,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            # Kill the entire process group
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            return f"ERROR: Command timed out after {timeout}s (hard cap: {settings.max_shell_timeout}s)"
        except Exception as exc:
            return f"ERROR: {exc}"

        parts = []
        if stdout:
            parts.append(stdout.decode(errors="replace"))
        if stderr:
            parts.append(f"STDERR: {stderr.decode(errors='replace')}")
        parts.append(f"Exit code: {proc.returncode}")

        output = "\n".join(parts)
        if len(output) > _MAX_OUTPUT_CHARS:
            output = output[:_MAX_OUTPUT_CHARS] + "\n... (output truncated)"
        return output
