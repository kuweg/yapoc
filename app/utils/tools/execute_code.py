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

import json
import os
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
        "Internet and DNS are available unless EXECUTION_NETWORK_ENABLED=false. "
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

        from .process_sandbox import command, run, SandboxUnavailable
        forbidden = list(getattr(self._policy, "forbidden_paths", []) or [])
        if len(code) > 200_000:
            return 'ERROR: Script exceeds the size limit.'
        bootstrap = (
            "import os, importlib.util\n"
            "os.environ['YAPOC_PROJECT_ROOT'] = '/work'\n"
            f"os.environ['YAPOC_FORBIDDEN_PATHS'] = {json.dumps(forbidden)!r}\n"
            "spec = importlib.util.spec_from_file_location('yapoc', '/run/code_api.py')\n"
            "yapoc = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(yapoc)\n"
        )
        fd, script_path = tempfile.mkstemp(suffix='.py', prefix='yapoc_exec_')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(bootstrap + code)
            args = command(root, [sys.executable, '-I', '/run/script.py'], forbidden=forbidden,
                           bindings=[(script_path, '/run/script.py'),
                                     (Path(__file__).with_name('code_api.py'), '/run/code_api.py')])
            returncode, out, err = await run(args, timeout)
            if returncode:
                return truncate_tool_output(f'execute_code FAILED (exit {returncode})\n{out}\n{err}', cap=_MAX_OUTPUT)
            return truncate_tool_output(out or err or 'execute_code completed; no output.', cap=_MAX_OUTPUT)
        except TimeoutError:
            return 'ERROR: execute_code timed out; process group terminated.'
        except (SandboxUnavailable, OSError):
            return 'ERROR: Isolated execution unavailable or resource limit exceeded. Linux bubblewrap and util-linux are required.'
        finally:
            Path(script_path).unlink(missing_ok=True)
