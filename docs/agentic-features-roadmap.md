# YAPOC Agentic Features Roadmap

*Last updated: 2026-04-13*

## Principles

1. **Safety before capability** — no new autonomy ships without sandbox enforcement + tests covering it
2. **Build on what exists** — extend working code (sandbox, fallback adapters, Doctor, cost tracking), don't rewrite
3. **Concrete over aspirational** — every item names specific files, functions, and acceptance criteria
4. **One feature at a time** — finish and verify before starting the next

---

## Current System State

**Already implemented and production-ready:**

| Capability | Status | Key files |
|---|---|---|
| Tool-level sandbox | Done | `tools/__init__.py` SandboxPolicy, `file.py` `_sandbox()` |
| Model fallback chains | Done | `agent_settings.py`, `adapters/fallback.py` FallbackAdapter |
| Cost tracking (per-agent, per-model) | Done | `usage_tracker.py`, `cli/renderer.py` |
| Doctor agent (autonomous health check) | Done | `agents/doctor/agent.py` — prunes logs, detects timeouts, writes optimization suggestions |
| Context auto-compaction | Done | `BaseAgent._compact_messages()` — haiku summarizer at 85% context fill |
| Notification chain (sub-agent → parent) | Done | `notify_parent` tool, `notification_queue.py`, `spawn_registry.py` |
| Task tracing | Done | `add_task_trace` tool — posts notes to ticket activity timeline |
| CONFIG.md read consolidation | Done | Single read per task in `run_stream_with_tools`, passed to sub-functions |
| Poll interval optimization | Done | `wait_for_agent` / `wait_for_agents` default 3s (was 15s/10s) |

**Implemented but thin (prompt + CONFIG + BaseAgent subclass, no custom logic):**

| Agent | State | Notes |
|---|---|---|
| Keeper | Implemented, task-driven | Sandbox enforced; manages .env, settings.py, pyproject.toml |
| Cron | Implemented, task-driven | Schedule in NOTES.MD; spawned by APScheduler every 10 min |

**Implemented in M1-M3 (2026-04-13):**

| Capability | Status | Key files |
|---|---|---|
| SQLite persistence (tasks + memory) | Done | `app/utils/db.py`, APScheduler in `main.py`, runner inserts on completion |
| Embedding search (hybrid RRF) | Done | `app/utils/embeddings.py`, `app/utils/indexer.py`, `app/utils/tools/search.py` |
| `search_memory` tool | Done | Registered in `tools/__init__.py`, added to master/planning/builder CONFIG.md |
| Uncertainty protocol | Done | Added `[UNCERTAIN]` escalation to master, planning, builder PROMPT.MD |
| Secret scanning | Done | `app/utils/secrets.py` — integrated into memory tools + `_sanitize_for_memory()` |
| Decision logging | Done | `add_task_trace` rationale prompts in master, planning, builder PROMPT.MD |
| Test suite expansion | Done | 39 new tests: `test_db.py`, `test_secrets.py`, `test_sandbox.py`, `test_context.py`, `test_embeddings.py` |

**Implemented in M4-M5 (2026-04-13):**

| Capability | Status | Key files |
|---|---|---|
| Tool retry on transient errors | Done | `app/agents/base/__init__.py` `_execute_tool()` — 1 retry with 2s delay |
| Error recovery prompting | Done | Master, builder, planning PROMPT.MD `## Error Recovery` sections |
| Stale task detection | Done | `agents/doctor/agent.py` `_check_stale_tasks()` — 3 detection modes |
| Cross-agent error patterns | Done | `agents/doctor/agent.py` `_detect_cross_agent_patterns()` — 3+ agents threshold |

**Implemented in M6-M7 (2026-04-13):**

| Capability | Status | Key files |
|---|---|---|
| LEARNINGS.MD file + context injection | Done | `context.py`, LEARNINGS.MD for all agents |
| `learnings_append` tool | Done | `tools/memory.py`, registered in `__init__.py` |
| Outcome classification in MEMORY.MD | Done | `base/__init__.py` — `| outcome: success` suffix |
| Learning retrieval prompts | Done | Master, planning, builder PROMPT.MD |
| LEARNINGS.MD indexing | Done | `indexer.py` `index_agent_learnings()` |
| Structured escalation format | Done | `[DECISION NEEDED]` format in all 3 agent prompts |

