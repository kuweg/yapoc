"""SQLite persistence layer — single DB at data/yapoc.db.

All writes go through helpers in this module. Tables:
- tasks          — completed task history (survives TASK.MD overwrite)
- task_queue     — async task lifecycle (pending → running → done/error/timeout)
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

import json

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
        CREATE TABLE IF NOT EXISTS task_events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_task_events ON task_events(task_id, seq);

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
            error_summary   TEXT,
            cost_usd        REAL NOT NULL DEFAULT 0.0,
            continuation    INTEGER NOT NULL DEFAULT 0,
            changed_files   TEXT NOT NULL DEFAULT '',
            checkpoint_sha  TEXT NOT NULL DEFAULT '',
            verification    TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(agent, status);
        CREATE INDEX IF NOT EXISTS idx_tasks_time  ON tasks(assigned_at DESC);

        CREATE TABLE IF NOT EXISTS memory_entries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            agent       TEXT NOT NULL,
            source      TEXT NOT NULL,
            content     TEXT NOT NULL,
            timestamp   TEXT NOT NULL,
            embedding   BLOB,
            tier        TEXT NOT NULL DEFAULT 'hot',
            provenance  TEXT NOT NULL DEFAULT '',
            layer       TEXT NOT NULL DEFAULT 'episodic'
        );
        CREATE INDEX IF NOT EXISTS idx_mem_agent  ON memory_entries(agent);
        CREATE INDEX IF NOT EXISTS idx_mem_source ON memory_entries(agent, source);
        CREATE INDEX IF NOT EXISTS idx_mem_time   ON memory_entries(timestamp DESC);

        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
            content,
            content_rowid='id',
            tokenize='porter unicode61'
        );

        CREATE TABLE IF NOT EXISTS task_results (result_key TEXT PRIMARY KEY, payload TEXT NOT NULL);

        CREATE TABLE IF NOT EXISTS task_queue (
            id              TEXT PRIMARY KEY,
            prompt          TEXT NOT NULL,
            source          TEXT DEFAULT 'ui',
            session_id      TEXT,
            status          TEXT DEFAULT 'pending',
            assigned_agent  TEXT,
            result          TEXT,
            error           TEXT,
            cost_usd        REAL DEFAULT 0.0,
            created_at      TEXT NOT NULL,
            started_at      TEXT,
            completed_at    TEXT,
            updated_at      TEXT NOT NULL,
            metadata        TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_tq_status  ON task_queue(status);
        CREATE INDEX IF NOT EXISTS idx_tq_session ON task_queue(session_id);

        CREATE TABLE IF NOT EXISTS index_checkpoints (
            agent        TEXT NOT NULL,
            source       TEXT NOT NULL,
            last_line    INTEGER NOT NULL DEFAULT 0,
            content_hash TEXT NOT NULL DEFAULT '',
            updated_at   TEXT NOT NULL,
            PRIMARY KEY (agent, source)
        );
    """)
    # Additive migrations for databases created before these columns existed.
    # SQLite lacks ADD COLUMN IF NOT EXISTS, so duplicate-column errors are safe.
    for statement in (
        "ALTER TABLE index_checkpoints ADD COLUMN content_hash TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE memory_entries ADD COLUMN tier TEXT NOT NULL DEFAULT 'hot'",
        "ALTER TABLE memory_entries ADD COLUMN provenance TEXT NOT NULL DEFAULT ''",
        # Typed memory layer (roadmap 3.1). Separate from `tier`, which stays
        # the retrieval-visibility flag: tier answers "is this searchable now",
        # layer answers "what kind of memory is this". Overloading tier would
        # have silently changed what every `tier='hot'` query returns.
        "ALTER TABLE memory_entries ADD COLUMN layer TEXT NOT NULL DEFAULT 'episodic'",
        # Per-agent-task cost. An agent runs one task at a time, so the delta of
        # its USAGE.json across the task is exactly that task's spend — unlike
        # task_queue.cost_usd, which spans a whole delegation tree.
        "ALTER TABLE tasks ADD COLUMN cost_usd REAL NOT NULL DEFAULT 0.0",
        # Which continuation attempt this row is (0 = the original run).
        "ALTER TABLE tasks ADD COLUMN continuation INTEGER NOT NULL DEFAULT 0",
        # Verification gate (roadmap 2.5): what a modifying task actually
        # touched, and the checkpoint it can be rolled back to.
        "ALTER TABLE tasks ADD COLUMN changed_files TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE tasks ADD COLUMN checkpoint_sha TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE tasks ADD COLUMN verification TEXT NOT NULL DEFAULT ''",
    ):
        try:
            db.execute(statement)
            db.commit()
        except sqlite3.OperationalError:
            pass  # column already exists
    db.execute("CREATE INDEX IF NOT EXISTS idx_mem_tier ON memory_entries(tier)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_mem_layer ON memory_entries(layer)")

    db.execute("""
        CREATE TABLE IF NOT EXISTS indexer_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    db.commit()


# ── Indexer state helpers ────────────────────────────────────────────────


def get_indexer_counter() -> int:
    """Read the indexer turn_counter. Returns 0 if not yet set."""
    db = get_db()
    row = db.execute(
        "SELECT value FROM indexer_state WHERE key = 'turn_counter'"
    ).fetchone()
    return int(row["value"]) if row else 0


def increment_indexer_counter() -> int:
    """Atomically increment the turn_counter. Returns the new value."""
    db = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    current = get_indexer_counter()
    new_val = current + 1
    db.execute(
        """INSERT INTO indexer_state (key, value, updated_at)
           VALUES ('turn_counter', ?, ?)
           ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?""",
        (str(new_val), now, str(new_val), now),
    )
    db.commit()
    return new_val


def get_seen_sessions() -> set[str]:
    """Read the set of seen session IDs from indexer_state."""
    db = get_db()
    row = db.execute(
        "SELECT value FROM indexer_state WHERE key = 'seen_sessions'"
    ).fetchone()
    if not row:
        return set()
    try:
        return set(json.loads(row["value"]))
    except (json.JSONDecodeError, TypeError):
        return set()


def is_new_session(session_id: str) -> bool:
    """Check if session_id has been seen before. If new, adds it and persists.

    Returns True if session_id is new (was not in seen_sessions before).
    """
    if not session_id:
        return False
    seen = get_seen_sessions()
    if session_id in seen:
        return False
    seen.add(session_id)
    db = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.execute(
        """INSERT INTO indexer_state (key, value, updated_at)
           VALUES ('seen_sessions', ?, ?)
           ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?""",
        (json.dumps(list(seen)), now, json.dumps(list(seen)), now),
    )
    db.commit()
    return True


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
    cost_usd: float = 0.0,
    continuation: int = 0,
    changed_files: str = "",
    checkpoint_sha: str = "",
    verification: str = "",
) -> int:
    """Insert a completed task record. Returns the row id."""
    db = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = db.execute(
        """INSERT INTO tasks
           (agent, task_id, status, assigned_by, assigned_at, completed_at,
            task_summary, result_summary, error_summary, cost_usd, continuation,
            changed_files, checkpoint_sha, verification)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            agent,
            task_id,
            status,
            assigned_by,
            assigned_at or now,
            now,
            task_summary,
            result_summary,
            error_summary,
            float(cost_usd or 0.0),
            int(continuation or 0),
            changed_files or "",
            checkpoint_sha or "",
            verification or "",
        ),
    )
    from app.utils.task_results import save_result
    save_result(db, f'agent:{agent}:{cur.lastrowid}', task_id, status, result_summary, error_summary)
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
    from app.utils.task_results import attach_result
    return [attach_result(db, r, f"agent:{r['agent']}:{r['id']}") for r in rows]


