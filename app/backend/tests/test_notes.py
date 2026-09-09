"""File safety, note linking, optimistic saves and durable context injection."""
import json
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.routers.notes import router
from app.backend.services import notes


@pytest.fixture()
def env(monkeypatch, tmp_path):
    root = tmp_path / 'notes'
    monkeypatch.setattr(notes, '_root', lambda: root)
    app = FastAPI()
    app.include_router(router)
    return root, TestClient(app)


def test_create_edit_and_external_edit_conflict(env):
    root, client = env
    created = client.post('/notes', json={'title': 'Project ideas'}).json()
    assert (root / 'Project ideas.md').read_text() == '# Project ideas\n\n'
    assert client.post('/notes', json={'title': 'project IDEAS'}).status_code == 409
    updated = client.put('/notes/Project%20ideas.md', json={'revision': created['revision'], 'content': '# Changed\n[[Roadmap]]'}).json()
    assert updated['links'] == ['Roadmap']
    (root / created['id']).write_text('Edited by an agent', encoding='utf-8')
    response = client.put('/notes/Project%20ideas.md', json={'revision': updated['revision'], 'content': 'Old browser draft'})
    assert response.status_code == 409
    assert (root / created['id']).read_text() == 'Edited by an agent'


@pytest.mark.parametrize('title', ['../outside', '/absolute', 'bad\\name', '.hidden', 'CON', 'bad:name', 'bad\nname', ''])
def test_invalid_names_cannot_escape_or_break_portability(env, title):
    _, client = env
    assert client.post('/notes', json={'title': title}).status_code in (400, 422)


def test_external_markdown_index_and_code_links(env):
    root, client = env
    root.mkdir()
    (root / 'From editor.md').write_text('# Hello\n[[Roadmap#Next|Plan]] [[Roadmap]]\n`[[Inline code]]`\n```md\n[[Example only]]\n```\n', encoding='utf-8')
    row = client.get('/notes').json()['notes'][0]
    assert row['id'] == 'From editor.md'
    assert row['links'] == ['Roadmap']
    assert 'content' not in row


def test_symlinks_and_oversized_files_not_exposed(env, tmp_path):
    root, client = env
    root.mkdir()
    outside = tmp_path / 'outside.md'
    outside.write_text('outside notes')
    (root / 'Unsafe.md').symlink_to(outside)
    (root / 'Large.md').write_text('x' * (notes.MAX_NOTE_BYTES + 1))
    assert client.get('/notes/Unsafe.md').status_code == 400
    assert client.get('/notes/Large.md').status_code == 413
    assert client.get('/notes').json()['notes'] == []
    assert len(client.get('/notes').json()['skipped']) == 2


def test_markdown_note_links_join_graph_but_external_links_and_images_do_not(env):
    _, client = env
    note = client.post('/notes', json={'title': 'Links', 'content': '[Plan](./Roadmap.md#Next) [Work](Deep%20work.md) [External](https://example.com/doc.md) ![Image](Ignored.md)'}).json()
    assert note['links'] == ['Deep work', 'Roadmap']


def test_trash_is_recoverable_and_checks_revision(env):
    root, client = env
    note = client.post('/notes', json={'title': 'Keep recoverable', 'content': 'Important idea'}).json()
    url = '/notes/' + quote(note['id']) + '/trash'
    assert client.post(url, json={'revision': 'stale'}).status_code == 409
    assert client.post(url, json={'revision': note['revision']}).status_code == 200
    assert not (root / note['id']).exists()
    assert next((root / '.trash').glob('*.md')).read_text() == 'Important idea'
    assert client.get('/notes').json()['notes'] == []


def test_context_dedup_latest_content_missing_and_size_limits(env):
    _, client = env
    note = client.post('/notes', json={'title': 'Project ideas', 'content': 'First version'}).json()
    edited = notes.save_note(note['id'], 'Latest version', note['revision'])
    suffix, metadata = notes.build_note_context('Discuss @note:Project%20ideas.md', [note['id']])
    assert suffix.count('Latest version') == 1
    assert metadata[0]['revision'] == edited['revision']
    assert len(metadata) == 1
    with pytest.raises(Exception) as missing:
        notes.build_note_context('Discuss @note:Missing.md')
    assert missing.value.status_code == 404
    notes.save_note(note['id'], 'x' * 65_000, edited['revision'])
    with pytest.raises(Exception) as oversized:
        notes.build_note_context('Discuss', [note['id']])
    assert oversized.value.status_code == 413


@pytest.mark.parametrize('endpoint', ['/task', '/task/stream'])
def test_task_snapshots_note_context_and_stream_replay_reuses_it(env, monkeypatch, endpoint):
    _, client = env
    note = client.post('/notes', json={'title': 'Context', 'content': 'Original reference'}).json()
    from app.backend.routers import tasks
    from app.backend.services import task_runtime
    rows = {}
    def enqueue(**kwargs):
        row = {**kwargs, 'status': 'done'}
        rows[kwargs['id']] = row
        return row
    monkeypatch.setattr(tasks, 'create_queued_task', enqueue)
    monkeypatch.setattr(tasks, 'get_queued_task', lambda task_id: rows.get(task_id))
    monkeypatch.setattr(task_runtime, 'read_events', lambda *args: [])
    app = FastAPI()
    app.include_router(tasks.router)
    task_client = TestClient(app)
    payload = {'task': 'Use my reference', 'note_ids': [note['id']], 'task_id': 'note-task', 'session_id': 'note-session'}
    assert task_client.post(endpoint, json=payload).status_code == 200
    row = next(iter(rows.values()))
    assert 'Original reference' in row['prompt']
    assert json.loads(row['metadata'])['notes'][0]['revision'] == note['revision']
    if endpoint.endswith('/stream'):
        notes.trash_note(note['id'], note['revision'])
        assert task_client.post(endpoint, json=payload).status_code == 200
        assert len(rows) == 1
        assert 'Original reference' in row['prompt']
