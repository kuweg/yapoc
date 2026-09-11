"""Durable handoff, recovery and diagnostics without credentials or public internet."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from app.config import settings
from app.utils import db
from app.backend.services import task_progress, recovery, runtime_diagnostics


@pytest.fixture
def task_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, '_DB_PATH', tmp_path / 'tasks.db')
    monkeypatch.delattr(db._local, 'conn', raising=False)
    db.init_schema()
    yield
    conn = getattr(db._local, 'conn', None)
    if conn:
        conn.close()
        del db._local.conn


def task(tid, state='pending', meta=None):
    db.create_queued_task(id=tid, prompt='Original work', source='ui', session_id='session', metadata=json.dumps(meta or {}))
    return db.update_queued_task(tid, status=state)


def test_handoff_stays_waiting_until_all_deliveries_finish(task_db):
    row = task('parent', 'done', {'abandoned_waits': ['builder', 'keeper'], 'child_deliveries': {'builder': 'b', 'keeper': 'k'}})
    task('b', 'done')
    task('k', 'running')
    view = task_progress.present_task(row)
    assert view['progress']['state'] == 'waiting'
    assert view['structured_result']['status'] == 'partial'
    db.update_queued_task('k', status='done')
    assert task_progress.progress(row)['state'] == 'completed'
    db.update_queued_task('k', status='error')
    assert task_progress.progress(row)['state'] == 'blocked'


def test_cyclic_delivery_metadata_is_bounded(task_db):
    row = task('cycle', 'done', {'abandoned_waits': ['builder'], 'child_deliveries': {'builder': 'cycle'}})
    assert task_progress.progress(row)['state'] == 'unknown'


def test_recovery_preserves_identity_evidence_and_is_idempotent(task_db, monkeypatch):
    from app.utils import conversation_store
    from app.backend.services.task_runtime import append_event, read_events
    monkeypatch.setattr(conversation_store, 'load', lambda _: 'Retained checkpoint')
    row = task('interrupted', 'interrupted')
    append_event(row['id'], {'type': 'tool_start', 'name': 'file_write', 'input': {'path': 'work.txt'}})
    assert recovery.recover_interrupted_tasks() == ['interrupted']
    result = db.get_queued_task('interrupted')
    assert result['session_id'] == 'session'
    assert result['status'] == 'pending'
    assert 'UNKNOWN outcome' in result['prompt']
    assert 'Retained checkpoint' in result['prompt']
    assert task_progress.metadata(result)['original_prompt'] == 'Original work'
    assert len(read_events('interrupted')) == 2
    assert recovery.recover_interrupted_tasks() == []
    assert task_progress.metadata(db.get_queued_task('interrupted'))['recovery_count'] == 1


def test_recovery_limit_blocks_and_manual_recovery_retains_history(task_db, monkeypatch):
    monkeypatch.setattr(settings, 'restart_recovery_limit', 1)
    monkeypatch.setattr('app.utils.conversation_store.load', lambda _: '')
    task('loop', 'running', {'recovery_count': 1})
    assert recovery.recover_interrupted_tasks() == []
    assert db.get_queued_task('loop')['status'] == 'blocked'
    assert recovery.recover_interrupted_tasks('loop', manual=True) == ['loop']
    meta = task_progress.metadata(db.get_queued_task('loop'))
    assert meta['recovery_count'] == 2 and len(meta['recovery_history']) == 2


def test_corrupt_metadata_does_not_stop_other_recovery(task_db, monkeypatch):
    monkeypatch.setattr('app.utils.conversation_store.load', lambda _: '')
    task('a', 'running')
    db.update_queued_task('a', metadata='{broken')
    task('b', 'running')
    assert set(recovery.recover_interrupted_tasks()) == {'a', 'b'}


async def test_task_api_uses_same_progress_and_scopes_session(task_db):
    from app.backend.routers.tasks import router
    app = FastAPI(); app.include_router(router)
    task('parent', 'done', {'abandoned_waits': ['builder']})
    task('other', 'running')
    db.update_queued_task('other', session_id='different')
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        rows = (await client.get('/tasks', params={'session_id': 'session'})).json()
        assert len(rows) == 1
        single = (await client.get('/tasks/parent')).json()
        assert single['progress'] == rows[0]['progress']
        assert (await client.post('/tasks/other/recover')).status_code == 409


async def test_diagnostics_use_tools_and_never_return_raw_errors(task_db, monkeypatch):
    python = AsyncMock(return_value='YAPOC_PROBE_OK')
    shell = AsyncMock(return_value='synthetic-secret raw error')
    monkeypatch.setattr(runtime_diagnostics.ExecuteCodeTool, 'execute', python)
    monkeypatch.setattr(runtime_diagnostics.ShellExecTool, 'execute', shell)
    monkeypatch.setattr(runtime_diagnostics, 'snapshot', lambda: {'last_check': runtime_diagnostics._last_result})
    result = await runtime_diagnostics.run_checks()
    assert python.await_count == 5 and shell.await_count == 1
    assert 'synthetic-secret' not in json.dumps(result)
    assert result['last_check']['status'] == 'degraded'
    assert next(c for c in result['last_check']['checks'] if c['name'] == 'poetry')['status'] == 'failed'


async def test_diagnostics_exceptions_are_nonfatal(task_db, monkeypatch):
    monkeypatch.setattr(runtime_diagnostics.ExecuteCodeTool, 'execute', AsyncMock(side_effect=RuntimeError('synthetic-secret')))
    monkeypatch.setattr(runtime_diagnostics.ShellExecTool, 'execute', AsyncMock(side_effect=RuntimeError('synthetic-secret')))
    monkeypatch.setattr(runtime_diagnostics, 'snapshot', lambda: {'last_check': runtime_diagnostics._last_result})
    result = await runtime_diagnostics.run_checks()
    assert 'synthetic-secret' not in json.dumps(result)
    assert result['last_check']['status'] == 'degraded'


async def test_wait_returns_quickly_without_cancelling_child(tmp_path, monkeypatch):
    from app.utils.tools import delegation
    path = tmp_path / 'TASK.MD'
    path.write_text('---\nstatus: running\ntask_id: child\n---\n')
    monkeypatch.setattr(settings, 'master_wait_timeout', 1)
    monkeypatch.setattr(delegation, '_task_path', lambda _: path)
    monkeypatch.setattr(delegation, '_read_status', lambda _: {'state': 'running'})
    monkeypatch.setattr(delegation, '_publish_wait_heartbeat', AsyncMock())
    # A requested 30-second poll must not exceed master's one-second wait cap.
    async with asyncio.timeout(2):
        result = await delegation.WaitForAgentTool().execute(agent_name='builder', timeout=900, poll_interval=30)
    assert 'STILL RUNNING' in result
    assert 'status: running' in path.read_text()


def test_recovery_does_not_duplicate_a_surviving_worker(task_db, monkeypatch):
    task('survivor', 'interrupted')
    monkeypatch.setattr(recovery, 'has_live_child', lambda _: True)
    assert recovery.recover_interrupted_tasks() == []
    assert db.get_queued_task('survivor')['status'] == 'blocked'


def test_reconcile_delivery_link_after_insert_crash(task_db):
    from app.backend.services.notification_delivery import _link_delivery
    row = task('parent', 'done', {'abandoned_waits': ['builder']})
    task('delivery', 'done')
    _link_delivery({'parent_task_id': 'parent', 'child_agent': 'builder', 'status': 'done'}, 'delivery')
    assert task_progress.progress(db.get_queued_task('parent'))['state'] == 'completed'
    # Repeated reconciliation is harmless, but a failed child must not look successful.
    _link_delivery({'parent_task_id': 'parent', 'child_agent': 'builder', 'status': 'error'}, 'delivery')
    assert task_progress.progress(db.get_queued_task('parent'))['state'] == 'blocked'


@pytest.mark.parametrize('child_state,expected', [('done', 'completed'), ('error', 'blocked'), ('running', 'waiting')])
def test_matching_child_run_status(task_db, tmp_path, monkeypatch, child_state, expected):
    monkeypatch.setattr(task_progress, 'settings', SimpleNamespace(agents_dir=tmp_path))
    agent = tmp_path / 'builder'
    agent.mkdir()
    (agent / 'TASK.MD').write_text(f'---\ntask_id: child\nstatus: {child_state}\n---\n')
    (agent / 'STATUS.json').write_text(json.dumps({'state': 'running'}))
    row = task('parent', 'done', {'abandoned_waits': ['builder'], 'waiting_tasks': {'builder': 'child'}})
    assert task_progress.progress(row)['state'] == expected


def test_old_handoff_does_not_use_another_builder_run(task_db, tmp_path, monkeypatch):
    monkeypatch.setattr(task_progress, 'settings', SimpleNamespace(agents_dir=tmp_path))
    agent = tmp_path / 'builder'
    agent.mkdir()
    (agent / 'TASK.MD').write_text('---\ntask_id: newer\nstatus: running\n---\n')
    (agent / 'STATUS.json').write_text('{"state":"running"}')
    row = task('parent', 'done', {'abandoned_waits': ['builder'], 'waiting_tasks': {'builder': 'older'}})
    view = task_progress.progress(row)
    assert view['state'] == 'unknown' and view['waiting_on'] == []


def test_stopped_child_is_not_reported_as_waiting(task_db, tmp_path, monkeypatch):
    monkeypatch.setattr(task_progress, 'settings', SimpleNamespace(agents_dir=tmp_path))
    agent = tmp_path / 'builder'
    agent.mkdir()
    (agent / 'TASK.MD').write_text('---\ntask_id: child\nstatus: running\n---\n')
    (agent / 'STATUS.json').write_text('{"state":"idle"}')
    row = task('parent', 'done', {'abandoned_waits': ['builder'], 'waiting_tasks': {'builder': 'child'}})
    assert task_progress.progress(row)['state'] == 'unknown'
