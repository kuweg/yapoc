# YAPOC Roadmap

## TL;DR

This doc covers 10 proposed features for YAPOC and recommends an order. Each section identifies what's already in the codebase, what the work entails, what it depends on, and a rough effort tag. The aim is to make it easy to pick the next thing to build without rereading the audit docs every time.

Headline finding: most features are **partial**, not greenfield. The plugin loader for dynamic tools is already there; vector search infrastructure already runs; the researcher agent dir is scaffolded; observability primitives are scattered but unconsolidated. The two genuinely greenfield items are **git integration** and **approval gates**, both of which gate the riskier features further out.

Sequencing in one line: foundations (memory polish, dynamic tools, observability) → capability unlocks (web research, JSON mode, parallel DAG) → safety & scale (approval gates, git, multi-user) → self-evolution (self-improvement loop).

## At a glance

| # | Feature | State | Effort | Unlocks |
|---|---|---|---|---|
| 1 | Web Browsing & Research Agent | partial | M | Live information, doc lookups |
| 2 | Vector Memory (semantic search) | partial | S | Cross-session learning, retrieval over notes |
| 3 | Git Integration | none | L | Safe destructive ops, rollback |
| 4 | Human-in-the-Loop Approval Gates | none | L | Production safety |
| 5 | Multi-User & Session Persistence | partial | M | Platform mode |
| 6 | Dynamic Tool Creation | partial | S | Self-extending capability |
| 7 | Structured Output / JSON Mode | partial | M | Reliable agent-to-agent handoff |
| 8 | Observability Dashboard | partial | M | Debugging, cost visibility, foundation for #10 |
| 9 | Parallel DAG Executor | partial | M | Faster complex tasks |
| 10 | Self-Improvement Loop | partial | L | Auto-tuning, needs #8 |

S = under one day · M = 1–3 days · L = 1–2 weeks. Estimates assume one engineer familiar with the code.

## Recommended sequencing

Four phases. Each phase is internally parallelizable; later phases assume earlier ones are landed.

### Phase 1 — Foundations
- **#2 Vector memory polish** (S) — infra is built; just needs tuning, eviction policy, and a UI surface.
- **#6 Dynamic tool creation** (S) — plugin loader is already running at startup; needs an agent-facing flow to author + register.
- **#8 Observability dashboard** (M) — pull together LIVE.MD, COSTS.json, metrics router into one frontend tab.

Reason for ordering: these are independent of each other and unlock everything downstream. **#8 specifically is a hard prerequisite for #10** (self-improvement needs signal). **#6** lets later features ship as plugins rather than core edits.

### Phase 2 — Capability unlocks
- **#1 Web research agent** (M) — researcher dir is scaffolded; add a page-fetch tool and wire it up.
- **#7 JSON mode** (M) — model registry already tracks support; thread `response_format` through `AgentConfig` and the 8 adapters.
- **#9 Parallel DAG executor** (M) — `wait_for_agents` exists; add a DAG type + topo sort on top of the dispatcher.

These three are roughly independent. **#7 cleans up agent-to-agent handoff before #9 starts running them in parallel**, so do #7 first if you only pick one Phase-2 item.

### Phase 3 — Safety & scale
- **#4 Approval gates** (L) — backend pause/resume, frontend approval UI, per-tool policy.
- **#3 Git integration** (L) — git tool, branch-per-task, rollback hook.
- **#5 Multi-user** (M) — user model, auth middleware, per-user task isolation.

**#3 and #4 must land before #10.** Self-modifying systems without rollback and human gating are how bad weekends happen. #5 is independent but expensive to retrofit, so doing it before #10 keeps the surface area smaller.

### Phase 4 — Self-evolution
- **#10 Self-improvement loop** (L) — depends on #8 (signals) and #3/#4 (safety). Defer until the others are stable.

---

## Per-feature detail

### 1. Web Browsing & Research Agent

**Goal.** A dedicated agent that can search the web and read pages, callable by master for research tasks.

**Current state.** `app/agents/researcher/` is fully scaffolded (`agent.py`, `CONFIG.yaml`, all six markdown files). `WebSearchTool` at `app/utils/tools/web.py` does DuckDuckGo + HTML fallback. Missing: a tool that fetches a URL and returns clean text content (the "read the page" half of research).

**Scope.**
- Add `FetchPageTool` to `app/utils/tools/web.py` — accepts URL, returns extracted main content (readability-style strip).
- Wire researcher's `CONFIG.yaml` to include both `web_search` and `fetch_page`.
- Add researcher to master's `delegation_targets` so master can spawn it.
- Add a minimal prompt template in `app/agents/researcher/PROMPT.MD` that frames the role.

