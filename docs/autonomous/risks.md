# Risks — What's Fragile, What's Dangerous, What Breaks First

This document is not a roadmap. It is an honest inventory of what is
currently wrong, dangerous, or likely to fail. Read this before building
anything new.

Last updated: 2026-04-13 (project age: ~1 week)

---

## Critical (blocks autonomy, or causes damage if ignored)

### R1. The API boundary is synchronous

`POST /task` awaits the full agent execution and returns the response.
This means:

- Closing the browser kills the task
- Server restart loses in-flight work
- Only one task runs per HTTP connection
- The entire "fire and forget" promise is broken at the entry point

Every document in this directory assumes this is fixed. It is not.
**Phase 1 of the roadmap exists specifically to fix this.**

Until this is fixed, YAPOC is a request-response system with extra steps.

**Risk:** User believes task is running autonomously. It is not.
Closing the browser silently kills it. No error, no recovery, no notification.

**Files affected:** `app/backend/routers/tasks.py`, `app/backend/main.py`

---

### R2. CONFIRM-tier tools auto-execute over HTTP with no approval gate

The agentic roadmap (M7B) states explicitly:
> "Backend has no approval gate — CONFIRM-tier tools auto-execute over HTTP."

This means `shell_exec`, `file_delete`, `file_write` to any path, and
`kill_agent` all execute without user confirmation when triggered through
the backend (which is the primary path now that the UI is the main interface).

**Risk:** An agent running autonomously (Doctor, Cron, or a goal-driven task)
can execute destructive shell commands with no human in the loop. A single
hallucinated `rm -rf` or `git push --force` has no guardrail.

Currently survivable because nothing runs truly autonomously yet (R1 blocks it).
**The moment R1 is fixed, R2 becomes actively dangerous.**

**Files affected:** `app/utils/tools/__init__.py` (SandboxPolicy),
`app/agents/base/__init__.py` (_execute_tool)

---

### R3. No structured event channel from agents to UI

The UI has rendering components for streaming (`ThinkingBlock.tsx`,
`ToolCallBlock.tsx`, `MessageBubble.tsx`). The agents emit logs.
But there is no protocol connecting them.

Agent subprocesses write to log files. The backend does not read these
in real-time and relay them via WebSocket. The Chat tab cannot show
thinking blocks, tool calls, or streaming responses during execution.

**Risk:** No risk of damage, but this is the entire Claude Code experience.
Without it, the Chat tab is a text box that submits a task and shows a
final response. It feels like a form submission, not a conversation.

**Files affected:** `app/agents/base/__init__.py` (needs event emission),
`app/backend/websocket.py` (needs event relay)

---

## High (will cause problems as the system matures)

### R4. Prompt engineering is the only behavioral guardrail

Agent behavior is controlled by PROMPT.MD files — long natural-language
instructions. These work well with Claude Sonnet 3.5/4, but:

- A different model (Ollama, OpenAI) may interpret instructions differently
- Long prompts get compressed during context compaction — instructions can be lost
- Under complex multi-step tasks, agents sometimes ignore constraints
- There are no programmatic checks that enforce delegation rules, budget limits,
  or escalation policies beyond what the LLM chooses to do

Examples of things controlled only by prompt:
- "Do not modify another agent's PROMPT.MD" — no code enforces this
- "Escalate with [DECISION NEEDED] when uncertain" — optional, LLM decides
- "Call add_task_trace before non-trivial decisions" — optional, LLM decides
- "Check LEARNINGS.MD before complex tasks" — optional, LLM decides

The sandbox enforces file path restrictions programmatically. Nothing else is.

**Risk:** An agent using a cheaper model (haiku, ollama local) ignores
behavioral instructions that a frontier model follows. The system degrades
silently — no error, just wrong behavior.

**Mitigation path:** Add programmatic guards in `_execute_tool()` and
`SpawnAgentTool` that enforce hard rules regardless of what the LLM requests.

---

### R5. Single-process control plane

Everything runs in one uvicorn process:

```
uvicorn
├── HTTP handlers
├── WebSocket manager
├── APScheduler (cron ticks)
├── dispatcher_loop() (when built)
├── notification_listener() (when built)
└── indexer_tick()
```

Agent subprocesses are separate, but the control plane is monolithic.

**Risk scenarios:**
- A blocking operation in a route handler freezes WebSocket delivery
- APScheduler callback raises → cron ticks stop silently
- Memory leak in the indexer grows until OOM kills the process
- An uncaught exception in the dispatcher loop stops all task dispatching

**Risk:** For personal use this is fine. For "overcome OpenClaw" ambitions,
a single process death takes everything down — agents, scheduling, UI,
notifications. There is no supervisor restarting the process automatically.

(`yapoc-supervisor.sh` exists in the project root but its status is unclear.)

**Mitigation path:** `systemd` user service with `Restart=always` for
the immediate term. Process separation (gateway vs executor) long-term.

---

### R6. Testing covers infrastructure but not behavior

39+ tests exist and pass. They cover:

- SQLite schema, queries, FTS, vector search (test_db.py)
- Secret scanning patterns (test_secrets.py)
- Sandbox path enforcement (test_sandbox.py)
- Context assembly and config parsing (test_context.py)
- Embedding shape and similarity (test_embeddings.py)
- Doctor proactive detection (test_doctor_proactive.py)
- Learnings system (test_learnings.py)
- Tool retry logic (test_tool_retry.py)

What is NOT tested:

