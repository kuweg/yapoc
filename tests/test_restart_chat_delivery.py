"""Restart ownership regression: exercise the real factory and startup handoff."""
import ast
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from loguru import logger

from app.backend import dispatcher
from app.backend.message_bus import bus
from app.backend.services import task_runtime
from app.backend.services.graph_events import graph_event_bus
from app.backend.websocket import WebSocketManager, ws_manager
from app.utils import conversation_store, db
from app.utils.adapters import TextDelta
from app.utils.tools import build_tools
from app.utils.tools import server


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    monkeypatch.setattr(db, 'get_db', lambda: conn)
    monkeypatch.setattr(task_runtime, 'get_db', lambda: conn)
    db.init_schema()
    agents = tmp_path / 'agents'
    (agents / 'master').mkdir(parents=True)
    # `managed_restart` must be present: server.restart_server() reads it to
    # decide whether the installer supervisor owns process replacement. It was
    # added to the real Settings after this stub was written, so the stub went
    # stale and every run died with AttributeError before reaching any assert.
    settings = SimpleNamespace(agents_dir=agents, project_root=tmp_path, host='127.0.0.1',
                               port=8000, managed_restart=False)
    monkeypatch.setattr(server, 'settings', settings)
    monkeypatch.setattr(server, '_RESUME_FILE', agents / 'master' / 'RESUME.MD')
    monkeypatch.setattr(server, '_PID_FILE', tmp_path / 'pid')
    server._PID_FILE.write_text(str(os.getpid()))
    monkeypatch.setattr(conversation_store, 'CONVERSATION_ROOT', tmp_path / 'conversations')
    monkeypatch.setattr(server, '_notify_agents_pre_shutdown', AsyncMock())
    monkeypatch.setattr(server, '_schedule_deferred_restart', Mock())
    monkeypatch.setattr(ws_manager, 'push_event', AsyncMock())
    monkeypatch.setattr(graph_event_bus, 'emit_task_assigned', AsyncMock())
    monkeypatch.setattr(bus, 'publish', AsyncMock())
    monkeypatch.setattr(db, 'increment_indexer_counter', lambda: 1)
    yield settings
    conn.close()


def startup_resume(settings):
    # Execute the actual startup function without the production lifespan's
    # schedulers, Telegram, Redis connections or agent processes.
    tree = ast.parse(Path('app/backend/main.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_startup_resume')
    scope = dict(settings=settings, datetime=datetime, timezone=timezone, json=json, re=re, logger=logger)
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'startup_resume', 'exec'), scope)
    return scope['_startup_resume']


@pytest.mark.asyncio
async def test_factory_restart_startup_dispatch_and_session_replay(isolated):
    owner = 'chat-a'
    db.create_queued_task(id='original', prompt='Restart and give the forecast', session_id=owner)
    restart = build_tools(['server_restart'], isolated.agents_dir / 'master', session_id=owner)[0]
    # This assertion catches the actual bug: the helper's direct tests passed
    # while the production tool factory silently omitted the session argument.
    assert restart._session_id == owner
    token = task_runtime.current_task_id.set('original')
    try:
        await restart.execute(next_action='Show the forecast after restart')
    finally:
        task_runtime.current_task_id.reset(token)
    saved = server._RESUME_FILE.read_text()
    assert 'session_id: "chat-a"' in saved
    assert 'origin_task_id: original' in saved
    await startup_resume(isolated)()
    resumed = next(row for row in db.get_tasks_by_status('pending') if row['source'] == 'resume')
    assert resumed['session_id'] == owner
    assert json.loads(resumed['metadata'])['origin_task_id'] == 'original'
    assert db.get_queued_task('original')['status'] == 'superseded'

    async def completed(**kwargs):
        assert kwargs['session_id'] == owner
        yield TextDelta('Restart complete. Belgrade forecast is ready.')
    with patch.dict('sys.modules', {'app.agents.master.agent': SimpleNamespace(master_agent=SimpleNamespace(handle_task_stream=completed))}):
        await dispatcher._execute_task(resumed['id'])
    row = db.get_queued_task(resumed['id'])
    assert row['status'] == 'done' and row['session_id'] == owner
    completed_event = next(call.args[1] for call in ws_manager.push_event.call_args_list if call.args[0] == 'task_complete')
    assert completed_event['session_id'] == owner

    # Bury the completion outside the global 20-task snapshot. Subscribing
    # still recovers the owning conversation and excludes another chat.
    for i in range(25):
        db.create_queued_task(id=f'other-{i}', prompt='other work', session_id='chat-b')
    manager = WebSocketManager()
    socket = Mock(send_text=AsyncMock())
    await manager.subscribe_session(socket, owner)
    snapshot = json.loads(socket.send_text.call_args.args[0])
    assert snapshot['type'] == 'session_sync'
    assert {task['session_id'] for task in snapshot['tasks']} == {owner}
    assert any(task['id'] == resumed['id'] and task['result'] == row['result'] for task in snapshot['tasks'])


@pytest.mark.asyncio
async def test_legacy_restart_file_recovers_explicit_origin_owner(isolated):
    db.create_queued_task(id='original', prompt='user request', session_id='chat-a')
    # Old factory bug wrote no session but did record the originating run.
    server._RESUME_FILE.write_text('---\norigin_task_id: original\nnext_action: "continue"\nsession_id: ""\n---\n')
    await startup_resume(isolated)()
    resumed = next(row for row in db.get_tasks_by_status('pending') if row['source'] == 'resume')
    assert resumed['session_id'] == 'chat-a'


@pytest.mark.asyncio
async def test_save_falls_back_to_current_run_without_guessing_latest_chat(isolated):
    db.create_queued_task(id='original', prompt='request', session_id='chat-a')
    db.create_queued_task(id='newer', prompt='different request', session_id='chat-b')
    token = task_runtime.current_task_id.set('original')
    try:
        saved = await server._save_resume_state(next_action='continue')
    finally:
        task_runtime.current_task_id.reset(token)
    assert 'session_id: "chat-a"' in saved
    saved = await server._save_resume_state(next_action='service work')
    assert 'session_id: ""' in saved


@pytest.mark.asyncio
async def test_sessionless_resume_does_not_invent_a_chat(isolated):
    db.create_queued_task(id='service-resume', prompt='service work', source='resume')
    async def completed(**kwargs):
        assert kwargs['session_id'] == ''
        yield TextDelta('Service recovered')
    with patch.dict('sys.modules', {'app.agents.master.agent': SimpleNamespace(master_agent=SimpleNamespace(handle_task_stream=completed))}):
        await dispatcher._execute_task('service-resume')
    assert db.get_queued_task('service-resume')['session_id'] == ''