**Implemented in M8 (2026-04-13):**

| Capability | Status | Key files |
|---|---|---|
| Shared Knowledge Base (KNOWLEDGE.MD) | Done | `agents/shared/KNOWLEDGE.MD`, `tools/memory.py` `SharedKnowledgeAppendTool` |
| `shared_knowledge_append` tool | Done | `tools/memory.py`, registered in `__init__.py`, added to all agent CONFIG.md |
| KNOWLEDGE.MD context injection | Done | `context.py` — newest 1500 chars injected as `## Shared Knowledge` |
| KNOWLEDGE.MD indexing | Done | `indexer.py` `index_shared_knowledge()` |
| Peer delegation protocol | Done | `tools/delegation.py` `_parse_delegation_targets()`, `SpawnAgentTool` guard |
| `delegation_targets` in CONFIG.md | Done | builder→keeper, keeper→builder, cron→builder+keeper |
| Peer delegation audit trail | Done | `[PEER DELEGATION]` logged to master's HEALTH.MD |
| Peer delegation prompts | Done | Builder, keeper, master PROMPT.MD updated |

**Implemented in M9 (2026-04-13):**

| Capability | Status | Key files |
|---|---|---|
| Capability module library (5 modules) | Done | `app/modules/capabilities.py` |
| CreateAgentTool `modules` parameter | Done | `app/utils/tools/agent_mgmt.py` |
| Learning promotion on agent deletion | Done | `app/utils/tools/agent_mgmt.py` |
| `image_read` tool | Done | `app/utils/tools/file.py` |
| `parse_csv` tool (with PII scrubbing) | Done | `app/utils/tools/file.py` |
| PII detection (`scrub_pii`) | Done | `app/utils/secrets.py` |
| Goal reasoning (Planning prompt) | Done | `app/agents/planning/PROMPT.MD` |
| Budget enforcement (per-task, per-agent) | Done | `app/agents/base/__init__.py`, `app/config/settings.py` |
| Runaway cost detection (Doctor) | Done | `app/agents/doctor/agent.py` |
| Cost dashboard endpoints | Done | `app/backend/routers/metrics.py` |

**Not yet implemented:**

| Capability | Notes |
|---|---|
| Feature flags | No system exists |
| Batch approval (UI) | Deferred from M7B — needs UI approval interface |
| Autonomy envelope (CONFIG.md) | Deferred from M5C |

---

## Milestone 1: Memory + Search (DB Foundation) — DONE

**Status:** Fully implemented. All files created, APScheduler integrated, runner records tasks.

**Implementation plan:** `docs/implementation-plan-db-embeddings.md`

**Files created/modified:**
- `app/utils/db.py` — SQLite schema (tasks, memory_entries, memory_fts, index_checkpoints)
- `app/utils/embeddings.py` — lazy-loaded sentence-transformers (all-MiniLM-L6-v2, 384-dim)
- `app/utils/indexer.py` — background MEMORY.MD + NOTES.MD indexer with checkpoints
- `app/utils/tools/search.py` — `SearchMemoryTool` (hybrid RRF search)
- `app/utils/tools/__init__.py` — registered `search_memory`
- `app/agents/base/runner.py` — `insert_task()` on done/error/timeout
- `app/backend/main.py` — `init_schema()` on startup, `_indexer_tick` every 10 min
- `app/agents/{master,planning,builder}/CONFIG.md` — added `search_memory` to tools

---

## Milestone 2: Safety Baseline — DONE

**Status:** Fully implemented. Uncertainty protocol in prompts, secret scanning in memory tools, 39 new tests passing.

**2A. Uncertainty Escalation — Done**
- Added `## Uncertainty Protocol` section to `agents/master/PROMPT.MD`, `agents/planning/PROMPT.MD`, `agents/builder/PROMPT.MD`
- Agents assess intent/context/reversibility before consequential actions
- Format: `[UNCERTAIN]` + structured report when confidence is insufficient

