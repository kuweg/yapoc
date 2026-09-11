from typing import Any

from app.config import settings

from . import BaseTool


class ShellExecTool(BaseTool):
    name = "shell_exec"
    description = "Run a command in an isolated project filesystem without credentials. Use cwd or a leading cd directory && command. Node, npm, npx, pnpm, yarn, corepack and bun are available when installed on the host. Poetry is available with the managed project virtualenv, even outside the project root; validated dependency commands can download packages and update that environment. Internet and DNS are available unless EXECUTION_NETWORK_ENABLED=false. Returns bounded stdout, stderr, and exit code."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 300 for JavaScript commands, otherwise 30)", "default": 30},
            "cwd": {"type": "string", "description": "Working directory relative to project root (default: project root)"},
        },
        "required": ["command"],
    }

    def __init__(self, sandbox: Any = None) -> None:
        self._policy = sandbox

    async def execute(self, **params: Any) -> str:
        command = params["command"]
        timeout = min(params.get("timeout", 30), settings.max_shell_timeout)
        cwd = params.get("cwd", "")

        if self._policy and self._policy.shell_allowlist:
            from . import project_shell_arguments
            try:
                _, checked_argv = project_shell_arguments(command)
            except ValueError:
                return 'ERROR: Unsupported shell syntax. Use one command per call, cwd for the directory, or cd directory && command. Pipes, redirects and other chaining are not accepted; this is not an executable allowlist failure.'
        if self._policy is not None and not self._policy.is_shell_allowed(command):
            allow = ", ".join(self._policy.shell_allowlist) or "(empty)"
            return (
                f"ERROR: shell command '{checked_argv[0] if command else ''}' "
                f"is not in this agent's allowlist: [{allow}]"
            )

        work_dir = settings.project_root
        if cwd:
            work_dir = settings.project_root / cwd
            if not work_dir.resolve().is_relative_to(settings.project_root.resolve()):
                return "ERROR: cwd escapes project root"

        from . import project_shell_arguments, truncate_tool_output
        from .process_sandbox import command as isolated_command, run, SandboxUnavailable
        from .poetry_execution import operation
        try:
            restricted = bool(self._policy and self._policy.shell_allowlist)
            try:
                directory, parsed = project_shell_arguments(command)
                if directory is not None:
                    work_dir = (work_dir / directory).resolve()
                    if not work_dir.is_relative_to(settings.project_root.resolve()):
                        return 'ERROR: cwd escapes project root'
                    cwd = str(work_dir.relative_to(settings.project_root.resolve()))
                poetry_mode = operation(parsed)
            except ValueError:
                parsed, poetry_mode = [], None
            from .javascript_execution import executable_name
            javascript = executable_name(parsed)
            if javascript:
                timeout = min(params.get('timeout', 300), settings.max_shell_timeout)
            argv = parsed if parsed else ['/bin/sh', '-c', command]
            if restricted and not parsed:
                raise ValueError('Invalid command')
            if not argv:
                raise ValueError('Invalid command')
            args = isolated_command(settings.project_root, argv,
                                    forbidden=getattr(self._policy, 'forbidden_paths', ()), cwd=cwd or '.',
                                    poetry_mode=poetry_mode, profile="shell")
            returncode, stdout, stderr = await run(args, max(1, timeout))
            return truncate_tool_output(f'{stdout}\n{stderr}\nExit code: {returncode}', cap=20_000)
        except TimeoutError:
            return 'ERROR: Command timed out; process group terminated.'
        except (SandboxUnavailable, OSError, ValueError):
            return 'ERROR: Isolated shell unavailable, command refused, or resource limit exceeded. Linux bubblewrap and util-linux are required.'
