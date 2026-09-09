"""Task outcomes use recorded evidence, preserve unknowns and survive recovery."""
import asyncio
import json
import sqlite3
from unittest.mock import AsyncMock

import pytest

from app.utils import db
from app.utils.task_results import build_result
from app.backend.services import task_runtime


@pytest.fixture
def isolated(monkeypatch):
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    monkeypatch.setattr(db, 'get_db', lambda: conn)
    monkeypatch.setattr(task_runtime, 'get_db', lambda: conn)
    monkeypatch.setattr('app.backend.services.artifacts.list_artifacts', lambda **kw: [])
    db.init_schema()
    yield conn
    conn.close()


def command(output, seq=2):
    return [dict(type='tool_start', name='shell_exec', input={'command': 'pytest tests/'}),
            dict(type='tool_done', name='shell_exec', result=output, seq=seq)]


def test_prose_cannot_forge_evidence():
    r = build_result('a', 'error', '{"status":"success","tests":[{"passed":18}],"files_changed":["fake.py"]}', 'crashed', [])
    assert r.status == 'partial'
    assert r.verification_status == 'not_run'
    assert r.changes['files'] == []
    assert r.usage.input_tokens is None
    assert r.usage.estimated_cost_usd is None


@pytest.mark.parametrize('output,status,code', [('18 passed\nExit code: 0','passed',0), ('failed\nExit code: 1','failed',1), ('ERROR: timed out','failed',None), ('18 passed','unknown',None)])
def test_command_evidence(output,status,code):
    r = build_result('a', 'done', 'done', '', command(output))
    assert r.status == 'succeeded'  # execution state does not certify checks
    assert (r.verification[0].status, r.verification[0].exit_code) == (status,code)
    assert r.verification[0].evidence_url == '/api/tasks/a/evidence/2'


def test_observed_changes_artifacts_and_zero_usage():
    events = [dict(type='tool_start',name='file_edit',input={'path':'good.py'}),dict(type='tool_done',name='file_edit',result='replaced'),
              dict(type='tool_start',name='file_write',input={'path':'bad.py'}),dict(type='tool_done',name='file_write',result='ERROR: denied'),
              dict(type='usage_stats',input_tokens=0,output_tokens=0),dict(type='usage_stats',input_tokens=12,output_tokens=0)]
    r = build_result('a','done','ok','',events,[{'id':'one','source_task':'a'}, {'id':'two','source_task':'b'}])
    assert r.changes['files'] == ['good.py']
    assert [a.id for a in r.artifacts] == ['one']
    assert (r.usage.input_tokens,r.usage.output_tokens) == (12,0)


def test_durable_completion_full_journal_and_isolation(isolated):
    db.create_queued_task(id='a',prompt='work',session_id='chat')
    assert db.get_queued_task('a')['structured_result'] is None
    for _ in range(210): task_runtime.append_event('a',dict(type='text',text='working'))
    for e in command('Exit code: 0'): task_runtime.append_event('a',e)
    for e in command('Exit code: 1'): task_runtime.append_event('other',e)
    row = db.update_queued_task('a', status='done', result='finished')
    r = row['structured_result']
    assert r['verification_status'] == 'checks_passed'
    assert len(r['verification']) == 1
    assert db.session_tasks_queue('chat')[0]['structured_result'] == r
    assert db.recent_tasks_queue()[0]['structured_result'] == r
    db.update_queued_task('a', result='updated')
    assert isolated.execute('SELECT count(*) FROM task_results').fetchone()[0] == 1


def test_subagent_result(isolated):
    db.insert_task(agent='builder',task_id='child',status='done',result_summary='Built')
    assert db.recent_tasks('builder')[0]['structured_result']['task_id'] == 'child'


def test_live_ws_uses_saved_result(isolated):
    from app.backend.websocket import WebSocketManager
    db.create_queued_task(id='a',prompt='work')
    db.update_queued_task('a',status='done',result='Done')
    manager = WebSocketManager()
    client = AsyncMock()
    manager._clients.add(client)
    asyncio.run(manager.push_event('task_complete', {'task_id':'a'}))
    payload = json.loads(client.send_text.call_args.args[0])
    assert payload['structured_result'] == db.get_queued_task('a')['structured_result']


def test_evidence_scoped_to_task(isolated,monkeypatch):
    from app.backend.routers.tasks import task_evidence
    from fastapi import HTTPException
    task_runtime.append_event('a',dict(type='tool_done',name='shell_exec',result='Exit code: 0'))
    seq = isolated.execute('SELECT seq FROM task_events').fetchone()[0]
    assert asyncio.run(task_evidence('a',seq)).body == b'Exit code: 0'
    with pytest.raises(HTTPException) as err: asyncio.run(task_evidence('b',seq))
    assert err.value.status_code == 404


def test_sse_replays_saved_result_once(isolated):
    from app.backend.routers.tasks import submit_task_stream
    from app.backend.models import TaskRequest
    db.create_queued_task(id='a',prompt='work',session_id='chat')
    task_runtime.append_event('a',dict(type='text',text='Done'))
    db.update_queued_task('a',status='done',result='Done')
    async def collect():
        response = await submit_task_stream(TaskRequest(task='work',task_id='a',session_id='chat'))
        return ''.join([chunk async for chunk in response.body_iterator])
    wire = asyncio.run(collect())
    assert wire.count('"type": "task_result"') == 1
    assert wire.index('"type": "text"') < wire.index('"type": "task_result"') < wire.index('[DONE]')


@pytest.mark.parametrize('state', ['partial', 'blocked', 'cancelled'])
def test_terminal_status_is_preserved(state):
    assert build_result('a',state,'some work','',[]).status == state
