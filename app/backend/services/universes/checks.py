"""Checks run with the same filesystem boundary as universe tools."""
import asyncio
import json
import sys
import os
import signal
from pathlib import Path
from app.config import settings
from app.utils.tools import shell_arguments
from app.utils.tools.process_sandbox import command, run
from app.utils.secrets import scrub


_processes = set()


async def check(workspace: Path, text: str):
    argv = shell_arguments(text)
    if not argv: raise ValueError('A check command is required.')
    # Each worktree owns its dependencies. No shared writable node_modules.
    frontend = workspace / 'app/frontend'
    if (frontend / 'package.json').exists() and not (frontend / 'node_modules').exists():
        install = ['pnpm', '--dir', 'app/frontend', 'install', '--frozen-lockfile'] if (frontend / 'pnpm-lock.yaml').exists() else ['npm', '--prefix', 'app/frontend', 'ci']
        code, out, err = await run(command(workspace, install, profile='shell'), 300)
        if code: return {'command': 'Install isolated frontend dependencies', 'exit_code': code, 'output': scrub(out + err)[-6000:]}
    code, out, err = await run(command(workspace, argv, profile='shell'), 300)
    return {'command': text, 'exit_code': code, 'output': scrub(out + err)[-10000:]}


async def run_check_process(workspace: Path, text: str):
    proc = await asyncio.create_subprocess_exec(sys.executable, str(settings.project_root / 'app/universe_entry.py'), 'check', str(workspace), text,
        cwd=settings.project_root, start_new_session=True, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    _processes.add(proc)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), 620)
        if proc.returncode: raise ValueError('Integration checks could not run.')
        return json.loads(out)
    except BaseException:
        if proc.returncode is None: proc.kill(); await proc.wait()
        raise
    finally:
        _processes.discard(proc)


async def stop_checks():
    for proc in list(_processes):
        if proc.returncode is None:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            await proc.wait()


if __name__ == '__main__':
    root = Path(sys.argv[1]).resolve()
    settings._execution_root = root
    print(json.dumps(asyncio.run(check(root, sys.argv[2])), separators=(',', ':')))
