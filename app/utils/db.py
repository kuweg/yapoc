"""SQLite persistence layer — single DB at data/yapoc.db.

All writes go through helpers in this module. Tables:
- tasks          — completed task history (survives TASK.MD overwrite)
- memory_entries — text + embedding for semantic search
- memory_fts     — FTS5 virtual table for keyword search

Usage:
    from app.utils.db import get_db, init_schema, insert_task, search_hybrid
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.config import settings

_DB_PATH: Path | None = None
_local = threading.local()


def _db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = settings.project_root / "data" / "yapoc.db"
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _DB_PATH


def get_db() -> sqlite3.Connection:
    """Return a thread-local SQLite connection (one per thread)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(_db_path()), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn = conn
    return conn


def init_schema() -> None:
    """Create tables if they don't exist. Safe to call multiple times."""
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            agent           TEXT NOT NULL,
            task_id         TEXT,
            status          TEXT NOT NULL,
            assigned_by     TEXT,
            assigned_at     TEXT,
            completed_at    TEXT,
            task_summary    TEXT,
            result_summary  TEXT,
            error_summary   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(agent, status);
        CREATE INDEX IF NOT EXISTS idx_tasks_time  ON tasks(assigned_at DESC);

        CREATE TABLE IF NOT EXISTS memory_entries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            agent       TEXT NOT NULL,
            source      TEXT NOT NULL,
            content     TEXT NOT NULL,
            timestamp   TEXT NOT NULL,
            embedding   BLOB
        );
        CREATE INDEX IF NOT EXISTS idx_mem_agent  ON memory_entries(agent);
        CREATE INDEX IF NOT EXISTS idx_mem_source ON memory_entries(agent, source);
        CREATE INDEX IF NOT EXISTS idx_mem_time   ON memory_entries(timestamp DESC);

        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
            content,
            content_rowid='id',
            tokenize='porter unicode61'
        );

        CREATE TABLE IF NOT EXISTS index_checkpoints (
            agent        TEXT NOT NULL,
            source       TEXT NOT NULL,
            last_line    INTEGER NOT NULL DEFAULT 0,
            content_hash TEXT NOT NULL DEFAULT '',
            updated_at   TEXT NOT NULL,
            PRIMARY KEY (agent, source)
        );
    """)
    # Migration: add content_hash column to existing DBs
    try:
        db.execute("ALTER TABLE index_checkpoints ADD COLUMN content_hash TEXT NOT NULL DEFAULT ''")
        db.commit()
    except Exception:
        pass  # column already exists
    db.commit()


# ── Task history helpers ──────────────────────────────────────────────────


def insert_task(
    *,
    agent: str,
    task_id: str = "",
    status: str,
    assigned_by: str = "",
    assigned_at: str = "",
    task_summary: str = "",
    result_summary: str = "",
    error_summary: str = "",
) -> int:
    """Insert a completed task record. Returns the row id."""
    db = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = db.execute(
        """INSERT INTO tasks
           (agent, task_id, status, assigned_by, assigned_at, completed_at,
            task_summary, result_summary, error_summary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            agent,
            task_id,
            status,
            assigned_by,
            assigned_at or now,
            now,
            task_summary[:500],
            result_summary[:2000],
            error_summary[:2000],
        ),
    )
    db.commit()
    return cur.lastrowid


