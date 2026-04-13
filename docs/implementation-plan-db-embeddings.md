# YAPOC — SQLite + Embedding Search: Implementation & Debug Plan

*Date: 2026-04-12 | Based on: [System Audit](audit-database-embeddings.md) + [Friday Showcase](https://github.com/missingus3r/friday-showcase)*

---

## What This Plan Covers

Three features, in order:

1. **SQLite core** — `app/utils/db.py` with schema init and task history logging
2. **Hybrid search** — FTS5 keyword search + numpy cosine similarity (inspired by Friday's Reciprocal Rank Fusion)
3. **`search_memory` agent tool** — so agents can semantically recall past decisions

**Not covered:** session migration to SQLite (do later), `sqlite-vec` ANN upgrade (do when >100 K entries).

---

## Feature Comparison: Friday vs YAPOC

| Feature | Friday (showcase) | YAPOC (current) | Plan |
|---|---|---|---|
| Database | SQLite for memory | None — all files | SQLite `data/yapoc.db` |
| Embeddings | Auto-embedded in SQLite | None | `sentence-transformers` all-MiniLM-L6-v2 |
| Search | Hybrid: cosine + FTS5 + RRF | None | Same pattern — cosine + FTS5 + RRF |
| Memory API | Flask server on :7777 | MEMORY.MD files | In-process module (no separate server) |
| Vector DB | None (SQLite only) | None | numpy MVP → sqlite-vec later |
| Indexing | Auto-embed on write | Append-only MEMORY.MD | APScheduler background job |
| Agent recall | Endpoint-based retrieval | Last 10 lines of MEMORY.MD | `search_memory` tool |

**Key insight from Friday:** No external vector DB needed. SQLite + FTS5 + numpy cosine is production-sufficient for the entry counts we're dealing with (<100 K).

---

## Step-by-Step Implementation

### Step 1: Add dependencies

**File:** `pyproject.toml`

```bash
poetry add sentence-transformers
```

This pulls in `torch` (CPU), `transformers`, `huggingface-hub`. The `all-MiniLM-L6-v2` model is ~22 MB and auto-downloads on first use.

**Verify:**
```bash
poetry run python -c "from sentence_transformers import SentenceTransformer; m = SentenceTransformer('all-MiniLM-L6-v2'); print(m.encode(['hello']).shape)"
# Expected: (1, 384)
```

**Debug:** If torch install fails on macOS ARM, use `poetry add sentence-transformers --python ">=3.12"`. If model download hangs, set `HF_HUB_OFFLINE=0` and check network.

---

### Step 2: Create `app/utils/db.py`

**New file.** Provides `get_db()`, `init_schema()`, and typed helper functions.

```python
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
            agent       TEXT NOT NULL,
            source      TEXT NOT NULL,
            last_line   INTEGER NOT NULL DEFAULT 0,
            updated_at  TEXT NOT NULL,
            PRIMARY KEY (agent, source)
        );
    """)
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


def search_fts(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Full-text keyword search via FTS5. Returns memory_entries rows."""
    db = get_db()
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

    # Keyword results
    fts_results = search_fts(query, limit=top_k * 3)
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
```

**Verify:**
```bash
poetry run python -c "
from app.utils.db import init_schema, insert_task, recent_tasks, get_db
init_schema()
insert_task(agent='test', status='done', task_summary='hello world')
print(recent_tasks())
import os; os.remove('data/yapoc.db')
"
```

**Debug notes:**
- `PRAGMA journal_mode=WAL` is critical — without it, concurrent readers/writers will get `SQLITE_BUSY`. WAL mode allows readers during writes.
- `PRAGMA synchronous=NORMAL` trades crash safety for speed. Fine for metadata that can be re-derived.
- `content_rowid='id'` in FTS5 keeps the virtual table in sync with `memory_entries` by rowid — but you must INSERT into FTS manually after each `memory_entries` insert. If they go out of sync, run: `INSERT INTO memory_fts(memory_fts) VALUES('rebuild');`
- Thread-local connections: SQLite connections are NOT safe to share across threads. `_local` gives each thread its own.
- The `timeout=5.0` prevents immediate `SQLITE_BUSY` errors — waits up to 5s for the write lock.

---

### Step 3: Create `app/utils/embeddings.py`

**New file.** Lazy-loads sentence-transformers model on first call.

```python
"""Embedding utilities — lazy-loaded sentence-transformers model.

The model (~22 MB, 384-dim) downloads on first use and caches in
~/.cache/huggingface/. All functions are synchronous — call from
a thread or use asyncio.to_thread() in async contexts.

Usage:
    from app.utils.embeddings import embed, embed_batch
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_MODEL_NAME = "all-MiniLM-L6-v2"
_EMBEDDING_DIM = 384


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """Lazy-load the embedding model. Cached after first call."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(_MODEL_NAME)


def embed(text: str) -> np.ndarray:
    """Embed a single text string. Returns shape (384,) float32 array."""
    model = _get_model()
    return model.encode(text, convert_to_numpy=True, show_progress_bar=False)


def embed_batch(texts: list[str], batch_size: int = 64) -> np.ndarray:
    """Embed multiple texts. Returns shape (N, 384) float32 array."""
    if not texts:
        return np.empty((0, _EMBEDDING_DIM), dtype=np.float32)
    model = _get_model()
    return model.encode(texts, batch_size=batch_size, convert_to_numpy=True, show_progress_bar=False)
```

**Verify:**
```bash
poetry run python -c "
from app.utils.embeddings import embed, embed_batch
v = embed('hello world')
print(f'shape: {v.shape}, dtype: {v.dtype}')
vs = embed_batch(['hello', 'world', 'test'])
print(f'batch shape: {vs.shape}')
"
# Expected: shape: (384,), dtype: float32
#           batch shape: (3, 384)
```

**Debug notes:**
- First call takes 2–5 s (model load). All subsequent calls are ~5 ms/sentence. This is why it's `@lru_cache` — load once per process.
- `TYPE_CHECKING` import avoids loading torch at import time — critical for fast CLI startup. The model is only loaded when `embed()` is actually called.
- If `sentence-transformers` import fails at runtime: check `poetry show sentence-transformers` — it must be installed. Common issue: Poetry installs to wrong venv.
- `convert_to_numpy=True` avoids returning torch tensors (which would need `.numpy()` conversion).

---

### Step 4: Create `app/utils/tools/search.py`

**New file.** The `search_memory` tool for agents.

```python
"""Search tool — hybrid semantic + keyword search over agent memory."""

from __future__ import annotations

import asyncio
from typing import Any

from app.utils.tools import BaseTool, RiskTier, truncate_tool_output


class SearchMemoryTool(BaseTool):
    name = "search_memory"
    description = (
        "Search agent memory and history using natural language. "
        "Combines semantic similarity (embeddings) with keyword matching "
        "to find relevant past decisions, task results, and notes. "
        "Returns the most relevant entries across all agents (or a specific one)."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language search query (e.g. 'what was decided about authentication')",
            },
            "agent": {
                "type": "string",
                "description": "Optional: limit search to a specific agent's memory",
                "default": "",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results to return (default 8)",
                "default": 8,
            },
        },
        "required": ["query"],
    }
    risk_tier = RiskTier.AUTO

    async def execute(self, **params: Any) -> str:
        query = params["query"]
        agent = params.get("agent", "") or None
        top_k = params.get("top_k", 8)

        try:
            from app.utils.db import init_schema, search_hybrid, get_db
            from app.utils.embeddings import embed

            init_schema()  # ensure tables exist

            # Check if there are any entries
            db = get_db()
            count = db.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]
            if count == 0:
                return "Memory index is empty. No entries have been indexed yet."

            # Embed query in a thread (blocks ~5ms, but model load can be slow on first call)
            query_vec = await asyncio.to_thread(embed, query)

            results = search_hybrid(query, query_vec, agent=agent, top_k=top_k)

            if not results:
                return f"No results found for query: '{query}'"

            lines: list[str] = [f"Found {len(results)} results for: '{query}'\n"]
            for i, entry in enumerate(results, 1):
                agent_name = entry.get("agent", "?")
                source = entry.get("source", "?")
                ts = entry.get("timestamp", "?")
                content = entry.get("content", "")
                score = entry.get("rrf_score", 0)
                lines.append(
                    f"**{i}. [{agent_name}/{source}] {ts}** (score: {score})\n"
                    f"  {content}\n"
                )

            return truncate_tool_output("\n".join(lines))

        except ImportError:
            return "Error: sentence-transformers not installed. Run: poetry add sentence-transformers"
        except Exception as exc:
            return f"Search error: {exc}"
```

**Verify** (after Steps 5–7 are also done):
```bash
# From the REPL, after some memory has been indexed:
# > search my memory for decisions about agent configuration
```

**Debug notes:**
- `init_schema()` is called defensively — it's idempotent (all `IF NOT EXISTS`). This handles the case where the DB hasn't been created yet when an agent first calls the tool.
- `asyncio.to_thread(embed, query)` runs the embedding in a thread pool so it doesn't block the event loop. The first call is slow (model load); subsequent calls are <10 ms.
- If `search_hybrid` returns empty: the index is empty. Check that Step 6 (indexer) has run.

---

### Step 5: Register the tool

**File:** `app/utils/tools/__init__.py`

**Change 1 — add import** (after the existing import block, around line 192):

```python
from .search import SearchMemoryTool
```

**Change 2 — add to TOOL_REGISTRY** (inside the dict, after `"show_agent_settings"`):

```python
    "search_memory": SearchMemoryTool,
```

No changes needed to `_AGENT_DIR_TOOLS` or `_SANDBOX_TOOLS` — this tool doesn't need `agent_dir` or sandbox.

**Verify:**
```bash
poetry run python -c "from app.utils.tools import TOOL_REGISTRY; print('search_memory' in TOOL_REGISTRY)"
# Expected: True
```

---

### Step 6: Create the indexer — `app/utils/indexer.py`

**New file.** Background job that indexes MEMORY.MD lines into SQLite + embeddings.

```python
"""Background indexer — reads new MEMORY.MD lines and embeds them into SQLite.

Designed to run as an APScheduler job alongside Doctor/ModelManager.
Each agent's MEMORY.MD is tracked via a checkpoint (last indexed line number).
"""

from __future__ import annotations

import re
from pathlib import Path

from loguru import logger as _log

from app.config import settings
from app.utils.db import (
    get_checkpoint,
    init_schema,
    insert_memory_entry,
    set_checkpoint,
)
from app.utils.embeddings import embed_batch

# Agents that should not be indexed (base is a module, not an agent)
_SKIP_DIRS = {"base", "__pycache__"}

# Minimum content length to index (skip near-empty lines)
_MIN_CONTENT_LEN = 20


def _parse_memory_line(line: str) -> tuple[str, str]:
    """Extract timestamp and content from a MEMORY.MD line.

    Format: [YYYY-MM-DD HH:MM] task: ... | result: ...
    Returns (timestamp, full_line_content).
    """
    m = re.match(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]\s*(.+)$", line.strip())
    if m:
        return m.group(1), m.group(2)
    return "", line.strip()


def index_agent_memory(agent_name: str, agent_dir: Path) -> int:
    """Index new MEMORY.MD lines for a single agent. Returns count of new entries."""
    memory_path = agent_dir / "MEMORY.MD"
    if not memory_path.exists():
        return 0

    lines = memory_path.read_text(encoding="utf-8").splitlines()
    checkpoint = get_checkpoint(agent_name, "MEMORY.MD")

    # Only process lines after the checkpoint
    new_lines = lines[checkpoint:]
    if not new_lines:
        return 0

    # Filter out empty/short lines
    entries: list[tuple[str, str, int]] = []  # (timestamp, content, original_index)
    for i, line in enumerate(new_lines):
        line = line.strip()
        if len(line) < _MIN_CONTENT_LEN:
            continue
        ts, content = _parse_memory_line(line)
        if not ts:
            ts = "unknown"
        entries.append((ts, content, checkpoint + i))

    if not entries:
        # Still advance checkpoint even if all lines were too short
        set_checkpoint(agent_name, "MEMORY.MD", len(lines))
        return 0

    # Batch embed all content
    texts = [content for _, content, _ in entries]
    try:
        embeddings = embed_batch(texts)
    except Exception as exc:
        _log.error("Embedding failed for agent {}: {}", agent_name, exc)
        return 0

    # Insert into DB
    count = 0
    for (ts, content, _idx), emb in zip(entries, embeddings):
        try:
            insert_memory_entry(
                agent=agent_name,
                source="MEMORY.MD",
                content=content,
                timestamp=ts,
                embedding=emb,
            )
            count += 1
        except Exception as exc:
            _log.warning("Failed to insert memory entry for {}: {}", agent_name, exc)

    # Update checkpoint to total lines processed
    set_checkpoint(agent_name, "MEMORY.MD", len(lines))
    _log.info("Indexed {} new memory entries for agent '{}'", count, agent_name)
    return count


def run_indexer() -> int:
    """Index all agents' MEMORY.MD files. Returns total entries indexed."""
    init_schema()
    total = 0

    agents_dir = settings.agents_dir
    if not agents_dir.exists():
        return 0

    for agent_dir in sorted(agents_dir.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name in _SKIP_DIRS:
            continue
        try:
            total += index_agent_memory(agent_dir.name, agent_dir)
        except Exception as exc:
            _log.error("Indexer error for agent '{}': {}", agent_dir.name, exc)

    return total
```

**Verify:**
```bash
poetry run python -c "
from app.utils.db import init_schema
from app.utils.indexer import run_indexer
init_schema()
total = run_indexer()
print(f'Indexed {total} entries')
"
```

**Debug notes:**
- Checkpoint tracking: each `(agent, source)` pair has a `last_line` integer. If MEMORY.MD has 56 lines and checkpoint is 56, nothing is indexed. If a new line is appended (57 lines), only line 57 is processed.
- If MEMORY.MD is truncated/pruned (fewer lines than checkpoint): the indexer skips it. This is intentional — re-indexing old data would create duplicates. To force re-index: `DELETE FROM index_checkpoints WHERE agent = 'builder';`
- Embedding failure is non-fatal — the checkpoint is NOT advanced, so the next run retries.
- The indexer is synchronous (not async) because it runs in APScheduler's thread pool.

---

### Step 7: Hook into task completion — `app/agents/base/runner.py`

**What to change:** After `set_task_status("done", ...)` and `set_task_status("error", ...)`, insert a task record into SQLite.

**File:** `app/agents/base/runner.py` — around line 184

Find the block (approximately lines 175–190):

```python
            result_text = await self._agent._read_file("RESULT.MD")
            result_text = result_text.strip()

            await self._agent.set_task_status("done", result=result_text or "Task completed.")

        except TimeoutError:
            await self._agent.set_task_status("error", error="Task timed out (exceeded configured timeout)")
        except Exception as exc:
            await self._agent.set_task_status("error", error=str(exc) or repr(exc))
```

**Add after each `set_task_status` call:**

```python
            await self._agent.set_task_status("done", result=result_text or "Task completed.")
            # ── Persist task to SQLite ──
            try:
                from app.utils.db import init_schema, insert_task
                init_schema()
                insert_task(
                    agent=self._name,
                    task_id=task_frontmatter.get("task_id", ""),
                    status="done",
                    assigned_by=task_frontmatter.get("assigned_by", ""),
                    assigned_at=task_frontmatter.get("assigned_at", ""),
                    task_summary=task_text[:500],
                    result_summary=result_text[:2000],
                )
            except Exception:
                pass  # never let DB errors break the runner

        except TimeoutError:
            await self._agent.set_task_status("error", error="Task timed out (exceeded configured timeout)")
            try:
                from app.utils.db import init_schema, insert_task
                init_schema()
                insert_task(
                    agent=self._name,
                    task_id=task_frontmatter.get("task_id", ""),
                    status="error",
                    assigned_by=task_frontmatter.get("assigned_by", ""),
                    assigned_at=task_frontmatter.get("assigned_at", ""),
                    task_summary=task_text[:500],
                    error_summary="Task timed out",
                )
            except Exception:
                pass
        except Exception as exc:
            await self._agent.set_task_status("error", error=str(exc) or repr(exc))
            try:
                from app.utils.db import init_schema, insert_task
                init_schema()
                insert_task(
                    agent=self._name,
                    task_id=task_frontmatter.get("task_id", ""),
                    status="error",
                    assigned_by=task_frontmatter.get("assigned_by", ""),
                    assigned_at=task_frontmatter.get("assigned_at", ""),
                    task_summary=task_text[:500],
                    error_summary=str(exc)[:2000],
                )
            except Exception:
                pass
```

**Important:** `task_frontmatter` and `task_text` must already be in scope. Check the runner's `_execute_task` method — it parses frontmatter early in the method. If these variables don't exist under those exact names, read the method to find how frontmatter fields are extracted and use the correct variable names.

**Debug notes:**
- Lazy import (`from app.utils.db import ...`) inside the try block is intentional — it avoids importing sqlite3/numpy at runner startup, keeping subprocess spawn fast.
- `try/except: pass` is intentional — DB errors must NEVER break agent task execution. The task lifecycle is more important than the audit log.
- `[:500]` and `[:2000]` truncation prevents storing huge blobs in SQLite.

---

### Step 8: Register indexer as APScheduler job

**File:** `app/backend/main.py` — inside the `lifespan()` function

**Add a new tick function** (near `_doctor_tick` and `_model_manager_tick`, around line 55):

```python
async def _indexer_tick() -> None:
    """Run the memory indexer (called by APScheduler)."""
    import asyncio
    from app.utils.indexer import run_indexer

    try:
        await asyncio.to_thread(run_indexer)
    except Exception:
        pass  # indexer logs its own errors
```

**Add scheduler registration** inside `lifespan()` (where Doctor and ModelManager are registered, around line 165):

```python
    scheduler.add_job(_indexer_tick, "interval", minutes=10, id="indexer")
```

**Add initial fire** (where Doctor's `call_later(5, ...)` is, around line 175):

```python
    loop.call_later(20, lambda: asyncio.ensure_future(_indexer_tick()))
```

The 20s delay lets the server fully start before the indexer loads the embedding model.

**Also add `init_schema()` call at startup** (right after `_cleanup_stale_agent_statuses()`, around line 149):

```python
    _cleanup_stale_agent_statuses()

    # Initialize SQLite schema
    from app.utils.db import init_schema
    init_schema()
```

**Verify:**
```bash
poetry run yapoc start
# Wait 20 seconds, then:
sqlite3 data/yapoc.db "SELECT agent, source, COUNT(*) FROM memory_entries GROUP BY agent, source;"
```

**Debug notes:**
- `asyncio.to_thread(run_indexer)` is required because the indexer does synchronous I/O (file reads, SQLite writes, numpy operations). Without it, the event loop blocks.
- The 10-minute interval is a good default. For high-activity systems, lower to 2–5 minutes. Controlled via `settings.embedding_index_interval_minutes` if you add that setting.
- First run is slow (~3–5 s for model load + embedding ~100 entries). Subsequent runs are fast (<500 ms if no new entries).

---

### Step 9: Add `search_memory` to agent CONFIG.md files

Add `search_memory` to the tools list of agents that should have it.

**Files to edit:**
- `app/agents/master/CONFIG.md` — add `  - search_memory`
- `app/agents/planning/CONFIG.md` — add `  - search_memory`
- `app/agents/builder/CONFIG.md` — add `  - search_memory` (optional)

Example (master):
```yaml
tools:
  - spawn_agent
  - wait_for_agent
  - wait_for_agents
  # ... existing tools ...
  - search_memory
```

---

### Step 10: Add settings (optional)

**File:** `app/config/settings.py` — add to the `Settings` class:

```python
    # ── Embedding / indexer ───────────────────────────────────────────────
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_index_interval_minutes: int = 10
```

These are optional — the defaults are hardcoded in `embeddings.py` and `main.py`. Adding them to settings makes them configurable via `.env`.

---

## File Summary

| File | Action | Lines changed |
|---|---|---|
| `pyproject.toml` | `poetry add sentence-transformers` | 1 |
| `app/utils/db.py` | **New** — SQLite schema + helpers | ~220 |
| `app/utils/embeddings.py` | **New** — lazy embedding model | ~40 |
| `app/utils/indexer.py` | **New** — MEMORY.MD background indexer | ~110 |
| `app/utils/tools/search.py` | **New** — `SearchMemoryTool` | ~80 |
| `app/utils/tools/__init__.py` | Add import + registry entry | 2 |
| `app/agents/base/runner.py` | Insert task records after completion | ~30 |
| `app/backend/main.py` | Add indexer job + `init_schema()` | ~10 |
| `app/agents/*/CONFIG.md` | Add `search_memory` to tool lists | 3 files, 1 line each |
| `app/config/settings.py` | Optional: add `embedding_model`, `embedding_index_interval_minutes` | 2 |

---

## Debugging Playbook

### Problem: "Memory index is empty"
1. Check indexer ran: `sqlite3 data/yapoc.db "SELECT * FROM index_checkpoints;"`
2. If no checkpoints: the indexer hasn't run. Check server logs for `_indexer_tick` errors.
3. If checkpoints exist but `memory_entries` is empty: all MEMORY.MD lines were shorter than 20 chars. Lower `_MIN_CONTENT_LEN`.

### Problem: "Search returns irrelevant results"
1. Check FTS5 index: `sqlite3 data/yapoc.db "SELECT COUNT(*) FROM memory_fts;"`
2. If FTS count differs from `memory_entries` count: rebuild FTS: `INSERT INTO memory_fts(memory_fts) VALUES('rebuild');`
3. If semantic results are poor: the query might be too abstract. Try more specific phrases.

### Problem: "First search_memory call is very slow"
Expected. The sentence-transformers model loads on first call (~3–5 s). Subsequent calls are <50 ms. The indexer's first run in main.py pre-loads the model, so agent calls after that are fast.

### Problem: "SQLite BUSY / locked"
1. Check WAL mode: `sqlite3 data/yapoc.db "PRAGMA journal_mode;"` — should show `wal`.
2. Multiple processes writing simultaneously: WAL handles this for reads, but only one writer at a time. The 5s timeout should handle normal contention.
3. If persistent: a crashed process may hold a lock. Delete `data/yapoc.db-wal` and `data/yapoc.db-shm` (safe — WAL checkpoint happens automatically).

### Problem: "ImportError: sentence-transformers"
```bash
poetry show sentence-transformers  # check it's installed
poetry env info                    # check venv path matches runtime
which python                       # check it's the poetry venv python
```

### Problem: "DB file missing after restart"
Check `data/` directory exists. `init_schema()` creates it via `_db_path()` → `mkdir(parents=True)`. If running from a different CWD, `settings.project_root` might resolve differently.

### Problem: "Duplicate entries after MEMORY.MD pruning"
If `_prune_memory_if_needed()` runs and truncates MEMORY.MD to fewer lines than the checkpoint, the indexer skips. But if pruning resets lines AND the checkpoint isn't updated, old content might be re-indexed on a future append. Fix: after pruning MEMORY.MD, call `set_checkpoint(agent, "MEMORY.MD", new_line_count)`.

---

## End-to-End Verification

```bash
# 1. Install deps
poetry add sentence-transformers

# 2. Start server (creates DB, runs initial indexer after 20s)
poetry run yapoc start

# 3. Wait 25 seconds for indexer to run, then check
sqlite3 data/yapoc.db "SELECT agent, source, COUNT(*) c FROM memory_entries GROUP BY agent, source ORDER BY c DESC;"

# 4. Test search from Python
poetry run python -c "
from app.utils.db import init_schema, search_hybrid
from app.utils.embeddings import embed
init_schema()
results = search_hybrid('agent configuration', embed('agent configuration'), top_k=5)
for r in results:
    print(f\"[{r['agent']}/{r['source']}] {r['content'][:80]}...\")
"

# 5. Send a task and verify it's recorded
poetry run yapoc chat "create a hello world python script"
sqlite3 data/yapoc.db "SELECT agent, status, task_summary FROM tasks ORDER BY id DESC LIMIT 5;"

# 6. Test the tool via REPL
poetry run yapoc
# Type: search my memory for decisions about file structure
```
