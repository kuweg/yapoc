"""Tests for app.utils.db — SQLite persistence layer."""

import os
import sqlite3
import numpy as np
import pytest

# Patch settings.project_root before importing db module
from unittest.mock import patch


@pytest.fixture
def db_dir(tmp_path):
    """Provide a temp directory with a data/ subdir and patch settings."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "yapoc.db"

    import app.utils.db as db_mod

    # Reset module-level state
    old_path = db_mod._DB_PATH
    old_local = db_mod._local
    db_mod._DB_PATH = db_path
    db_mod._local = __import__("threading").local()

    yield db_path

    # Cleanup
    db_mod._DB_PATH = old_path
    db_mod._local = old_local


def test_init_schema_creates_tables(db_dir):
    from app.utils.db import init_schema, get_db

    init_schema()
    db = get_db()
    tables = {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        ).fetchall()
    }
    assert "tasks" in tables
    assert "memory_entries" in tables
    assert "memory_fts" in tables
    assert "index_checkpoints" in tables


def test_init_schema_idempotent(db_dir):
    from app.utils.db import init_schema

    init_schema()
    init_schema()  # should not raise


def test_insert_and_recent_tasks(db_dir):
    from app.utils.db import init_schema, insert_task, recent_tasks

    init_schema()
    rowid = insert_task(
        agent="builder",
        status="done",
        task_summary="test task",
        result_summary="it worked",
    )
    assert rowid > 0

    rows = recent_tasks()
    assert len(rows) == 1
    assert rows[0]["agent"] == "builder"
    assert rows[0]["status"] == "done"
    assert rows[0]["task_summary"] == "test task"


def test_recent_tasks_filter_by_agent(db_dir):
    from app.utils.db import init_schema, insert_task, recent_tasks

    init_schema()
    insert_task(agent="builder", status="done", task_summary="a")
    insert_task(agent="planning", status="done", task_summary="b")

    builder_rows = recent_tasks(agent="builder")
    assert len(builder_rows) == 1
    assert builder_rows[0]["agent"] == "builder"

    all_rows = recent_tasks()
    assert len(all_rows) == 2


def test_insert_memory_entry_and_fts(db_dir):
    from app.utils.db import init_schema, insert_memory_entry, search_fts

    init_schema()
    emb = np.random.randn(384).astype(np.float32)
    rowid = insert_memory_entry(
        agent="builder",
        source="MEMORY.MD",
        content="decided to use SQLite for persistence",
        timestamp="2026-04-12 10:00",
        embedding=emb,
    )
    assert rowid > 0

    results = search_fts("SQLite persistence")
    assert len(results) >= 1
    assert results[0]["agent"] == "builder"


def test_search_vector(db_dir):
    from app.utils.db import init_schema, insert_memory_entry, search_vector

    init_schema()
    # Insert two entries with known embeddings
    emb_a = np.zeros(384, dtype=np.float32)
    emb_a[0] = 1.0  # points in dimension 0
    emb_b = np.zeros(384, dtype=np.float32)
    emb_b[1] = 1.0  # points in dimension 1

    insert_memory_entry(
        agent="a", source="MEMORY.MD", content="entry a",
        timestamp="2026-01-01", embedding=emb_a,
    )
    insert_memory_entry(
        agent="b", source="MEMORY.MD", content="entry b",
        timestamp="2026-01-02", embedding=emb_b,
    )

    # Query aligned with entry a
    query = np.zeros(384, dtype=np.float32)
    query[0] = 1.0
    results = search_vector(query)
    assert len(results) == 2
    assert results[0][0]["content"] == "entry a"
    assert results[0][1] > results[1][1]  # a scores higher


def test_search_hybrid(db_dir):
    from app.utils.db import init_schema, insert_memory_entry, search_hybrid

    init_schema()
    emb = np.random.randn(384).astype(np.float32)
    insert_memory_entry(
        agent="builder", source="MEMORY.MD",
        content="authentication middleware was refactored",
        timestamp="2026-04-10", embedding=emb,
    )

    query_emb = np.random.randn(384).astype(np.float32)
    results = search_hybrid("authentication refactored", query_emb, top_k=5)
    assert len(results) >= 1
    assert "authentication" in results[0]["content"]


def test_checkpoint_round_trip(db_dir):
    from app.utils.db import init_schema, get_checkpoint, set_checkpoint

    init_schema()
    assert get_checkpoint("builder", "MEMORY.MD") == 0

    set_checkpoint("builder", "MEMORY.MD", 42)
    assert get_checkpoint("builder", "MEMORY.MD") == 42

    # Update
    set_checkpoint("builder", "MEMORY.MD", 100)
    assert get_checkpoint("builder", "MEMORY.MD") == 100


def test_search_hybrid_agent_filter(db_dir):
    from app.utils.db import init_schema, insert_memory_entry, search_hybrid

    init_schema()
    emb_a = np.random.randn(384).astype(np.float32)
    emb_b = np.random.randn(384).astype(np.float32)
    insert_memory_entry(
        agent="planning", source="MEMORY.MD",
        content="task delegation strategy for the project",
        timestamp="2026-04-10", embedding=emb_a,
    )
    insert_memory_entry(
        agent="builder", source="MEMORY.MD",
        content="task delegation to sub-agent completed",
        timestamp="2026-04-11", embedding=emb_b,
    )

    query_emb = np.random.randn(384).astype(np.float32)
    # Filter to planning only
    results = search_hybrid("task delegation", query_emb, agent="planning", top_k=5)
    for r in results:
        assert r["agent"] == "planning", f"Expected planning, got {r['agent']}"

    # Filter to builder only
    results = search_hybrid("task delegation", query_emb, agent="builder", top_k=5)
    for r in results:
        assert r["agent"] == "builder", f"Expected builder, got {r['agent']}"


def test_task_summary_truncation(db_dir):
    from app.utils.db import init_schema, insert_task, recent_tasks

    init_schema()
    long_summary = "x" * 1000
    insert_task(agent="builder", status="done", task_summary=long_summary)
    rows = recent_tasks()
    assert len(rows[0]["task_summary"]) == 500