- Master → Planning → Builder delegation chain (does it actually work end-to-end?)
- Notification chain completion (does notify_parent propagate correctly through 3 levels?)
- Agent error recovery (does Planning actually retry when Builder fails?)
- Concurrent agent execution (do two tasks running simultaneously interfere?)
- TASK.MD race conditions (what happens if dispatcher writes while runner reads?)
- Context compaction under real load (does haiku produce usable summaries?)
- Session persistence and reload (does a session restore correctly after restart?)

**Risk:** Infrastructure works perfectly. Agent behavior is verified only
by manual testing. A refactor to BaseAgent, the notification queue, or the
spawn registry could break the agent pipeline with no test catching it.

**Mitigation path:** One end-to-end test that submits a task via POST /task,
verifies master delegates to planning, planning to builder, builder calls
notify_parent, and the result reaches the task store. This single test
covers the critical path.

---

## Medium (worth tracking, not urgent)

### R7. Backend-frontend connection is "50-50"

The user's own assessment. The UI sometimes connects to the backend,
sometimes doesn't. This suggests:

- CORS or WebSocket origin issues
- Race conditions on startup (UI connects before backend is ready)
- State sync failures (UI shows stale data after reconnect)
- Possibly: Vite dev server proxy vs production build differences

**Risk:** The primary interface is unreliable. Users fall back to CLI,
which defeats the purpose of Mission Control as the main entry point.

---

### R8. Agent file state can diverge from task store

Two sources of truth exist:

- **Task Store (SQLite):** `tasks` table with status, result, timestamps
- **Agent TASK.MD files:** status field in the markdown file

The dispatcher (when built) will bridge these. But currently, if an agent
updates its TASK.MD to "done" and the backend doesn't read it, the task
store still says "running." The Dashboard shows the wrong state.

**Risk:** User sees a task as "running" when it finished minutes ago.
Or sees "done" when the agent is still working. State divergence erodes
trust in the Dashboard.

**Mitigation path:** The dispatcher design (execution-engine.md) addresses
this. The dispatcher is the single writer to TASK.MD and the single reader
of notify_parent results. Build it.

---

### R9. No rate limiting on agent API calls

Agents call LLM APIs in a loop: reason → tool call → reason → tool call.
There are per-task limits (`max_turns`, `task_timeout`) but:

- No global rate limit across agents
- No daily budget enforcement (designed in safety.md, not implemented)
- No circuit breaker if the API returns 429s repeatedly
- ~~Cost tracking exists but is observational (logs cost, doesn't enforce limits)~~

> **Updated (M9D):** Per-task and per-agent budget limits now enforced in
> `run_stream_with_tools()`. `budget_per_task_usd` and `budget_per_agent_usd`
> settings with hard stops. Runaway detection built in Doctor. Daily autonomous
> budget still not implemented (Phase 4).

**Risk:** ~~A goal-driven or cron-triggered loop that retries failed tasks
could burn through API credits while the user is asleep.~~ Per-task limits
mitigate the worst case. Daily autonomous budget (Phase 4) will close the
remaining gap for cron/goal-driven work.

---

### R10. Memory and context files grow without bounds

MEMORY.MD, NOTES.MD, HEALTH.MD, and LEARNINGS.MD are append-only.
The future_development.md document proposes archiving and splitting,
but none of it is implemented.

- MEMORY.MD: every task appends a line. After 1000 tasks, this file is huge.
- HEALTH.MD: every error appends. An agent in a failure loop fills this fast.
- Context compaction exists (haiku summarizer at 85% fill) but doesn't
  prevent the source files from growing.

**Risk:** Agent context windows fill with old, irrelevant information.
Cost increases. Response quality decreases. Eventually, files are too
large to read in a single tool call.

---

## Low (cosmetic or long-term)

### R11. ~~No structured logging~~ Structured logging exists

> **Updated (M9):** Agents use loguru with structured binds throughout BaseAgent:
> `agent=`, `event=`, `turn=`, `model=`, `cost_usd=`. Consistent format across
> all agent activity. Backend still uses uvicorn's default logger.

**Risk:** Largely mitigated. Agent-side logging is structured. Backend logging
could be improved but is not a blocker.

---

### R12. The name "YAPOC" undersells the project

"Yet Another OpenClaw" positions the project as a derivative. The
architecture is fundamentally different from OpenClaw — hierarchical
agent orchestration vs gateway + plugin model. The self-healing,
self-directing capabilities are original work.

**Risk:** Perception, not technical. If the project goes public,
the name invites comparison on OpenClaw's terms rather than YAPOC's.

---

## Risk priority matrix

```
              DAMAGE IF IGNORED
              Low          High
         ┌────────────┬────────────┐
  LIKELY  │ R10, R11   │ R1, R2     │  ← fix these first
  TO HIT  │            │ R4         │
         ├────────────┼────────────┤
  LESS    │ R12        │ R3, R5     │
  LIKELY  │            │ R6, R7     │
         ├────────────┼────────────┤
  ONLY    │            │ R8, R9     │
  AT      │            │            │
  SCALE   │            │            │
         └────────────┴────────────┘
```

**Fix order:**
1. R1 (sync API) — unlocks everything
2. R2 (tool approval) — becomes dangerous the moment R1 is fixed
3. R3 (streaming) — unlocks the interactive experience
4. R7 (frontend reliability) — unlocks the primary interface
5. R6 (behavioral tests) — prevents regressions as you build
6. Everything else — as needed