def recent_tasks(agent: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent task records, newest first."""
    db = get_db()
    if agent:
        rows = db.execute(
            "SELECT * FROM tasks WHERE agent = ? ORDER BY id DESC LIMIT ?",
            (agent, limit),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Memory / embedding helpers ────────────────────────────────────────────


def insert_memory_entry(
    *,
    agent: str,
    source: str,
    content: str,
    timestamp: str,
    embedding: np.ndarray | None = None,
) -> int:
    """Insert a memory entry with optional embedding. Returns row id."""
    db = get_db()
    blob = embedding.astype(np.float32).tobytes() if embedding is not None else None
    cur = db.execute(
        "INSERT INTO memory_entries (agent, source, content, timestamp, embedding) VALUES (?, ?, ?, ?, ?)",
        (agent, source, content, timestamp, blob),
    )
    rowid = cur.lastrowid
    # Keep FTS5 in sync
    db.execute(
        "INSERT INTO memory_fts (rowid, content) VALUES (?, ?)",
        (rowid, content),
    )
    db.commit()
    return rowid


def get_checkpoint(agent: str, source: str) -> int:
    """Return last indexed line number for an agent+source pair."""
    db = get_db()
    row = db.execute(
        "SELECT last_line FROM index_checkpoints WHERE agent = ? AND source = ?",
        (agent, source),
    ).fetchone()
    return row["last_line"] if row else 0


def set_checkpoint(agent: str, source: str, last_line: int) -> None:
    """Update the indexing checkpoint."""
    db = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.execute(
        """INSERT INTO index_checkpoints (agent, source, last_line, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(agent, source) DO UPDATE SET last_line = ?, updated_at = ?""",
        (agent, source, last_line, now, last_line, now),
    )
    db.commit()


def get_checkpoint_hash(agent: str, source: str) -> str:
    """Return the stored content hash for an agent+source pair (empty string if none)."""
    db = get_db()
    row = db.execute(
        "SELECT content_hash FROM index_checkpoints WHERE agent = ? AND source = ?",
        (agent, source),
    ).fetchone()
    return row["content_hash"] if row else ""


def set_checkpoint_hash(agent: str, source: str, content_hash: str) -> None:
    """Upsert the content hash checkpoint for an agent+source pair."""
    db = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.execute(
        """INSERT INTO index_checkpoints (agent, source, last_line, content_hash, updated_at)
           VALUES (?, ?, 0, ?, ?)
           ON CONFLICT(agent, source) DO UPDATE SET content_hash = ?, updated_at = ?""",
        (agent, source, content_hash, now, content_hash, now),
    )
    db.commit()


def delete_agent_source_entries(agent: str, source: str) -> int:
    """Delete all memory entries for an agent+source pair. Returns count deleted."""
    db = get_db()
    rows = db.execute(
        "SELECT id FROM memory_entries WHERE agent = ? AND source = ?",
        (agent, source),
    ).fetchall()
    for row in rows:
        db.execute("DELETE FROM memory_fts WHERE rowid = ?", (row["id"],))
    db.execute(
        "DELETE FROM memory_entries WHERE agent = ? AND source = ?",
        (agent, source),
    )
    db.commit()
    return len(rows)


def search_fts(query: str, agent: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Full-text keyword search via FTS5. Returns memory_entries rows."""
    db = get_db()
    if agent:
        rows = db.execute(
            """SELECT m.*, rank
               FROM memory_fts f
               JOIN memory_entries m ON m.id = f.rowid
               WHERE memory_fts MATCH ? AND m.agent = ?
               ORDER BY rank
               LIMIT ?""",
            (query, agent, limit),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT m.*, rank
               FROM memory_fts f
               JOIN memory_entries m ON m.id = f.rowid
               WHERE memory_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (query, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def search_vector(
    query_embedding: np.ndarray,
    agent: str | None = None,
    limit: int = 20,
) -> list[tuple[dict[str, Any], float]]:
    """Brute-force cosine similarity search over stored embeddings.

    Returns list of (row_dict, similarity_score) sorted desc.
    """
    db = get_db()
    if agent:
        rows = db.execute(
            "SELECT * FROM memory_entries WHERE embedding IS NOT NULL AND agent = ?",
            (agent,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM memory_entries WHERE embedding IS NOT NULL"
        ).fetchall()

    if not rows:
        return []

    q = query_embedding.astype(np.float32)
    q_norm = q / (np.linalg.norm(q) + 1e-10)

    results: list[tuple[dict[str, Any], float]] = []
    for row in rows:
        stored = np.frombuffer(row["embedding"], dtype=np.float32)
        s_norm = stored / (np.linalg.norm(stored) + 1e-10)
        sim = float(np.dot(q_norm, s_norm))
        results.append((dict(row), sim))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:limit]


def search_hybrid(
    query: str,
    query_embedding: np.ndarray,
    agent: str | None = None,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion of FTS5 keyword + cosine vector results.

    Inspired by Friday's hybrid search pattern. RRF formula:
        score(doc) = sum(1 / (k + rank_i)) across all rankers
    where k = 60 (standard constant).
    """
    K = 60  # RRF constant

    # Keyword results (agent-filtered when specified)
    fts_results = search_fts(query, agent=agent, limit=top_k * 3)
    # Vector results
    vec_results = search_vector(query_embedding, agent=agent, limit=top_k * 3)

    # Build RRF scores keyed by memory_entries.id
    rrf_scores: dict[int, float] = {}
    entry_cache: dict[int, dict[str, Any]] = {}

    for rank, row in enumerate(fts_results):
        rid = row["id"]
        rrf_scores[rid] = rrf_scores.get(rid, 0) + 1.0 / (K + rank + 1)
        entry_cache[rid] = row

    for rank, (row, _sim) in enumerate(vec_results):
        rid = row["id"]
        rrf_scores[rid] = rrf_scores.get(rid, 0) + 1.0 / (K + rank + 1)
        entry_cache[rid] = row

    # Sort by combined RRF score
    ranked = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

    results: list[dict[str, Any]] = []
    for rid, score in ranked[:top_k]:
        entry = entry_cache[rid]
        # Remove embedding blob from output
        entry.pop("embedding", None)
        entry["rrf_score"] = round(score, 4)
        results.append(entry)

    return results
