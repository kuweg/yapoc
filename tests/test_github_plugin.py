import base64
import importlib.util
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from app.config import settings
from app.utils.github import client as gh
from app.utils.github.mcp import guard, server_config
from app.utils.mcp.host import MCPHostManager, STATE_CONNECTED
from app.utils.mcp.registry import flatten_content
from app.utils.tools.security_policy import is_outward_facing

spec = importlib.util.spec_from_file_location('test_github_plugin_module', 'plugins/github/github.py')
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)


@pytest.fixture(autouse=True)
def config(monkeypatch):
    for name, value in dict(github_enabled=True, github_token=SecretStr('test-private-credential'),
                            github_allowed_repos='example/fork,other/library', github_default_owner='example',
                            github_default_repo='fork', github_self_repo='', github_write_enabled=False,
                            github_mcp_enabled=False).items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(gh, 'last_summary', None)
    monkeypatch.setattr(gh, 'last_success', None)
    monkeypatch.setattr(gh, 'connection', 'not_checked')


@pytest.mark.parametrize('field,value,message', [('github_enabled', False, 'disabled'),
    ('github_token', SecretStr(''), 'credentials'), ('github_allowed_repos', '', 'allowlist'),
    ('github_self_repo', 'outside/repo', 'not allowed')])
async def test_disabled_unconfigured(monkeypatch, field, value, message):
    monkeypatch.setattr(settings, field, value)
    assert message in await plugin.execute_operation('get_repo')


@pytest.mark.parametrize('repo', ['outside/repo', 'example/fork/../secret', 'example/fork?x=y', 'example/%66ork', 'https://example/fork'])
async def test_allowlist(repo):
    assert 'error' in json.loads(await plugin.execute_operation('get_repo', repository=repo))


def test_redaction():
    secret = 'test-private-credential'
    assert secret not in gh.compact({'body': secret, 'nested': [secret], secret: secret})
    assert secret not in repr(settings)
    assert 'github_token' not in settings.model_dump()
    assert 'ghp_abcdef123456' not in gh.compact('ghp_abcdef123456')


@pytest.mark.parametrize('operation', sorted(plugin.WRITES))
async def test_read_only(operation, monkeypatch):
    request = AsyncMock()
    monkeypatch.setattr(gh.client, 'request', request)
    assert 'writes are disabled' in await plugin.execute_operation(operation, number=1)
    request.assert_not_called()
    assert is_outward_facing('github_' + operation)
    assert is_outward_facing('plugin:github:' + operation)


@pytest.mark.parametrize('status,headers,message', [(401, {}, 'authentication'), (403, {}, 'permission'),
    (403, {'x-ratelimit-remaining': '0'}, 'rate limit'), (429, {}, 'rate limit'),
    (500, {}, 'request failed'), (302, {'location': 'https://evil.example'}, 'request failed')])
async def test_api_errors(status, headers, message):
    client = gh.GitHubClient(httpx.MockTransport(lambda req: httpx.Response(status, headers=headers, text='test-private-credential')))
    with pytest.raises(gh.GitHubError, match=message) as exc:
        await client.request('example/fork')
    assert 'test-private-credential' not in str(exc.value)


async def test_transport_error():
    def fail(req):
        raise httpx.ConnectError('test-private-credential', request=req)
    with pytest.raises(gh.GitHubError, match='connection failed'):
        await gh.GitHubClient(httpx.MockTransport(fail)).request('example/fork')


async def test_file_decoded_and_redacted(monkeypatch):
    monkeypatch.setattr(gh.client, 'request', AsyncMock(return_value={'encoding': 'base64', 'content': base64.b64encode(b'test-private-credential').decode()}))
    result = await plugin.execute_operation('read_file', path='README.md')
    assert 'test-private-credential' not in result
    assert 'REDACTED' in result


async def test_health(monkeypatch):
    async def request(repo, suffix, **kwargs):
        if suffix == '/actions/runs':
            return {'workflow_runs': [{'id': 10, 'conclusion': 'failure', 'head_sha': 'abc'}]}
        if suffix == '/issues':
            return [{'number': 2, 'updated_at': '2020-01-01T00:00:00Z', 'labels': [{'name': 'bug'}]}, {'pull_request': {}}]
        if suffix == '/pulls':
            return [{'number': 3, 'head': {'sha': 'abc'}, 'updated_at': '2020-01-01T00:00:00Z'}]
        if suffix.endswith('/check-runs'):
            return {'check_runs': [{'name': 'tests', 'status': 'completed', 'conclusion': 'failure'}]}
        if suffix.endswith('/reviews'):
            return [{'state': 'CHANGES_REQUESTED', 'user': {'login': 'reviewer'}}]
        return {'jobs': [{'steps': [{'name': 'pytest', 'conclusion': 'failure'}]}]}
    monkeypatch.setattr(gh.client, 'request', request)
    summary = await gh.health_summary(head_sha='abc')
    assert summary['open_issues'] == summary['stale_issues'] == 1
    assert summary['stale_pull_requests'] == 1
    assert summary['failed_runs'][0]['failed_steps'] == ['pytest']
    assert summary['pull_request_health'][0]['blocked_checks'] == ['tests']
    assert gh.status()['last_successful_check']


