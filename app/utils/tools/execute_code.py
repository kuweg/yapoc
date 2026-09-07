"""``execute_code`` — run a mechanical Python pipeline without an LLM loop.

The cheap half of the delegation split. ``spawn_agent`` / ``delegate_task``
start a full reasoning loop with fresh context: right for work that needs
judgement, and a ~30s round trip plus model spend for work that does not. The
project's own negative-knowledge store records the consequence —

    "Master spawning sub-agents just to cat a file / read a config …
     A full spawn is a ~30s round trip for a 0.1s read."

The tool ladder fixed the single-read case. This fixes the *multi-step*
mechanical case: read twelve files, extract a field from each, write a summary.
Today that is either a dozen LLM turns or a delegated agent; here it is one
call with no model in the loop at all.

Execution model
    A subprocess (never in-process: the backend must not be corruptible by a
    generated script, and a hung script must be killable). The script gets
    ``yapoc`` — see ``code_api`` — for sandboxed file work, and the calling
    agent's ``forbidden_paths`` are enforced inside the child before any I/O.
    stdout is the result; the script prints what it wants the agent to see.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import tempfile
from pathlib import Path
from typing import Any

from app.config import settings

from . import BaseTool, truncate_tool_output

# A mechanical pipeline that runs longer than this is doing something that
# probably wanted an agent. Kept well under shell_exec's cap.
_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 120
_MAX_OUTPUT = 20_000

_BOOTSTRAP = """\
import sys, os
sys.path.insert(0, os.environ["YAPOC_PROJECT_ROOT"])
from app.utils.tools import code_api as yapoc  # noqa: F401  (script API)
"""


class ExecuteCodeTool(BaseTool):
    name = "execute_code"
    description = (
        "Run a short Python script for MECHANICAL work — no LLM reasoning, no "
        "sub-agent, no conversation. Use this instead of spawn_agent/delegate_task "
        "whenever the steps are deterministic and you already know them: batch "
        "file edits, extracting fields from many files, transforming data, "
        "counting/checking things across a tree.\n\n"
        "The script gets a `yapoc` module (already imported) with sandboxed "
        "helpers: yapoc.read(path), yapoc.write(path, content), "
        "yapoc.edit(path, old, new), yapoc.delete(path), yapoc.ls(path, pattern), "
        "yapoc.grep(pattern, path, glob), yapoc.exists(path). All paths are "
        "relative to the project root and cannot escape it.\n\n"
        "print() whatever you need to see — stdout is returned to you. "
        "Use a delegated agent instead when the work needs judgement or the "
        "steps depend on interpreting results."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "Python source. `yapoc` is pre-imported. Example:\n"
                    "for p in yapoc.ls('app/agents', '*'):\n"
                    "    print(p)"
                ),
            },
            "timeout": {
                "type": "integer",
                "description": f"Seconds before the script is killed (default {_DEFAULT_TIMEOUT}, max {_MAX_TIMEOUT})",
                "default": _DEFAULT_TIMEOUT,
            },
        },
        "required": ["code"],
    }

    def __init__(self, sandbox: Any = None) -> None:
        self._policy = sandbox

    async def execute(self, **params: Any) -> str:
        code = params.get("code") or ""
        if not code.strip():
            return "ERROR: execute_code — `code` is required and must be non-empty."

        timeout = max(1, min(int(params.get("timeout", _DEFAULT_TIMEOUT) or _DEFAULT_TIMEOUT), _MAX_TIMEOUT))
        root = settings.project_root.resolve()

        forbidden = list(getattr(self._policy, "forbidden_paths", []) or [])
        env = {
            **os.environ,
            "YAPOC_PROJECT_ROOT": str(root),
            "YAPOC_FORBIDDEN_PATHS": json.dumps(forbidden),
            # Keep the child from inheriting a half-initialised event loop or
            # writing .pyc noise into the tree for a one-shot script.
            "PYTHONDONTWRITEBYTECODE": "1",
        }

        fd, script_path = tempfile.mkstemp(suffix=".py", prefix="yapoc_exec_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(_BOOTSTRAP)
                f.write("\n")
                f.write(code)

            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, script_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(root),
                    env=env,
                    start_new_session=True,
                )
            except Exception as exc:
                return f"ERROR: execute_code — could not start interpreter: {exc}"

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                # Kill the whole group — a script may have spawned children.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    proc.kill()
                # Reap it. Without this the transport is closed by the GC later,
                # which raises "Event loop is closed" noise and leaks a pipe per
                # timed-out script.
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except (asyncio.TimeoutError, ProcessLookupError):
                    pass
                return (
                    f"ERROR: execute_code — script timed out after {timeout}s. "
                    "Mechanical work should be fast; if this needs to run long, "
                    "it probably wants a delegated agent instead."
                )
        finally:
            Path(script_path).unlink(missing_ok=True)

        out = stdout.decode(errors="replace") if stdout else ""
        err = stderr.decode(errors="replace") if stderr else ""

        if proc.returncode != 0:
            # Surface the traceback: the agent wrote this script and is the one
            # that has to fix it.
            parts = [f"execute_code FAILED (exit {proc.returncode})"]
            if out.strip():
                parts.append(f"stdout:\n{out.rstrip()}")
            if err.strip():
                parts.append(f"traceback:\n{err.rstrip()}")
            return truncate_tool_output("\n\n".join(parts), cap=_MAX_OUTPUT)

        if not out.strip():
            hint = (
                "execute_code ran successfully but printed nothing. "
                "Add print() for anything you need to see."
            )
            return f"{hint}\n\nSTDERR: {err.rstrip()}" if err.strip() else hint

        result = out.rstrip()
        if err.strip():
            result += f"\n\nSTDERR: {err.rstrip()}"
        return truncate_tool_output(result, cap=_MAX_OUTPUT)