**Dependencies.** None to start. Becomes much better with #2 (so research findings persist as searchable knowledge) and #7 (so master receives structured research, not just markdown).

**Effort.** M — one new tool, one agent wire-up, prompt tuning.

**Key files.** `app/agents/researcher/`, `app/utils/tools/web.py`, `app/agents/master/CONFIG.yaml` (delegation_targets), `pyproject.toml` (likely add `readability-lxml` or `trafilatura`).

---

### 2. Vector Memory (semantic search)

**Goal.** Agents can semantically retrieve past decisions, notes, and conversations across sessions, not just grep their own `MEMORY.MD`.

**Current state.** Genuinely close to done. `app/utils/embeddings.py` wraps `sentence-transformers` (`all-MiniLM-L6-v2` by default). `app/utils/indexer.py` runs as an APScheduler job and indexes content into SQLite + FTS via `app/utils/db.py`. `SearchMemoryTool` in `app/utils/tools/search.py` does hybrid semantic + keyword search. Embeddings dep already in `pyproject.toml`.

**Scope.**
- Confirm which agents have `search_memory` in `CONFIG.yaml` — gate at least master, planning, researcher.
- Tune the indexer's source set: are NOTES.MD, MEMORY.MD, LEARNINGS.MD all indexed? Check `indexer.py` and extend if needed.
- Surface "recent retrievals" in the frontend Memory tab so the user can see what was recalled.
- Document the retrieval contract in `app/utils/tools/CLAUDE.md`.

**Dependencies.** None. Stands alone.

**Effort.** S — polish + UI, no new core infra.

**Key files.** `app/utils/embeddings.py`, `app/utils/indexer.py`, `app/utils/db.py`, `app/utils/tools/search.py`, `app/frontend/src/memory-graph/`.

---

### 3. Git Integration

**Goal.** Safety net for file mutations: auto-commit before destructive changes, optional branch-per-task, rollback when something goes wrong.

**Current state.** None. CLI's `/diff` (in `app/cli/main.py`) shells out to `git diff` for display only. No tool, no service.

**Scope.**
- New `git_tool` in `app/utils/tools/` with operations: `commit`, `branch_create`, `branch_switch`, `rollback_to`, `status`. Runs via `subprocess` against the repo at `settings.project_root`.
- Auto-commit hook on `FileWriteTool` / `FileEditTool` / `FileDeleteTool`: before mutating, ensure a clean snapshot commit exists with a "pre-<tool>:<agent>" message.
- Branch-per-task: optional mode where each task starts a `task/<task_id>` branch; merge to main on success, leave on failure for inspection.
- Surface in the frontend: per-session "rollback to last commit" button.

**Dependencies.** None. Hard prerequisite for **#10**.

**Effort.** L — design choices around merge strategy, branch policy, and what counts as a "task".

**Key files.** `app/utils/tools/` (new file `git.py`), `app/utils/tools/file.py` (mutation hooks), `app/config/settings.py` (policy flags), `app/cli/main.py` (review existing `/diff`).

---

### 4. Human-in-the-Loop Approval Gates

**Goal.** Pause agent execution and ask the user before risky operations (file deletes, shell, config edits, agent spawns).

**Current state.** None. CLAUDE.md explicitly: *"All tools execute immediately without approval prompts."* `SpawnAgentTool` has a delegation-authorization check (agent X is allowed to spawn agent Y) but no human gate.

**Scope.**
- Approval policy in `app/config/settings.py` or per-agent `CONFIG.yaml`: per-tool flags like `require_approval: true`.
- Backend pause primitive: when a guarded tool fires, write a pending-approval entry to a new SQLite table, suspend the run, push a WebSocket event to the UI.
- Frontend approval queue: a modal or panel that surfaces pending approvals with tool name, args, agent context; user clicks approve/deny; backend resumes or aborts.
- Timeout policy: pending approvals auto-deny after N seconds (configurable).

**Dependencies.** None to start. Hard prerequisite for **#10**.

**Effort.** L — touches `BaseAgent.run_stream_with_tools`, dispatcher, WebSocket layer, frontend.

**Key files.** `app/agents/base/__init__.py` (tool-call loop), `app/utils/tools/__init__.py` (gate hook), `app/backend/main.py` (WS event), `app/backend/routers/` (new approvals router), `app/frontend/src/`.

---

### 5. Multi-User & Session Persistence

**Goal.** Different users see different sessions; sessions survive backend restarts.

