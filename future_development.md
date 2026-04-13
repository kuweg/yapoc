# YAPOC — Future Development Report

## 1. File Versioning for Agent MD & Project Files

### Problem
Agents use different LLM models (expensive vs cheap). A cheaper model can break work produced by an expensive one. Need version tracking with rollback capability that agents themselves can access and understand.

### Considered Options

| Solution | Fit | Verdict |
|----------|-----|---------|
| **Git auto-commits** | Agents understand git, `shell_exec` already exists, atomic rollback | Good for disaster recovery layer |
| **DVC** | Designed for large artifacts (datasets, models), overkill for small MD files | Not a fit now, revisit if `app/projects/` grows |
| **SQLite version store** | `(agent, file, version, content, model, hash)` — queryable, single file | **Chosen candidate** |
| **Event sourcing (CHANGELOG.MD)** | Append-only log per agent, fits existing MEMORY.MD pattern | Good complement to SQLite |
| **Fossil SCM** | Single-file repo, built-in wiki | LLMs know it less, smaller ecosystem |
| **Dolt** | Git-for-SQL, branch/merge/diff on tables | Heavy dependency |

### Decision
**SQLite or Git** — final choice TBD. Key requirements:
- Model attribution on every change (which agent, which model)
- Per-file rollback without affecting other files
- Agents can query history via tools (not raw git CLI)

### Proposed Tools

| Tool | Purpose |
|------|---------|
| `checkpoint` | Save a versioned snapshot of a file with metadata (agent, model, summary) |
| `rollback` | Restore a file to a previous version |
| `file_history` | Query version history for a file (who changed it, when, which model) |

---

## 2. Handling Large Agent Files (RAG & Alternatives)

### Problem
Agent MD files (MEMORY.MD, NOTES.MD, project docs) will grow over time. Large files waste context window, increase cost, and overwhelm cheap models.

### Tiered Strategy

#### Tier 1: Structured Files + Splitting (no dependencies)
- **Archive pattern**: When MEMORY.MD exceeds N entries, move old entries to `MEMORY_ARCHIVE/YYYY-MM.md`, keep a summary in MEMORY.MD
- **Topic splitting**: Split NOTES.MD into `NOTES/topic.md` files with an index
- **Agents read summaries first**, dig into specific files on demand
- **Cost**: Zero — just file organization conventions

#### Tier 2: Full-Text Search with SQLite FTS5 (stdlib only)
- SQLite FTS5 virtual table — ships with Python, zero dependencies
- Agents get a `search` tool to query across all agent files
- Keyword-based, works well for structured markdown with clear terminology
- **Synergy**: Can share the same SQLite DB used for versioning (Tier 1 above)

```python
# Schema sketch
CREATE VIRTUAL TABLE docs USING fts5(agent, file, section, content);
SELECT * FROM docs WHERE docs MATCH 'authentication retry';
```

#### Tier 3: Semantic RAG (only if keyword search proves insufficient)
Needed when query terms don't overlap with stored text (e.g., asking "error handling strategy" when the text says "retry with exponential backoff").

| Option | Type | Notes |
|--------|------|-------|
| **ChromaDB** | Embedded Python | Simple API, local-only, good for MVP |
| **LanceDB** | Embedded, no server | Fast, versioned, newer ecosystem |
| **SQLite-vec** | SQLite extension | Reuses existing SQLite, single file |
| **Qdrant** | Client-server | Production-grade, needs separate process |

**Embedding models**:
- Local: `sentence-transformers` (free, private, ~100MB)
- API: OpenAI `text-embedding-3-small` (cheap, better quality)

### Recommendation
Start with **Tier 1 + Tier 2**. Add Tier 3 only when a concrete failure case appears (agent searches for something, gets no results despite the info existing).

---

## 3. Implementation Priority

```
Phase 1 (current MVP+)
├── File splitting conventions for MEMORY.MD / NOTES.MD
├── SQLite version store with model attribution
└── checkpoint / rollback / file_history tools

Phase 2 (when files grow)
├── SQLite FTS5 search index
└── search tool for agents

Phase 3 (if needed)
├── Embedding-based RAG (ChromaDB or SQLite-vec)
└── Semantic search tool for agents
```

---

*Generated: 2026-03-14*