**2B. Test Suite Expansion — Done**
- `tests/test_db.py` — 9 tests (schema, insert, query, FTS, vector, hybrid, checkpoints)
- `tests/test_secrets.py` — 12 tests (all key types, false positives, edge cases)
- `tests/test_sandbox.py` — 7 tests (forbidden paths, shell allowlist, config parsing)
- `tests/test_context.py` — 7 tests (runner config parsing, context assembly, limits, preloaded config)
- `tests/test_embeddings.py` — 4 tests (shape, dtype, batch, similarity)
- Total: 39 new tests, all passing

**2C. Secret Scanning — Done**
- Created `app/utils/secrets.py` with `scrub()` function
- Patterns: Anthropic, OpenAI, OpenRouter, Google API keys; password/secret/token key-value; PEM keys; connection strings
- Integrated into: `MemoryAppendTool`, `NotesWriteTool`, `NotesAppendTool`, `HealthLogTool`, `_sanitize_for_memory()`

---

## Milestone 3: Explainability — DONE

**Status:** Fully implemented via prompt engineering. All three core agents have decision logging instructions.

**3A. Decision Rationale — Done**
- Added `## Decision Logging` section to master, planning, builder PROMPT.MD
- Agents call `add_task_trace` with 1-sentence rationale BEFORE non-trivial decisions
- `add_task_trace` tool already in all three agents' CONFIG.md

**3B. Counterfactual Logging for Delegation — Done**
- Added to `agents/planning/PROMPT.MD` in the Uncertainty Protocol section
- Planning logs decomposition choice, alternatives considered, and assumptions before spawning

---

## Milestone 4: Self-Healing & Recovery — DONE

**Status:** Fully implemented. Transient tool errors auto-retry, recovery prompting in all agents.

**4A. Tool Retry Logic — Done**
- Modified `_execute_tool()` in `app/agents/base/__init__.py`
- Transient errors (`TimeoutError`, `ConnectionError`, `OSError`) get 1 automatic retry with 2s delay
- Non-transient errors (`ValueError`, `FileNotFoundError`, etc.) fail immediately — no retry
- Retries logged at WARNING level via loguru
- 5 tests in `tests/test_tool_retry.py` (all passing)

**4B. Recovery Prompting — Done**
- Added `## Error Recovery` section to `master/PROMPT.MD`, `builder/PROMPT.MD`, `planning/PROMPT.MD`
- Master/builder: "transient errors retried automatically, permanent errors — adjust approach"
- Planning: "failed delegation — retry once, then adjust task description, then escalate after 2 failures"

---

## Milestone 5: Proactive Agent Behavior — DONE (5A + 5B)

**Status:** Stale task detection and cross-agent pattern recognition implemented in Doctor. Autonomy envelope (5C) deferred — not needed until Doctor takes autonomous corrective actions.

**5A. Stale Task Detection — Done**
- Added `_check_stale_tasks()` to `agents/doctor/agent.py`
- Detects: `STALE_TASK` — running for > 2× task_timeout (default 10 min)
- Detects: `CRASHED_TASK` — STATUS.json says terminated but TASK.MD says running
- Detects: `ZOMBIE_TASK` — STATUS.json says running but PID is dead
- Writes warnings to affected agent's HEALTH.MD AND master's HEALTH.MD
- Findings appear in HEALTH_SUMMARY.MD under "## Stale / Crashed Tasks"
- 5 tests in `tests/test_doctor_proactive.py` (all passing)

**5B. Cross-Agent Pattern Recognition — Done**
- Added `_detect_cross_agent_patterns()` to `agents/doctor/agent.py`
- Extracts error signatures (first 50 chars after `ERROR:`) from each agent's HEALTH.MD
- When 3+ agents share the same error signature, reports as `CROSS_AGENT_PATTERN`
- Writes findings to master's HEALTH.MD and HEALTH_SUMMARY.MD
- 4 tests in `tests/test_doctor_proactive.py` (all passing)

