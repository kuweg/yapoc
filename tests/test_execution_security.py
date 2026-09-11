"""Behavioral regressions for isolation, credential boundaries and output budgets."""
import asyncio
import base64
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from app.config import settings
from app.utils.tools import SandboxPolicy, truncate_tool_output
from app.utils.tools import execute_code, file, process_sandbox


@pytest.fixture
def isolated_root(tmp_path, monkeypatch):
    monkeypatch.setattr(execute_code, 'settings', SimpleNamespace(project_root=tmp_path))
    (tmp_path / 'input.txt').write_text('ordinary input')
    return tmp_path


def require_isolation():
    if not shutil.which('bwrap') or not shutil.which('prlimit'):
        pytest.skip('Install bubblewrap/util-linux to run OS isolation tests')


async def test_python_isolated_io_and_forbidden_writes(isolated_root, tmp_path, monkeypatch):
    require_isolation()
    monkeypatch.setattr(settings, "execution_network_enabled", False)
    protected = isolated_root / 'locked'
    protected.mkdir()
    (protected / 'file.txt').write_text('unchanged')
    outside = isolated_root.parent / 'outside-marker.txt'
    outside.write_text('outside sentinel')
    (isolated_root / '.env').write_text('GITHUB_TOKEN=synthetic-do-not-return')
    (isolated_root / 'alias').symlink_to('.env')
    code = f"""
from pathlib import Path
import os, socket
print(yapoc.read('input.txt'))
yapoc.write('output.txt', 'created')
assert not Path({str(outside)!r}).exists()
for path in ('/work/.env', '/work/alias'):
    try:
        assert Path(path).read_text() == ''
    except PermissionError:
        pass
assert not any('TOKEN' in key or 'SECRET' in key for key in os.environ)
try:
    Path('/work/locked/file.txt').write_text('changed')
except OSError:
    print('forbidden write blocked')
else:
    raise AssertionError('write escaped policy')
s = socket.socket()
s.settimeout(0.2)
assert s.connect_ex(('1.1.1.1', 443)) != 0
"""
    result = await execute_code.ExecuteCodeTool(SandboxPolicy(forbidden_paths=['locked'])).execute(code=code)
    assert 'ordinary input' in result, result
    assert 'forbidden write blocked' in result, result
    assert (isolated_root / 'output.txt').read_text() == 'created'
    assert (protected / 'file.txt').read_text() == 'unchanged'


@pytest.mark.skipif(
    sys.platform != 'linux',
    reason='fail-closed isolation is a Linux guarantee; other platforms have no '
           'bubblewrap equivalent and run unsandboxed by design',
)
async def test_missing_sandbox_never_executes(isolated_root, monkeypatch):
    """A Linux host missing bwrap/prlimit is a broken install, not a platform
    limit — it must refuse to run, never silently drop isolation."""
    monkeypatch.setattr(process_sandbox.shutil, 'which', lambda _: None)
    result = await execute_code.ExecuteCodeTool().execute(code="yapoc.write('escaped', 'bad')")
    assert result.startswith('ERROR:')
    assert not (isolated_root / 'escaped').exists()


def test_sandbox_is_mandatory_on_linux():
    """The fallback must key on the platform, not on tool availability."""
    assert process_sandbox.SANDBOX_REQUIRED == (sys.platform == 'linux')


def test_sandbox_available_needs_linux_and_both_binaries(monkeypatch):
    monkeypatch.setattr(process_sandbox.shutil, 'which', lambda _: None)
    assert process_sandbox.sandbox_available() is False
    monkeypatch.setattr(process_sandbox.shutil, 'which', lambda name: f'/usr/bin/{name}')
    monkeypatch.setattr(process_sandbox.sys, 'platform', 'darwin')
    assert process_sandbox.sandbox_available() is False