**Current state.** Partial. Frontend persists sessions to localStorage via Zustand (`app/frontend/src/store/session.ts`). CLI persists to JSONL (`app/cli/sessions.py`). Backend `app/backend/routers/sessions.py` is stateless (just summarization). No auth, no user model, `session_id` flows through requests but is not authorized.

**Scope.**
- SQLite users table; minimal auth (API token in header is enough for v1).
- Move session storage to backend SQLite (one table) instead of frontend localStorage; frontend hits an API.
- Per-user task isolation in the dispatcher so user A doesn't see user B's queue.
- Session list API (already implied by the Sessions tab — wire to backend).

**Dependencies.** None hard, but easier before **#10**.

**Effort.** M — schema + auth + frontend migration; nothing architecturally new.

**Key files.** `app/utils/db.py` (schema), new `app/backend/auth.py`, `app/backend/routers/sessions.py` (extend), `app/cli/sessions.py`, `app/frontend/src/store/session.ts`.

---

### 6. Dynamic Tool Creation

**Goal.** Agents can write a new Python tool and have it registered without a backend restart.

**Current state.** Already most of the way there. `app/utils/tools/plugin_loader.py` scans `plugins/` for `.py` files, imports them, finds `BaseTool` subclasses, registers them in `TOOL_REGISTRY`. Called at startup in `app/backend/main.py` lifespan.

**Scope.**
- An agent-facing convention: when builder writes a new tool to `plugins/<name>.py`, the plugin loader can be re-run to pick it up. Either expose a `reload_plugins` admin endpoint or use a filesystem watcher.
- A tool template in `app/utils/tools/CLAUDE.md` showing the minimal `BaseTool` subclass.
- Sandboxing: plugin tools run with the same permissions as core tools today. Document this; consider per-plugin authorization once #4 lands.
- Surface plugin tools in the frontend's tool inventory.

**Dependencies.** None functionally. Pairs naturally with **#4** so new-tool execution is gated.

**Effort.** S — small plumbing, mostly docs and an admin reload endpoint.

**Key files.** `app/utils/tools/plugin_loader.py`, `app/utils/tools/CLAUDE.md`, `plugins/`, `app/backend/main.py`.

---

### 7. Structured Output / JSON Mode

**Goal.** Agents return structured JSON instead of free-form markdown when a downstream consumer needs it. Makes agent-to-agent handoff reliable.

**Current state.** Partial. The model registry (`app/utils/adapters/models/anthropic.py`, `openai.py`, `deepseek.py`, etc.) marks `supports_json_mode: bool` per model. But `AgentConfig` in `app/utils/adapters/base.py` has no `response_format` field, and none of the 8 adapters pass `response_format` to their provider SDK.

**Scope.**
- Add `response_format: Literal["text", "json"] | None` to `AgentConfig`.
- Update each adapter (`anthropic.py`, `openai.py`, `deepseek.py`, `openrouter.py`, `google.py`, `ollama.py`, `lmstudio.py`, `codex.py`) to thread `response_format` to its API call when the model supports it; fall back to "respond in JSON" prompt nudge otherwise.
- Per-call override: allow `run_stream_with_tools(json_mode=True)`. Useful for one-off structured asks without changing agent config.
- Validation utility: pydantic schema check on the response before returning.

**Dependencies.** None. Best landed before **#9** so DAG handoff has typed contracts.

**Effort.** M — 8 adapters to touch, but each is mechanically simple.

**Key files.** `app/utils/adapters/base.py`, `app/utils/adapters/*.py`, `app/utils/adapters/models/*.py`, `app/agents/base/__init__.py`.

---

### 8. Observability Dashboard

**Goal.** One frontend tab that shows real-time agent traces, token/cost usage, and success/failure rates.

**Current state.** Primitives are scattered. Each agent writes `LIVE.MD` (token-by-token output buffer) via its runner. Per-agent `COSTS.json` tracks task-level cost. `app/utils/cost_tracker.py` tracks token/cost per call. `app/backend/routers/metrics.py` exposes a metrics endpoint. Frontend has `CostBar.tsx` per chat, `AgentCard.tsx` per agent on the dashboard. Nothing unifies these.

**Scope.**
- Aggregation endpoint in `app/backend/routers/metrics.py`: per-agent rollups (cost, tokens, success rate, average duration).
- Trace-stream endpoint: SSE/WebSocket subscription to per-agent LIVE.MD updates.
- New frontend tab "Observability" that shows: live trace viewer (select an agent, watch its turns), cost-over-time chart, agent leaderboard (highest cost, slowest, most errors).
- Surface failed turns: a feed of recent tool errors and exceptions across all agents.

**Dependencies.** None. **Hard prerequisite for #10** (self-improvement needs signal).