**5C. Autonomy Envelope — Deferred**
Not needed yet. Doctor currently only writes warnings — no autonomous corrective actions that would require an envelope. Will implement when Doctor gains restart/kill capabilities.

---

## Milestone 6: Agent Learning — DONE

**Status:** Fully implemented. LEARNINGS.MD file, tool, context injection, outcome classification, and learning retrieval prompts.

**6A. LEARNINGS.MD File Standard — Done**
- Created `LEARNINGS.MD` for all 6 named agents (master, planning, builder, keeper, cron, doctor)
- Added `## Learned Rules` section to `build_system_context()` in `app/agents/base/context.py`
- Capped at `context_learnings_limit` chars (default 2000), configurable in CONFIG.md runner block
- Created `LearningsAppendTool` in `app/utils/tools/memory.py` — structured rule format with name/context/action/confidence
- Max 20 rules per agent enforced by the tool; secrets scrubbed via `scrub()`
- Registered in `tools/__init__.py`, added to `_AGENT_DIR_TOOLS`, added to master/planning/builder CONFIG.md

**6B. Outcome Classification — Done**
- All 3 MEMORY.MD write paths in `app/agents/base/__init__.py` now append `| outcome: success`
- Format: `[timestamp] task: ... | result: ... | outcome: success`

**6C. Learning Retrieval — Done**
- Added `## Learning from Experience` section to master, planning, builder PROMPT.MD
- Agents call `search_memory` before complex tasks and apply LEARNINGS.MD rules
- Agents call `learnings_append` when same pattern observed 2+ times
- LEARNINGS.MD indexed by `index_agent_learnings()` in `app/utils/indexer.py` for `search_memory` retrieval
- 9 tests in `tests/test_learnings.py` (all passing)

---

## Milestone 7: Human-in-the-Loop Refinement — DONE (7A)

**Status:** Structured escalation format implemented in all three core agent prompts. Batch approval (7B) deferred — testing is via backend+UI, not CLI approval gate.

**7A. Structured Escalation Format — Done**
- Added `## Escalation Format` section to master, builder, planning PROMPT.MD
- Format: `[DECISION NEEDED]` + Question / Context / Options / Recommendation / Default
- Master has full format including "Default if no response" for async scenarios
- Builder/planning use `notify_parent` to relay decisions up the chain

**7B. Batch Approval — Deferred**
- CLI approval gate (`app/cli/main.py`) is not used when testing via backend+UI
- Backend has no approval gate — `CONFIRM`-tier tools auto-execute over HTTP
- Will implement when UI adds an approval interface

---

## Milestone 8: Inter-Agent Collaboration — DONE

**Status:** Fully implemented. Shared Knowledge Base and Peer Delegation Protocol both operational.

**Goal:** Reduce Master bottleneck for routine coordination. Allow peer-to-peer task handoff within boundaries.

**Depends on:** M2 (safety), M3 (explainability for audit trail)

### 8A. Shared Knowledge Base — Done

- Created `app/agents/shared/KNOWLEDGE.MD` — project-scoped, all agents can append
- `SharedKnowledgeAppendTool` in `tools/memory.py` — append-only, 50-entry cap, secret scrubbing
- Context injection in `context.py` — newest 1500 chars as `## Shared Knowledge` section
- Indexing in `indexer.py` — `index_shared_knowledge()` for `search_memory` retrieval
- Tool registered in `__init__.py`, added to all 7 agent CONFIG.md files

### 8B. Peer Delegation Protocol — Done

- `_parse_delegation_targets()` in `tools/delegation.py` — reads CONFIG.md `delegation_targets:` block
- `SpawnAgentTool.execute()` guard — master/planning unrestricted, others check `delegation_targets`
- Audit trail — `[PEER DELEGATION]` entries logged to master's HEALTH.MD
- CONFIG.md updates: builder→keeper, keeper→builder, cron→builder+keeper
- Builder/keeper got `spawn_agent`, `wait_for_agent`, `check_task_status` tools
- PROMPT.MD updates: builder, keeper (peer delegation sections), master (awareness section)