async def test_unsandboxed_platforms_still_execute(isolated_root, monkeypatch):
    """macOS/Windows have no bubblewrap equivalent: the script runs directly.

    Simulated by flipping SANDBOX_REQUIRED, which is the only thing the tools
    branch on. Proves the fallback path actually runs code rather than erroring.
    """
    monkeypatch.setattr(process_sandbox, 'SANDBOX_REQUIRED', False)
    result = await execute_code.ExecuteCodeTool().execute(
        code="yapoc.write('made-by-fallback.txt', 'ok'); print('ran unsandboxed')"
    )
    assert 'ran unsandboxed' in result
    assert (isolated_root / 'made-by-fallback.txt').read_text() == 'ok'


async def test_forbidden_paths_still_refused_without_a_sandbox(isolated_root, monkeypatch):
    """Without an OS boundary the yapoc helpers are the only guard left, so
    they must still enforce the agent's forbidden_paths."""
    monkeypatch.setattr(process_sandbox, 'SANDBOX_REQUIRED', False)
    locked = isolated_root / 'locked'
    locked.mkdir()
    (locked / 'file.txt').write_text('unchanged')

    result = await execute_code.ExecuteCodeTool(
        SandboxPolicy(forbidden_paths=['locked'])
    ).execute(code="yapoc.write('locked/file.txt', 'bad')")

    assert (locked / 'file.txt').read_text() == 'unchanged'
    assert 'bad' not in (locked / 'file.txt').read_text()
    assert result.startswith('ERROR:') or 'FAILED' in result


async def test_missing_forbidden_path_fails_closed(isolated_root):
    require_isolation()
    result = await execute_code.ExecuteCodeTool(SandboxPolicy(forbidden_paths=['missing'])).execute(
        code="yapoc.write('output.txt', 'bad')")
    assert result.startswith('ERROR:')
    assert not (isolated_root / 'output.txt').exists()


async def test_shell_executes_exact_argv_in_isolation(isolated_root, monkeypatch):
    require_isolation()
    from app.utils.tools import shell
    monkeypatch.setattr(shell, 'settings', SimpleNamespace(project_root=isolated_root, max_shell_timeout=10))
    tool = shell.ShellExecTool(SandboxPolicy(shell_allowlist=['cat', 'printf']))
    assert 'ordinary input' in await tool.execute(command='cat input.txt')
    result = await tool.execute(command='printf harmless; touch escaped')
    assert result.startswith('ERROR:')
    assert not (isolated_root / 'escaped').exists()


async def test_file_ranges_redact_for_direct_callers(tmp_path, monkeypatch):
    monkeypatch.setattr(file, 'settings', SimpleNamespace(project_root=tmp_path))
    (tmp_path / 'ordinary.txt').write_text('first\nghp_SYNTHETIC_RANGED_TOKEN\nlast')
    result = await file.FileReadTool().execute(path='ordinary.txt', start_line=2, tail_lines=1)
    assert 'ghp_' not in result and '[REDACTED]' in result


async def test_output_flood_is_stopped(isolated_root):
    require_isolation()
    result = await execute_code.ExecuteCodeTool().execute(code="while True: print('x' * 8192)", timeout=5)
    assert result.startswith('ERROR:')
    assert len(result) < 1000


async def test_timeout_is_bounded(isolated_root):
    require_isolation()
    result = await execute_code.ExecuteCodeTool().execute(code='while True: pass', timeout=1)
    assert 'timed out' in result


@pytest.mark.parametrize('command', ['poetry --version; printf bypass', 'poetry --version | sh',
                                    'poetryBAD --version', 'poetry $(printf bypass)',
                                    'poetry --version\nsh', 'poetry `id`', 'poetry > output'])
def test_shell_allowlist_rejects_programs(command):
    assert not SandboxPolicy(shell_allowlist=['poetry']).is_shell_allowed(command)


async def test_file_read_denies_credentials_and_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(file, 'settings', SimpleNamespace(project_root=tmp_path))
    (tmp_path / '.env').write_text('SYNTHETIC=not-for-agents')
    (tmp_path / 'alias').symlink_to('.env')
    for path in ('.env', 'alias'):
        result = await file.FileReadTool().execute(path=path)
        assert result.startswith('ERROR:') and 'not-for-agents' not in result