# ── Memory / embedding helpers ────────────────────────────────────────────


def insert_memory_entry(
    *,
    agent: str,
    source: str,
    content: str,
    timestamp: str,
    embedding: np.ndarray | None = None,
    tier: str = "hot",
    provenance: str = "",
    layer: str | None = None,
) -> int:
    """Insert a memory entry with optional embedding. Returns row id.

    ``layer`` is derived from agent/source when not given, so every call site
    gets a typed layer without having to know the taxonomy.
    """
    db = get_db()
    blob = embedding.astype(np.float32).tobytes() if embedding is not None else None
    if tier not in {"hot", "cold"}:
        raise ValueError("tier must be 'hot' or 'cold'")
    if layer is None:
        from app.utils.memory_layers import classify_layer
        layer = classify_layer(agent, source, content, tier)
    cur = db.execute(
        """INSERT INTO memory_entries
           (agent, source, content, timestamp, embedding, tier, provenance, layer)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (agent, source, content, timestamp, blob, tier, provenance, layer),
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


def search_fts(
    query: str,
    agent: str | None = None,
    limit: int = 20,
    include_cold: bool = False,
) -> list[dict[str, Any]]:
    """Full-text keyword search via FTS5. Returns memory_entries rows."""
    db = get_db()
    conditions = ["memory_fts MATCH ?"]
    params: list[Any] = [query]
    if agent:
        conditions.append("m.agent = ?")
        params.append(agent)
    if not include_cold:
        conditions.append("m.tier = 'hot'")
    params.append(limit)
    rows = db.execute(
        """SELECT m.*, rank
           FROM memory_fts f
           JOIN memory_entries m ON m.id = f.rowid
           WHERE """ + " AND ".join(conditions) + " ORDER BY rank LIMIT ?",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def search_vector(
    query_embedding: np.ndarray,
    agent: str | None = None,
    limit: int = 20,
    include_cold: bool = False,
) -> list[tuple[dict[str, Any], float]]:
    """Brute-force cosine similarity search over stored embeddings.

    Returns list of (row_dict, similarity_score) sorted desc.
    """
    db = get_db()
    conditions = ["embedding IS NOT NULL"]
    params: list[Any] = []
    if agent:
        conditions.append("agent = ?")
        params.append(agent)
    if not include_cold:
        conditions.append("tier = 'hot'")
    rows = db.execute(
        "SELECT * FROM memory_entries WHERE " + " AND ".join(conditions),
        params,
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


# ── Task queue helpers (async fire-and-forget lifecycle) ──────────────────


def create_queued_task(
    *,
    id: str,
    prompt: str,
    source: str = "ui",
    session_id: str | None = None,
    metadata: str | None = None,
) -> dict[str, Any]:
    """Insert a new task into the queue. Returns the row as dict."""
    db = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.execute(
        """INSERT INTO task_queue
           (id, prompt, source, session_id, status, created_at, updated_at, metadata)
           VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)""",
        (id, prompt, source, session_id, now, now, metadata),
    )
    db.commit()
    return get_queued_task(id)  # type: ignore[return-value]


def get_queued_task(task_id: str) -> dict[str, Any] | None:
    """Fetch a single task from the queue by id."""
    db = get_db()
    row = db.execute("SELECT * FROM task_queue WHERE id = ?", (task_id,)).fetchone()
    from app.utils.task_results import attach_result
    return attach_result(db, row, task_id) if row else None


def update_queued_task(task_id: str, **fields: Any) -> dict[str, Any] | None:
    """Update one or more fields on a queued task. Returns updated row."""
    if not fields:
        return get_queued_task(task_id)
    db = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fields["updated_at"] = now
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [task_id]
    db.execute(f"UPDATE task_queue SET {set_clause} WHERE id = ?", vals)
    row = db.execute('SELECT * FROM task_queue WHERE id=?', (task_id,)).fetchone()
    if row and row['status'] in {'done', 'error', 'timeout', 'cancelled', 'blocked', 'failed'}:
        from app.utils.task_results import save_result
        save_result(db, task_id, task_id, row['status'], row['result'], row['error'])
    db.commit()
    return get_queued_task(task_id)


def get_tasks_by_status(*statuses: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch tasks filtered by one or more statuses, newest first."""
    db = get_db()
    placeholders = ", ".join("?" for _ in statuses)
    rows = db.execute(
        f"SELECT * FROM task_queue WHERE status IN ({placeholders}) ORDER BY created_at DESC LIMIT ?",
        (*statuses, limit),
    ).fetchall()
    from app.utils.task_results import attach_result
    return [attach_result(db, r, r['id']) for r in rows]