async def test_writes_audited_without_body(monkeypatch):
    monkeypatch.setattr(settings, 'github_write_enabled', True)
    request = AsyncMock(return_value={'number': 5, 'body': 'sensitive body'})
    records = []
    monkeypatch.setattr(gh, 'audit', lambda *args: records.append(args))
    monkeypatch.setattr(gh.client, 'request', request)
    result = await plugin.execute_operation('create_issue', title='title', body='sensitive body')
    assert json.loads(result)['target_id'] == 5
    assert 'sensitive body' not in str(records) + result


def test_mcp_optional(monkeypatch):
    assert server_config() is None
    monkeypatch.setattr(settings, 'github_mcp_enabled', True)
    cfg = server_config()
    assert cfg.resources_allowlist == []
    assert '--read-only' in cfg.args
    for name, arguments in [('create_issue', {'owner': 'example', 'repo': 'fork'}),
                             ('get_file_contents', {'owner': 'outside', 'repo': 'repo'}),
                             ('get_file_contents', {'owner': 'example', 'repo': 'fork', 'path': '../other'})]:
        with pytest.raises(gh.GitHubError):
            guard(name, arguments)
    guard('get_file_contents', {'owner': 'other', 'repo': 'library'})


async def test_mcp_unavailable_and_direct_host_guard(monkeypatch):
    monkeypatch.setattr(settings, 'github_mcp_enabled', True)
    host = MCPHostManager()
    assert 'disconnected' in flatten_content(await host.call_tool('github', 'list_branches', {'owner': 'example', 'repo': 'fork'}))
    session = SimpleNamespace(call_tool=AsyncMock())
    host._state['github'] = STATE_CONNECTED
    host._sessions['github'] = session
    assert 'not allowed' in flatten_content(await host.call_tool('github', 'list_branches', {'owner': 'bad', 'repo': 'repo'}))
    session.call_tool.assert_not_called()
    session.call_tool.side_effect = RuntimeError('test-private-credential')
    result = await host.call_tool('github', 'list_branches', {'owner': 'example', 'repo': 'fork'})
    assert 'test-private-credential' not in flatten_content(result)


async def test_signed_logs_do_not_forward_token():
    seen = []
    def handler(req):
        seen.append(req)
        if req.url.host == 'api.github.com':
            return httpx.Response(302, headers={'location': 'https://logs.blob.core.windows.net/job?sig=private'})
        assert 'authorization' not in req.headers
        return httpx.Response(200, text='failure test-private-credential')
    result = await gh.GitHubClient(httpx.MockTransport(handler)).job_logs('example/fork', 1)
    assert len(seen) == 2
    assert 'test-private-credential' not in result


@pytest.mark.parametrize('term', ['repo:outside/repo', 'hello" OR repo:bad/repo', 'a\nb'])
async def test_search_scope(term):
    assert 'error' in json.loads(await plugin.execute_operation('search_code', query=term))


def test_http_logging_redaction():
    import logging
    from app.utils.github.logging import GitHubHTTPFilter
    record = logging.LogRecord('httpx', logging.INFO, '', 1, 'GET %s', ('https://logs.blob.core.windows.net/job?sig=secret',), None)
    GitHubHTTPFilter().filter(record)
    assert 'sig=' not in record.getMessage()
    record = logging.LogRecord('httpcore.http11', logging.DEBUG, '', 1, 'header %s', ('test-private-credential',), None)
    GitHubHTTPFilter().filter(record)
    assert 'test-private-credential' not in record.getMessage()


async def test_status_route_no_network_and_check_throttling(monkeypatch):
    from app.backend.routers import github
    check = AsyncMock()
    monkeypatch.setattr(gh, 'health_summary', check)
    monkeypatch.setattr(github, '_last_attempt', 0)
    await github.github_status()
    check.assert_not_called()
    await github.github_check()
    await github.github_check()
    assert check.await_count == 1


