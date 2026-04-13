# YAPOC System Audit — Databases & Embedding Search
*Audit date: 2026-04-12 | Scope: full codebase*

## Summary

The system is fundamentally file-based with no database infrastructure. Primary bottlenecks are **unbounded file growth** (MEMORY/HEALTH logs), **lack of search/retrieval** across agent history, and **silent context loss** during compaction. SQLite and vector/embedding search are the two highest-leverage additions for long-running deployments.

---

## 1. Current Storage — Complete Inventory

### Per-agent files (×7 named agents + ephemeral)

| File | Format | Current size (builder) | Pain point |
|---|---|---|---|
| `MEMORY.MD` | Append-only log, 1 line/turn | 56 entries / 16 KB | Unbounded; no pruning; only last 10 lines injected per turn |
| `HEALTH.MD` | Append-only error log | 136 KB | Doctor prunes >7 days; crash entries never pruned |
| `NOTES.MD` | Free-form knowledge | Usually empty | Injected at 3 000 char cap; not indexed or searchable |
| `TASK.MD` | YAML frontmatter + markdown body | Single active task | Overwritten per task — no history retained |
| `RESULT.MD` | Last LLM response | Overwritten per turn | All previous full responses lost |
| `OUTPUT.MD` | Subprocess stdout/stderr | 196 KB | Rotated at 512 KB; split at char boundary (not line) |
| `CRASH.MD` | Structured crash reports | Append-only | Append-only; never pruned |
| `STATUS.json` | `{state, pid, started_at, ...}` | ~200 bytes | Fine as-is |
| `USAGE.json` | Token/cost by model | ~1 KB | Fine as-is; could move to SQLite for cross-agent analytics |
| `CONFIG.md` | YAML agent config | Static | Static; read 1× per task after recent optimization |
| `PROMPT.MD` | System prompt template | Static | Fine as-is |

### Cross-agent / global files

| File | Format | Location | Notes |
|---|---|---|---|
| Session JSONL | One JSON line per message | `master/sessions/*.jsonl` | 32 files, 228 KB total; no pagination; no pruning |
| `notification_queue.json` | JSON array + `fcntl.flock` | `data/` | Queue; consumed per-delivery; fine as-is |
| `HEALTH_SUMMARY.MD` | Markdown report | `doctor/` | Overwritten every 5 min by Doctor |
| `SERVER_OUTPUT.MD` | Server stdout | `master/` | 229 KB / 11 K lines; not rotated separately |
| `RESUME.MD` | Task context across REPL sessions | `master/` | Written on clean REPL exit |

### Current dependencies (pyproject.toml)

**No database or ML libraries exist today.** Notable:
- `numpy>=2.4.3` — present but **unused** (presumably reserved for future embeddings)
- `aiofiles` — all file I/O is async
- No SQLite wrapper beyond stdlib, no SQLAlchemy, no vector DB client

---

## 2. Information Loss Map

| Location | What is lost | Trigger |
|---|---|---|
| Context compaction | Exact conversation structure, tool call details, precise code snippets | Every ~85% context window fill |
| `RESULT.MD` overwrite | All previous full turn responses | Every turn |
| `MEMORY.MD` injection cap | Entries older than the last 10 lines invisible to agent per turn | Every turn |
| `NOTES.MD` char cap | Content beyond 3 000 chars invisible per turn | Every turn |
| `OUTPUT.MD` rotation | Oldest 50% of subprocess logs (not line-aware) | At 512 KB |
| Task completion | Full task body + result once TASK.MD is overwritten by next task | Every new task |
| Tool output truncation | Results >6 000 chars silently cut | Every large tool result |

---

## 3. Search Capability Today

**None.** No grep, no full-text index, no semantic search exists for agents.

How agents currently find information:
1. `file_read` / `notes_read` — explicit full-file load (agent must know *where* to look)
2. Context injection — automatic last-N-lines of MEMORY.MD + first K chars of NOTES.MD
3. LLM in-context memory — limited to what fits in the current window

**What is missing:** "find all past decisions about X", "summarize what planning agent decided last week", "have we solved this class of problem before?"

---

## 4. Recommended Architecture

### 4A. SQLite — structured metadata

**Single database file:** `data/yapoc.db` (Python stdlib `sqlite3`, no extra deps)

**Three high-value tables:**

```sql
-- Task history — currently lost on TASK.MD overwrite
CREATE TABLE tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent           TEXT NOT NULL,
    parent          TEXT,                   -- assigning agent
    task_id         TEXT,                   -- frontmatter task_id
    status          TEXT,                   -- pending/running/done/error
    assigned_by     TEXT,
    assigned_at     TEXT,
    completed_at    TEXT,
    result_summary  TEXT,
    error_summary   TEXT
);
CREATE INDEX tasks_agent_status ON tasks(agent, status);
CREATE INDEX tasks_assigned_at  ON tasks(assigned_at DESC);

-- Session index — replaces JSONL-only file discovery
CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,       -- matches JSONL filename stem
    created_at      TEXT,
    name            TEXT,
    message_count   INTEGER DEFAULT 0,
    total_tokens    INTEGER DEFAULT 0,
    cost_usd        REAL    DEFAULT 0.0,
    model           TEXT
);

-- Cross-agent usage analytics (supplements per-agent USAGE.json)
CREATE TABLE usage_events (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    agent                   TEXT NOT NULL,
    model                   TEXT NOT NULL,
    recorded_at             TEXT NOT NULL,
    input_tokens            INTEGER DEFAULT 0,
    output_tokens           INTEGER DEFAULT 0,
    cache_creation_tokens   INTEGER DEFAULT 0,
    cache_read_tokens       INTEGER DEFAULT 0,
    cost_usd                REAL    DEFAULT 0.0
);
CREATE INDEX usage_agent_model ON usage_events(agent, model);
```