---

## Milestone 9: Advanced Capabilities — DONE

**Status:** Fully implemented. All 4 sub-features operational.

### 9A. Dynamic Agent Composition — Done

- Created `app/modules/` capability module library with 5 pre-built modules: `file_ops`, `web_research`, `config_management`, `code_analysis`, `memory_management`
- Extended `CreateAgentTool` with `modules` parameter — merges tools and prompt fragments from modules
- `DeleteAgentTool` now promotes LEARNINGS.MD entries to shared KNOWLEDGE.MD before deletion
- Master PROMPT.MD updated with module documentation

**Key files:** `app/modules/__init__.py`, `app/modules/capabilities.py`, `app/utils/tools/agent_mgmt.py`

### 9B. Multi-Modal Input — Done

- `ImageReadTool` — reads image files (PNG/JPG/GIF/WEBP), base64-encodes, returns metadata + data as JSON. 5MB cap.
- `ParseCsvTool` — parses CSV files to markdown tables with column filtering, row limits, and automatic PII scrubbing
- Extended `app/utils/secrets.py` with `scrub_pii()` — detects emails, US phone numbers, credit card numbers, SSNs
- Both tools registered in `TOOL_REGISTRY`, added to builder/master CONFIG.md

**Key files:** `app/utils/tools/file.py`, `app/utils/secrets.py`, `app/utils/tools/__init__.py`

### 9C. Goal Reasoning — Done

- Added `## Goal Reasoning` section to Planning PROMPT.MD with 3-level analysis framework
- Surface instruction → Immediate goal → Underlying intent
- `[GOAL CONFLICT]` escalation when surface and intent conflict
- Sub-goal decomposition with success criteria, prerequisites, and complexity estimates
- Progress tracking after sub-agent results
- Decision logging updated to include intent analysis

**Key files:** `app/agents/planning/PROMPT.MD`

### 9D. Resource & Cost Governance — Done

- Added `budget_per_task_usd`, `budget_per_agent_usd`, `cost_runaway_multiplier` to Settings
- Budget enforcement in `BaseAgent.run_stream_with_tools()` — checks both per-agent and per-task limits after each turn
- Runaway detection in `DoctorAgent._detect_runaway_agents()` — flags agents exceeding multiplier × median cost
- Cost dashboard: `GET /metrics/usage` (all agents) and `GET /metrics/usage/{name}` (single agent)

**Key files:** `app/config/settings.py`, `app/agents/base/__init__.py`, `app/agents/doctor/agent.py`, `app/backend/routers/metrics.py`

---

## Dependency Graph

```
M1: Memory + Search
 └─► M6: Agent Learning (needs search_memory)

M2: Safety Baseline
 ├─► M4: Self-Healing (needs uncertainty handling)
 ├─► M5: Proactive Behavior (needs safety checks)
 └─► M8: Inter-Agent Collaboration (needs sandbox + tests)

M3: Explainability
 └─► M8: Inter-Agent Collaboration (needs audit trail)

M4 + M5 + M6 + M7 ─► M9: Advanced Capabilities ✓
```

**Rule:** A milestone may not begin until all its dependencies are verified working.

---

## Verification Checklist

After each milestone, run these checks before proceeding:

```bash
# After M1
sqlite3 data/yapoc.db "SELECT COUNT(*) FROM memory_entries;"
sqlite3 data/yapoc.db "SELECT agent, status FROM tasks ORDER BY id DESC LIMIT 5;"
poetry run pytest tests/test_db.py tests/test_embeddings.py -v

# After M2
poetry run pytest tests/ -v  # all tests pass
# Manual: give builder a vague task → should escalate with [UNCERTAIN]
# Manual: give builder a clear task → should proceed normally

# After M3
# Run a planning→builder task, then check ticket trace for decision rationale

# After M4
# Kill a running agent mid-task → Doctor detects within 5 min
# Simulate a tool timeout → agent retries once, then tries alternative

# After M5
# Let system run for 30 min → Doctor reports any stale tasks or cross-agent patterns
```
