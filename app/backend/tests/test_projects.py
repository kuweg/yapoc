import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.backend.services import projects, notes
from app.backend.routers.projects import router


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(projects, 'settings', SimpleNamespace(project_root=tmp_path))
    monkeypatch.setattr(notes, '_root', lambda: tmp_path / 'notes')
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), tmp_path


def create(client, **changes):
    result = client.post('/projects', json={'name': 'Research', 'brief': 'Use Python', 'sessions': ['s1'], **changes})
    assert result.status_code == 201, result.text
    return result.json()


def test_crud_conflicts_and_non_destructive_delete(env):
    client, root = env
    note = notes.create_note('Keep', 'Keep this content')
    p = create(client, sources=[{'kind': 'note', 'target': note['id'], 'label': 'Keep'}])
    assert client.get('/projects').json() == [p]
    updated = client.put('/projects/'+p['id'], json={**p, 'name': 'Renamed'})
    assert updated.status_code == 200
    assert client.put('/projects/'+p['id'], json=p).status_code == 409
    assert client.delete('/projects/'+p['id'], params={'revision': 1}).status_code == 409
    assert client.delete('/projects/'+p['id'], params={'revision': 2}).status_code == 204
    assert notes.read_note(note['id'])['content'] == 'Keep this content'
    assert client.get('/projects').json() == []
    assert (root/'data/projects.sqlite3').exists()


def test_membership_unique_sources_shared_and_validation(env):
    client, _ = env
    source = {'kind': 'book', 'target': 'book-1', 'label': 'Reference'}
    create(client, sources=[source])
    assert client.post('/projects', json={'name': 'Other', 'sessions': ['s1']}).status_code == 409
    assert client.post('/projects', json={'name': 'Other', 'sources': [source]}).status_code == 201
    for payload in [{'name': ' '}, {'name': 'X', 'sources': [source, source]}, {'name': 'X', 'sources': [{**source, 'always': True}]}, {'name':'X','sources':[{'kind':'link','target':'javascript:alert(1)','label':'bad'}]}]:
        assert client.post('/projects', json=payload).status_code == 422


def test_context_scoping_bounds_exclusion_missing_and_no_network(env):
    client, _ = env
    note = notes.create_note('Context', 'x'*5000)
    p = create(client, sources=[{'kind':'note','target':note['id'],'label':'Context','always':True}, {'kind':'link','target':'https://example.com/book','label':'Reference'}])
    text, metadata = projects.build_context(p['id'], 's1', [])
    assert 'Use Python' in text and 'x'*4000 in text and 'x'*4001 not in text
    assert metadata['revision'] == 1
    text, _ = projects.build_context(p['id'], 's1', ['__brief__', 'note:'+note['id']])
    assert 'Use Python' not in text and 'xxxx' not in text and 'https://example.com/book' in text
    with pytest.raises(HTTPException) as error:
        projects.build_context(p['id'], 'unrelated', [])
    assert error.value.status_code == 409
    notes.trash_note(note['id'], note['revision'])
    with pytest.raises(HTTPException) as error:
        projects.build_context(p['id'], 's1', [])
    assert error.value.status_code == 409
    assert projects.build_context(None, None, []) == ('', None)


@pytest.mark.parametrize('endpoint', ['/task', '/task/stream'])
def test_task_snapshots_project_context_and_replay_survives_deletion(env, monkeypatch, endpoint):
    client, _ = env
    p = create(client)
    from app.backend.routers import tasks
    from app.backend.services import task_runtime
    rows = {}
    def enqueue(**kwargs):
        rows[kwargs['id']] = {**kwargs, 'status':'done'}
        return rows[kwargs['id']]
    monkeypatch.setattr(tasks, 'create_queued_task', enqueue)
    monkeypatch.setattr(tasks, 'get_queued_task', lambda task_id: rows.get(task_id))
    monkeypatch.setattr(task_runtime, 'read_events', lambda *args: [])
    app = FastAPI(); app.include_router(tasks.router)
    client = TestClient(app)
    payload = {'task':'Think', 'task_id':'project-task', 'session_id':'s1', 'project_id':p['id']}
    assert client.post(endpoint,json=payload).status_code == 200
    row = next(iter(rows.values()))
    assert 'Use Python' in row['prompt']
    assert json.loads(row['metadata'])['project']['id'] == p['id']
    if endpoint.endswith('/stream'):
        projects.delete_project(p['id'],1)
        assert client.post(endpoint,json=payload).status_code == 200
        assert len(rows) == 1