def clear_session_tasks(session_id: str, source: str = "telegram") -> int:
    """Delete all task_queue rows for a given session+source. Returns count deleted."""
    db = get_db()
    cur = db.execute(
        "DELETE FROM task_queue WHERE session_id = ? AND source = ?",
        (session_id, source),
    )
    db.commit()
    return cur.rowcount


def session_tasks_queue(session_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Recent runs owned by this conversation, independent of global activity."""
    rows = get_db().execute(
        "SELECT * FROM task_queue WHERE session_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    from app.utils.task_results import attach_result
    return [attach_result(get_db(), row, row['id']) for row in rows]


def recent_tasks_queue(limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
    """Return recent task_queue entries, newest first. Optional status filter."""
    db = get_db()
    if status:
        rows = db.execute(
            "SELECT * FROM task_queue WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM task_queue ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    from app.utils.task_results import attach_result
    return [attach_result(db, r, r['id']) for r in rows]


def search_hybrid(
    query: str,
    query_embedding: np.ndarray | None,
    agent: str | None = None,
    top_k: int = 10,
    include_cold: bool = False,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion of FTS5 keyword + cosine vector results.

    Inspired by Friday's hybrid search pattern. RRF formula:
        score(doc) = sum(1 / (k + rank_i)) across all rankers
    where k = 60 (standard constant).
    """
    K = 60  # RRF constant

    # Keyword results (agent-filtered when specified)
    fts_results = search_fts(
        query, agent=agent, limit=top_k * 3, include_cold=include_cold
    )
    # Vector results
    vec_results = search_vector(
        query_embedding, agent=agent, limit=top_k * 3, include_cold=include_cold
    ) if query_embedding is not None else []

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