**Why SQLite and not Postgres/Mongo:** No infrastructure, no server process, single file in `data/`, built into Python stdlib, handles concurrent readers without configuration. Right-sized for this workload.

**What stays as files:** PROMPT.MD (static), MEMORY.MD (still appended for human readability and as embedding source), HEALTH.MD (kept for Doctor Agent compatibility), NOTES.MD (free-form knowledge), CRASH.MD (debugging artifact). STATUS.json also stays — it's tiny and written by the subprocess watcher which should remain dependency-free.

---

### 4B. Embedding Search — semantic agent memory

**Embedding model:** `sentence-transformers` with `all-MiniLM-L6-v2`
- 22 MB model, CPU-fast (~5 ms/sentence), no API key, 384-dim output
- Suitable for semantic similarity over short MEMORY.MD entries and NOTES.MD paragraphs

**Vector store (two options):**
- **MVP:** Plain `numpy` dot-product over stored float32 arrays in SQLite BLOB column — zero extra deps, fast for <100 K entries
- **Production:** `sqlite-vec` extension (pure-Python wheel) — proper ANN index, 10× faster at scale

**What to embed:**

| Source | Unit of embedding | Use case |
|---|---|---|
| `MEMORY.MD` entries | 1 embedding per log line (~150 chars) | "What did we decide about auth?" |
| `RESULT.MD` snapshots | 1 embedding per task completion | Semantic task deduplication |
| `NOTES.MD` paragraphs | 1 embedding per paragraph | Knowledge retrieval |
| Session JSONL | 1 embedding per assistant turn | Cross-session recall |

**New agent tool:** `search_memory(query, agent=None, top_k=5, days=None)`
- Embeds the query string at call time
- Cosine similarity search across stored embeddings
- Returns top-K results with source, agent, and timestamp
- Optional `agent` filter scopes to one agent's history
- Optional `days` filter limits recency

**Storage schema (numpy MVP):**

```sql
CREATE TABLE memory_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent       TEXT NOT NULL,
    source      TEXT NOT NULL,  -- MEMORY.MD / RESULT.MD / NOTES.MD / SESSION
    content     TEXT NOT NULL,
    timestamp   TEXT,
    embedding   BLOB            -- float32 numpy array, stored as bytes
);
CREATE INDEX memory_agent ON memory_entries(agent);
CREATE INDEX memory_source ON memory_entries(agent, source);
```

**Indexing pipeline:** New APScheduler background job (`EmbeddingIndexer`) similar to Doctor Agent:
1. Reads MEMORY.MD lines since last checkpoint (`last_indexed_line` stored in SQLite)
2. Embeds batch with sentence-transformers
3. Inserts into `memory_entries`
4. Updates checkpoint
5. Runs every `settings.embedding_index_interval_minutes` (default 10)

---

## 5. Implementation Priority

| Priority | Item | Effort | Impact |
|---|---|---|---|
| **1** | SQLite task history table + write on task completion | Low | Persistent task log; enables analytics |
| **2** | SQLite session index + write on session save | Low | Fast session browsing; cost tracking |
| **3** | `search_memory` tool (numpy MVP) | Medium | Biggest capability boost for agents |
| **4** | Embedding indexer APScheduler job | Medium | Keeps index fresh automatically |
| **5** | Migrate to `sqlite-vec` ANN index | Low (after MVP) | 10× faster search at scale |
| **6** | Cross-agent usage analytics via `usage_events` table | Low | Replaces per-agent USAGE.json silos |

---

## 6. Files to Create / Modify

| File | Action |
|---|---|
| `data/yapoc.db` | Created automatically on first init |
| `app/utils/db.py` | **New** — `get_db()` connection, `init_schema()`, typed helpers |
| `app/utils/embeddings.py` | **New** — `embed(texts)`, `search(query, ...)`, `index_agent(name)` |
| `app/utils/tools/search.py` | **New** — `SearchMemoryTool` implementation |
| `app/utils/tools/__init__.py` | Add `search_memory` to `TOOL_REGISTRY` |
| `app/agents/base/runner.py` | Write completed task records to SQLite on status change |
| `app/cli/sessions.py` | Write session metadata row to SQLite on `save()` |
| `app/backend/main.py` | Call `db.init_schema()` on startup |
| `pyproject.toml` | `poetry add sentence-transformers` (+ `sqlite-vec` when ready) |
| `app/config/settings.py` | Add `embedding_index_interval_minutes`, `embedding_model` settings |

---

## 7. What NOT to change

- **Agent MD files** — MEMORY.MD, HEALTH.MD, NOTES.MD, PROMPT.MD, TASK.MD remain the human-readable source of truth. The database is additive, never a replacement.
- **STATUS.json** — stays as a file; the subprocess watcher writes it and should remain dependency-free.
- **notification_queue.json** — small, fast, already has correct `fcntl.flock` semantics; not worth migrating.
- **CRASH.MD** — debugging artifact; plain text is more useful here than a structured table.

---

## 8. Verification Steps

After implementation:

```bash
# 1. Start the server and run a task
poetry run yapoc start
poetry run yapoc chat "create a simple hello world script"

# 2. Check task history
sqlite3 data/yapoc.db "SELECT agent, status, assigned_at, completed_at FROM tasks ORDER BY id DESC LIMIT 10;"

# 3. Check session index
sqlite3 data/yapoc.db "SELECT id, name, message_count, cost_usd FROM sessions ORDER BY created_at DESC LIMIT 5;"

# 4. Check embedding index
sqlite3 data/yapoc.db "SELECT agent, source, COUNT(*) FROM memory_entries GROUP BY agent, source;"

# 5. Test search_memory tool from REPL
# Type in REPL: search my memory for decisions about file structure
```