async def test_periodic_signal_dedup(monkeypatch):
    from app.utils.github import observability
    summary = {'repository': 'example/fork', 'failed_runs': [], 'stale_issues': 0, 'stale_pull_requests': 0}
    monkeypatch.setattr(gh, 'health_summary', AsyncMock(return_value=summary))
    monkeypatch.setattr(observability, '_last_signal', None)
    calls = []
    monkeypatch.setattr(observability.logger, 'info', lambda *args: calls.append(args))
    await observability.check_health()
    await observability.check_health()
    assert len(calls) == 1


def test_agent_grants_and_plugin_manifest():
    import pathlib
    config = json.loads(pathlib.Path('app/config/agent-settings.json').read_text())
    for agent in ('master', 'doctor', 'evaluator', 'builder'):
        tools = [t for t in config['agents'][agent]['tools'] if t.startswith('github_')]
        assert tools
        yaml = pathlib.Path(f'app/agents/{agent}/CONFIG.yaml').read_text()
        for tool in tools:
            assert f'  - {tool}\n' in yaml
            assert tool.removeprefix('github_') not in plugin.WRITES
            assert any(isinstance(cls, type) and getattr(cls, 'name', None) == tool for cls in vars(plugin).values())
    assert not any(t.startswith('github_') for t in config['agents']['keeper']['tools'])


async def test_signed_log_redirect_rejected():
    client = gh.GitHubClient(httpx.MockTransport(lambda req: httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})))
    with pytest.raises(gh.GitHubError, match='destination refused'):
        await client.job_logs('example/fork', 1)


async def test_successful_mcp_result_sanitized(monkeypatch):
    monkeypatch.setattr(settings, 'github_mcp_enabled', True)
    host = MCPHostManager()
    host._state['github'] = STATE_CONNECTED
    host._sessions['github'] = SimpleNamespace(call_tool=AsyncMock(return_value=SimpleNamespace(
        content=[SimpleNamespace(text='test-private-credential')], isError=False)))
    result = await host.call_tool('github', 'list_branches', {'owner': 'example', 'repo': 'fork'})
    assert 'test-private-credential' not in flatten_content(result)
    assert 'REDACTED' in flatten_content(result)


async def test_draft_creation_and_update_guard(monkeypatch):
    monkeypatch.setattr(settings, 'github_write_enabled', True)
    request = AsyncMock(return_value={'number': 8})
    monkeypatch.setattr(gh.client, 'request', request)
    result = await plugin.execute_operation('create_draft_pull_request', title='Draft', body='', head='feature', base='trunk')
    assert json.loads(result)['ok']
    assert request.call_args.kwargs['payload']['draft'] is True
    request.reset_mock()
    request.return_value = {'draft': False, 'state': 'open'}
    result = await plugin.execute_operation('update_draft_pull_request', number=8, title='Draft', body='')
    assert 'Only open draft' in result
    assert request.await_count == 1


async def test_agent_fails_closed_when_policy_unavailable(monkeypatch, tmp_path):
    from app.agents.base import BaseAgent
    from app.utils.tools import security_gate
    agent = BaseAgent(tmp_path)
    monkeypatch.setattr(security_gate, 'classify', AsyncMock(side_effect=RuntimeError('test-private-credential')))
    tool = SimpleNamespace(execute=AsyncMock())
    tc = SimpleNamespace(name='github_create_issue', id='call', input={'title': 'test'})
    result, _ = await agent._execute_tool(tc, {tc.name: tool})
    assert result.is_error
    assert 'test-private-credential' not in result.content
    tool.execute.assert_not_called()


async def test_draft_head_cannot_escape_repository(monkeypatch):
    monkeypatch.setattr(settings, 'github_write_enabled', True)
    request = AsyncMock()
    monkeypatch.setattr(gh.client, 'request', request)
    result = await plugin.execute_operation('create_draft_pull_request', title='Draft', body='', head='outside:branch', base='trunk')
    assert 'selected repository' in result
    request.assert_not_called()


@pytest.mark.parametrize('path', ['/integrations/github', '/api/integrations/github'])
async def test_github_http_paths_match_frontend_proxy(path, monkeypatch):
    from fastapi import FastAPI
    from app.backend.dashboard import ApiPrefixMiddleware
    from app.backend.routers.github import router
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(ApiPrefixMiddleware)
    monkeypatch.setattr(settings, 'github_enabled', False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as http:
        response = await http.get(path)
    assert response.status_code == 200
    assert response.json()['enabled'] is False