def test_output_redacts_before_capping(monkeypatch):
    monkeypatch.setattr(settings, 'github_token', SecretStr('synthetic-configured-credential'))
    text = 'x' * 90 + 'synthetic-configured-credential' + 'ghp_SYNTHETIC_TOKEN'
    result = truncate_tool_output(text, cap=110)
    assert len(result) <= 110
    assert 'synthetic' not in result and 'ghp_' not in result
    assert len(truncate_tool_output('x' * 100_000)) <= 20_000
    assert 'synthetic-key-body' not in truncate_tool_output(
        '-----BEGIN PRIVATE KEY-----\nsynthetic-key-body\n-----END PRIVATE KEY-----')


async def test_decoded_github_contents_redacted(monkeypatch):
    from app.utils.github import client as gh
    from app.backend.routers.github import _read
    monkeypatch.setattr(settings, 'github_enabled', True)
    monkeypatch.setattr(settings, 'github_token', SecretStr('synthetic-auth'))
    monkeypatch.setattr(settings, 'github_allowed_repos', 'example/review')
    async def response(request):
        return httpx.Response(200, json={'encoding': 'base64', 'path': 'sample.txt',
            'content': base64.b64encode(b'prefix\nghp_SYNTHETIC_FILE_TOKEN\nsuffix').decode()})
    monkeypatch.setattr(gh.client, 'transport', httpx.MockTransport(response))
    result = await _read('example/review', 'contents', path='sample.txt')
    assert 'ghp_' not in result['content']
    assert '[REDACTED]' in result['content']


@pytest.mark.parametrize('name', ['plugin:gmail:send', 'shell_exec', 'execute_code', 'github_create_issue'])
async def test_gate_exception_never_executes(name, monkeypatch):
    from app.agents.base import BaseAgent
    from app.utils.tools import security_gate
    monkeypatch.setattr(security_gate, 'classify', AsyncMock(side_effect=RuntimeError('unavailable')))
    tool = SimpleNamespace(execute=AsyncMock(return_value='should not run'))
    agent = SimpleNamespace(_name='builder')
    result, event = await BaseAgent._execute_tool(agent, SimpleNamespace(name=name, id='test', input={}), {name: tool})
    assert result.is_error
    tool.execute.assert_not_awaited()


async def test_tool_results_redacted_before_events(monkeypatch):
    from app.agents.base import BaseAgent
    from app.utils.tools import security_gate
    monkeypatch.setattr(security_gate, 'classify', AsyncMock(return_value=('allow', 'ok')))
    tool = SimpleNamespace(execute=AsyncMock(return_value='ghp_SYNTHETIC_RESULT_TOKEN'))
    result, event = await BaseAgent._execute_tool(SimpleNamespace(_name='builder'),
        SimpleNamespace(name='file_read', id='test', input={}), {'file_read': tool})
    assert 'ghp_' not in result.content and 'ghp_' not in event.result


@pytest.mark.parametrize('enabled', [True, False])
@pytest.mark.parametrize('tool_name', ['shell', 'python'])
async def test_execution_network_access_follows_setting(isolated_root, monkeypatch, enabled, tool_name):
    """Exercise real sandbox sockets without depending on the public internet."""
    require_isolation()
    from app.utils.tools import shell
    monkeypatch.setattr(settings, 'execution_network_enabled', enabled)
    monkeypatch.setattr(shell, 'settings', SimpleNamespace(project_root=isolated_root, max_shell_timeout=10))

    async def respond(reader, writer):
        writer.write(b'network-ok')
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(respond, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]
    code = f"""
import socket
try:
    with socket.create_connection(('127.0.0.1', {port}), timeout=1) as connection:
        print(connection.recv(32).decode())
except OSError:
    print('network-blocked')
"""
    async with server:
        if tool_name == 'python':
            result = await execute_code.ExecuteCodeTool().execute(code=code)
        else:
            import shlex
            result = await shell.ShellExecTool().execute(command='python -c ' + shlex.quote(code))
    assert ('network-ok' if enabled else 'network-blocked') in result, result
