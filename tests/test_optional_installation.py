"""Core-only behavior and the credential stages of interactive setup."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import tomllib

import numpy as np
import pytest
from app.utils import embeddings, db


def test_heavy_capabilities_are_extras():
    project = tomllib.loads((Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text())['project']
    core = ' '.join(project['dependencies'])
    for dependency in ('sentence-transformers', 'ipykernel', 'pyttsx3'):
        assert dependency not in core
    assert set(project['optional-dependencies']) == {'embeddings', 'notebooks', 'voice'}


@pytest.fixture
def memory_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, '_DB_PATH', tmp_path / 'core.db')
    monkeypatch.delattr(db._local, 'conn', raising=False)
    db.init_schema()
    yield
    db._local.conn.close()
    del db._local.conn


def test_core_indexes_and_searches_without_model(memory_db, monkeypatch):
    monkeypatch.setattr(embeddings, 'embeddings_available', lambda: False)
    model = Mock(side_effect=AssertionError('Core must not load a model'))
    monkeypatch.setattr(embeddings, '_get_model', model)
    texts = ['The project uses a configurable GitHub integration', 'Telegram pairing is optional']
    for text, vector in zip(texts, embeddings.embed_batch_optional(texts)):
        assert vector is None
        db.insert_memory_entry(agent='master', source='fixture', content=text, timestamp='now', embedding=vector)
    results = db.search_hybrid('GitHub', embeddings.embed_optional('GitHub'), agent='master')
    assert len(results) == 1 and 'GitHub' in results[0]['content']
    model.assert_not_called()


def test_backfill_preserves_existing_vectors_and_rows(memory_db, monkeypatch):
    monkeypatch.setattr(embeddings, 'embeddings_available', lambda: True)
    monkeypatch.setattr(embeddings, 'embed_batch', lambda texts: np.ones((len(texts),384), dtype=np.float32))
    db.insert_memory_entry(agent='master', source='fixture', content='unembedded', timestamp='now')
    db.insert_memory_entry(agent='master', source='fixture', content='existing', timestamp='now', embedding=np.zeros(384, dtype=np.float32))
    assert embeddings.backfill_embeddings(1) == 1
    assert embeddings.backfill_embeddings(1) == 0
    assert db.get_db().execute('SELECT COUNT(*) FROM memory_entries').fetchone()[0] == 2


@pytest.mark.parametrize('telegram_choice', [False, True])
def test_guided_provider_then_optional_telegram(tmp_path, monkeypatch, telegram_choice):
    from app.cli import guided_setup as setup
    (tmp_path / '.yapoc-install.json').write_text('{"format":1}')
    monkeypatch.setattr(setup, 'settings', SimpleNamespace(project_root=tmp_path))
    events = []
    selections = iter(['anthropic', 'Skip Telegram'])
    monkeypatch.setattr(setup.questionary, 'select', lambda *a, **k: SimpleNamespace(ask=lambda: next(selections)))
    monkeypatch.setattr(setup.questionary, 'confirm', lambda *a, **k: SimpleNamespace(ask=lambda: events.append('telegram') or telegram_choice))
    monkeypatch.setattr(setup.questionary, 'password', lambda *a, **k: SimpleNamespace(ask=lambda: ''))
    monkeypatch.setattr(setup, '_collect_credentials', lambda provider: (events.append('provider/key') or ('synthetic-key', '')))
    monkeypatch.setattr(setup, '_validate_loop', lambda *a, **k: 'synthetic-key')
    monkeypatch.setattr(setup, '_pick_model', lambda provider: 'fixture-model')
    monkeypatch.setattr(setup, 'configure_agents', Mock())
    monkeypatch.setattr(setup, '_ensure_data_dirs', Mock())
    write = Mock(); monkeypatch.setattr(setup, '_write_env', write)
    pair = Mock(side_effect=AssertionError('Skipped Telegram must not make API calls'))
    monkeypatch.setattr(setup, 'pair_telegram', pair)
    assert setup.run_guided_setup() == 0
    assert events == ['provider/key', 'telegram']
    assert write.call_args.args[-1]['TELEGRAM_BOT_TOKEN'] == ''
    pair.assert_not_called()


def test_api_key_prompt_is_masked(monkeypatch):
    from app.cli import init_wizard
    prompt = Mock(return_value=SimpleNamespace(ask=lambda: 'synthetic-key'))
    monkeypatch.setattr(init_wizard.questionary, 'password', prompt)
    assert init_wizard._collect_credentials('anthropic') == ('synthetic-key', '')
    prompt.assert_called_once()