**Effort.** M — backend aggregation is straightforward; the frontend lift is the real cost.

**Key files.** `app/backend/routers/metrics.py`, `app/utils/cost_tracker.py`, `app/utils/db.py`, `app/agents/base/runner.py` (LIVE.MD writer), `app/frontend/src/agent-status/`, new `app/frontend/src/observability/`.

---

### 9. Parallel DAG Executor

**Goal.** Independent subtasks run in parallel automatically based on a dependency graph, not sequentially or via manual `wait_for_agents` calls.

**Current state.** Partial. `wait_for_agents` (plural) exists in `app/utils/tools/delegation.py` and polls multiple agents via `asyncio.gather` with a `fail_fast` option. `app/backend/dispatcher.py` already runs up to `settings.max_concurrent_tasks` (default 3) in parallel. No DAG planning, no topological scheduler.

**Scope.**
- DAG data model: a plan is a graph of nodes (task descriptions) with dependency edges.
- Planning agent updated to emit DAGs (instead of, or in addition to, linear plans).
- Executor service that walks the DAG: launches nodes whose dependencies are satisfied, waits on `wait_for_agents`, marks complete, repeats until done.
- Failure modes: half-completed DAG, retry policy, partial-result aggregation.
- Surface in observability: render the DAG with per-node status.

**Dependencies.** Better with **#7** (typed handoffs between nodes). Surface improves with **#8**.

**Effort.** M — the underlying primitives exist; the new work is the DAG type, the executor loop, and the planning prompt update.

**Key files.** `app/utils/tools/delegation.py` (`wait_for_agents`), `app/backend/dispatcher.py`, `app/agents/planning/`, `app/config/settings.py` (`max_concurrent_agents`, `max_concurrent_tasks`).

---

### 10. Self-Improvement Loop

**Goal.** YAPOC reviews its own performance periodically and proposes config / prompt / agent changes.

**Current state.** Partial scaffolding. `app/agents/model_manager/agent.py` runs `run_model_audit()` on a schedule but is pure Python — no LLM, just config validation. `LearningsAppendTool` (`app/utils/tools/memory.py`) lets an agent append rules to `LEARNINGS.MD`, capped at 20. No feedback scoring, no agent-evaluates-agent loop, no auto-tuning.

**Scope.**
- Success-signal pipeline: derive per-task / per-agent metrics from #8's aggregation (cost vs. baseline, error rate, retry rate).
- Evaluator agent: prompts an LLM to look at the last N tasks, identifies regressions, proposes config / prompt / agent changes.
- Proposal queue: writes proposals to a review queue, surfaced through approval gates (#4) — user approves before applying.
- Apply pipeline: when approved, the keeper agent edits config and the change is git-tracked (#3).

**Dependencies.** **Hard dependencies on #8 (signal), #3 (rollback), #4 (approval).** Soft dependency on keeper agent being more than a stub.

**Effort.** L — design-heavy. Failure modes are subtle (positive feedback loops, gaming the metrics).

**Key files.** `app/agents/model_manager/agent.py`, `app/agents/keeper/`, `app/utils/tools/memory.py` (`LearningsAppendTool`), `app/utils/cost_tracker.py`, new `app/agents/evaluator/`.

---

## Cross-cutting notes

- **Observability is the foundation.** Several features (#9 DAG, #10 self-improvement, even #4 approvals) are dramatically more useful when there's a trace-and-cost view to debug them against. That's why #8 lands in Phase 1.
- **The DAG executor (#9) reshapes the dispatcher.** Today `dispatcher.py` is a flat task queue with concurrency limits. A DAG executor sits above it — the queue becomes "ready nodes only." Worth considering whether this is a refactor or a new layer.
- **Approval gates (#4) need a pause/resume primitive that the backend currently lacks.** Today a `run_stream_with_tools` invocation is a single async function; introducing a checkpoint that survives a wait-for-human is a real change to that signature. Plan accordingly.
- **Self-improvement (#10) has feedback-loop hazards.** Without #4 + #3, a misaligned evaluator can degrade the system fast. The sequencing puts those guards first for that reason, not because of effort.
- **Plugin loader (#6) is a nice abstraction to lean into.** Several follow-on features could ship as plugins rather than core changes — keep this in mind when scoping later work.

## Out of scope for this doc

- Per-feature implementation plans. When you pick a feature, ask for an implementation plan and that becomes its own document.
- Features beyond the 10 listed.
- Architectural overhauls not implied by a feature (e.g. swapping Redis, changing the agent topology).
- Specific model / prompt / temperature tuning beyond what each feature explicitly requires.
