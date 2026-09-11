"""On-demand probes through the same execution boundary as agent tools."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from app.config import settings
from app.utils.runtime_identity import PROCESS_IDENTITY, code_revision
from app.utils.tools.execute_code import ExecuteCodeTool
from app.utils.tools.shell import ShellExecTool

_lock = asyncio.Lock()
_last_result: dict | None = None


def snapshot() -> dict:
    import psutil
    workers = []
    for path in settings.agents_dir.glob('*/STATUS.json'):
        try:
            status = json.loads(path.read_text())
            pid = status.get('pid')
            if not pid or not psutil.pid_exists(pid):
                continue
            proc = psutil.Process(pid)
            if 'app.agents.base.runner_entry' not in proc.cmdline():
                continue
            identity = status.get('runtime', {})
            workers.append({'agent': path.parent.name, 'pid': pid,
                            'current': identity.get('revision') == PROCESS_IDENTITY['revision']})
        except (OSError, ValueError, psutil.Error):
            continue
    return {'runtime': {**PROCESS_IDENTITY, 'restart_required': code_revision() != PROCESS_IDENTITY['revision']},
            'workers': workers, 'network_enabled': settings.execution_network_enabled,
            'last_check': _last_result}


async def _python_probe(name: str, code: str, detail: str, fix: str) -> dict:
    try:
        output = await ExecuteCodeTool().execute(code=code + "\nprint('YAPOC_PROBE_OK')", timeout=15)
        ok = 'YAPOC_PROBE_OK' in output and 'Traceback' not in output
    except Exception:
        ok = False
    # Never return raw exceptions or process output: these can contain secrets.
    return {'name': name, 'status': 'ok' if ok else 'failed', 'detail': detail if ok else fix}


async def run_checks() -> dict:
    global _last_result
    async with _lock:
        prefix = str(Path(sys.prefix))
        if Path(sys.prefix).is_relative_to(settings.project_root):
            prefix = '/work/' + Path(sys.prefix).relative_to(settings.project_root).as_posix()
        probes = [
            ('filesystem', "from pathlib import Path; assert Path('/work/pyproject.toml').is_file()", 'Project is visible inside the execution tools.', 'Check the project path and bubblewrap installation.'),
            ('dns', "import socket; assert socket.getaddrinfo('pypi.org',443)", 'PyPI resolves inside the sandbox.', 'Check host DNS and EXECUTION_NETWORK_ENABLED.'),
            ('https', "import urllib.request; assert urllib.request.urlopen('https://pypi.org/simple/',timeout=10).status == 200", 'PyPI HTTPS works inside the sandbox.', 'Check DNS, HTTPS trust stores and outbound connectivity.'),
            ('dependencies', "import httpx, trafilatura, curl_cffi, fake_useragent", 'Required fetch dependencies import successfully.', 'Run poetry install in the managed environment.'),
            ('environment', 'import sys; assert sys.prefix == ' + repr(prefix), 'Python uses the managed environment.', 'Restart YAPOC from its Poetry environment.'),
        ]
        checks = await asyncio.gather(*(_python_probe(*probe) for probe in probes))
        try:
            result = await ShellExecTool().execute(command='poetry env info --path', timeout=15)
            ok = 'Exit code: 0' in result and prefix in result
        except Exception:
            ok = False
        checks.append({'name': 'poetry', 'status': 'ok' if ok else 'failed',
                       'detail': 'Poetry can locate the managed environment.' if ok else 'Check Poetry on the backend PATH and restart from the project environment.'})
        try:
            from app.utils.db import get_db
            get_db().execute('SELECT 1 FROM task_queue LIMIT 1').fetchall()
            ready = True
        except Exception:
            ready = False
        checks.append({'name': 'backend', 'status': 'ok' if ready else 'failed',
                       'detail': 'Backend and task storage are ready.' if ready else 'Check task storage and backend startup.'})
        _last_result = {'checked_at': datetime.now(timezone.utc).isoformat(),
                        'status': 'ok' if all(c['status'] == 'ok' for c in checks) else 'degraded', 'checks': checks}
        return snapshot()
