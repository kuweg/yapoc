# YAPOC Runtime Audit

> Snapshot of the agent runtime as of 2026-05-16. Captures how agents are spawned, kept alive, communicate, and recover — and where the gaps are for "truly alive" autonomous behavior.

---

## TL;DR

YAPOC is a **file-based hierarchical multi-agent system** with an optional Redis event bus layered on top. Master runs in-process with the FastAPI server; sub-agents are spawned on demand as subprocesses, woken by a watchdog/polling/Redis-inbox combo, and self-terminate after an idle timeout. There is **no supervisor** — crashed agents stay dead until manually respawned — and shared markdown files (`MEMORY.MD`, `NOTES.MD`, `LEARNINGS.MD`) are written without locking. Redis adds real-time event streaming when present and falls back to file-based queues when not.

What works: graceful degradation (Redis → file-queue fallback for result delivery), watchdog-based task wakeup, autonomous Doctor/Model-Manager schedules.
What doesn't: no auto-respawn, no agent pooling/pre-warm, no peer-to-peer comms, no priority queueing, no resource limits, no test coverage.

---

## 1. Agent Lifecycle & Process Model

### Process model — mixed

- **Master Agent** (`app/agents/master/agent.py`): in-process singleton inside the FastAPI process. PID == server PID. Initialized once at server startup.
- **Sub-agents** (planning, builder, keeper, doctor, cron, model_manager): spawned as subprocesses via `Popen(..., start_new_session=True)`. Entry script: `yapoc-agent --agent <name>` → `app/agents/base/runner_entry.py`.
- **Doctor & Model Manager**: APScheduler triggers, not continuously running. Doctor every 5 min (`settings.doctor_interval_minutes`), Model Manager every 24 hr (`settings.model_manager_interval_hours`).

### Task detection — watchdog + polling + Redis hybrid

`AgentRunner` (`app/agents/base/runner.py`) wakes on whichever fires first:

1. **Watchdog** — `_TaskFileHandler` observes `TASK.MD` via `watchdog.observers.Observer`. Fires immediately on file modification.
2. **Polling fallback** — every `settings.runner_poll_interval` seconds (default 30s).
3. **Redis inbox stream** (optional) — `agent:{name}:inbox` consumer group reads `task_assign`, `kill`, `prepare_shutdown`, `task_result` messages. Falls back silently to watchdog+polling if Redis is unavailable.

### Two TASK.MD formats

| Form | Used by | Shape |
|------|---------|-------|
| **Raw** plain text | Master (called from CLI/HTTP directly) | Free-form prompt |
| **Structured** frontmatter + sections | Spawned sub-agents | YAML frontmatter (`status`, `assigned_by`, `task_id`, `session_id`, `assigned_at`, `completed_at`, `consumed_at`) + `## Task` / `## Context` / `## Result` / `## Error` |

### Main loop (sub-agents)

`AgentRunner.run()`:

1. Writes initial `STATUS.json` atomically (`tempfile + os.replace`): `{"state": "spawning", "pid": ...}`.
2. Sets up watchdog observer + Redis inbox consumer.
3. Loop:
   - Wait for TASK.MD modification, inbox message, or poll timeout.
   - `_check_task()` reads frontmatter; if `status: pending`, runs `_run_task()` which calls `BaseAgent.run_stream_with_tools(manage_task_file=False)`.
   - Rewrites `STATUS.json` with `state: running`.
   - **Heartbeat** every 30s keeps `idle_since: null` during long tasks.
   - Publishes result to parent via `_notify_parent_via_bus()` — tries Redis stream, falls back to file-based `NotificationQueue`.
   - Self-terminates after `agent_idle_timeout` (default 900s / 15 min, per-agent overridable in `app/config/agent-settings.json`).
4. **Temporary agents**: if `CONFIG.md` has `lifecycle.temporary: true`, exits immediately after one task.
5. **Signals**: SIGTERM/SIGINT marks STATUS.json `terminated` and notifies parent before exiting.

### Context assembly (per turn)

`build_system_context()` (`app/agents/base/context.py:61`) rebuilds system prompt on every LLM turn — no caching. Reads:

1. Full `PROMPT.MD`
2. Last `context_memory_limit` lines of `MEMORY.MD` (default 10)
3. `NOTES.MD` capped at `context_notes_limit` chars (default 3000)
4. Last `context_health_limit` lines of `HEALTH.MD` (default 5)
5. `LEARNINGS.MD` if present
6. Shared `KNOWLEDGE.MD` (visible to all agents)

Joined by `\n\n---\n\n`. This adds per-turn disk I/O but lets agents pick up CONFIG/NOTES/MEMORY changes immediately.

### Death & restart

- **Crash capture**: `runner_entry.py` wraps `AgentRunner.run()` in try/except → writes `CRASH.MD` via `app.utils.crash.write_crash_report()`.
- **Stale cleanup on server boot**: `_cleanup_stale_agent_statuses()` (`app/backend/main.py:27`) walks STATUS.json files. If `state` is idle/running/spawning but PID is dead → marks `terminated` and clears stale TASK.MD.
- **No auto-respawn.** Crashed agents stay dead. Recovery is manual (`kill_agent` + `spawn_agent`) or via server restart.

---

## 2. Inter-Agent Communication

### File-based persistence layer

Each agent directory under `app/agents/<name>/` carries:

| File | Role |
|------|------|
| `TASK.MD` | Task body + frontmatter status |
| `RESULT.MD` | Final LLM response from last task |
| `MEMORY.MD` | Append-only episodic log |
| `NOTES.MD` | Persistent knowledge |
| `HEALTH.MD` | Error log |
| `CRASH.MD` | Subprocess crash reports |
| `STATUS.json` | Live process state (PID, state, idle_since) |
| `LIVE.MD`, `OUTPUT.MD`, `USAGE.json`, `COSTS.json` | Streaming output, usage, costs |

### Parent → child task assignment

`SpawnAgentTool` (`app/utils/tools/delegation.py:207`):

1. **Auth check**: master can spawn anyone; other agents need target listed in their `CONFIG.md delegation_targets:`.
2. **Live agent cap**: refuses if `_count_live_agents() >= settings.max_concurrent_agents` (default 10).
3. **Reuse-if-idle**: reads child STATUS.json — if `state: idle` and PID alive, rewrites TASK.MD (watchdog picks up); otherwise spawns subprocess.
4. Writes structured TASK.MD with `status: pending`, `assigned_by`, `session_id`, `task_id`, `assigned_at`.
5. Polls child's TASK.MD `status:` up to `settings.agent_spawn_timeout` (default 60s) for confirmation, then returns. Result comes back asynchronously.

### Child → parent result delivery

Two distinct mechanisms, not three redundant ones:

**Push — child notifies parent (`_notify_parent_via_bus`, `runner.py:513`).** One channel fires per task, with fallback:

1. **Redis inbox stream** (primary) — `bus.stream_add(f"agent:{parent}:inbox", {"type": "task_result", ...})`. Parent's runner consumes via `XREADGROUP {parent}_group`.
2. **File-based notification queue** (fallback when Redis is down/times out) — writes to `data/notification_queue.json` (fcntl-locked, dedup). `NotificationPoller` (`app/backend/services/notification_poller.py:114`) scans every 30s for `status: done|error` + no `consumed_at`, enqueues, wakes parent.

These two are mutually exclusive per delivery — Redis first, file-queue only if Redis fails.

**Pull — parent observes child directly (`wait_for_agent` tool, `delegation.py:522`).** Independent of the push path. Parent polls child's `TASK.MD status:` frontmatter up to 300s (default). Used when the parent wants to block on a specific child rather than continue and handle the eventual notification.

### Master notification watcher (special case)

`_master_notification_watcher()` (`app/backend/main.py:92`) is an asyncio background task — **not** an AgentRunner. Every 3s:

- Checks master TASK.MD for trigger body `[Process incoming notifications from sub-agents]`.
- If pending notifications exist (`notification_queue.pending_count("master") > 0`), invokes `master_agent.handle_task_stream()` with **destructive tools blocked** (`spawn_agent`, `kill_agent`, `server_restart`, `shell_exec`).
- Drains queue only after master's turn succeeds (so failures retrigger).
- Publishes master's response to WebSocket for the UI chat panel.

### Message bus internals (`app/backend/message_bus.py`, `relay.py`)

- **Streams (guaranteed delivery)**: `agent:{name}:inbox` consumer groups. Messages persist until ACK; survive process death.
- **Pub/sub (fire-and-forget)**:
  - `session:{id}:events` — text deltas, tool calls, thinking, usage
  - `agent:{name}:status` — state changes
  - `system:health` — Doctor alerts
  - `system:tasks` — global task lifecycle events
- **Outbox fallback**: if Redis down, `stream_add()` buffers to `.outbox.jsonl`; drains FIFO on reconnect.
- **MessageBusRelay** (`relay.py`): asyncio task subscribes to pub/sub channels, forwards to WebSocket clients via `ws_manager.push_event()`. Throttles text deltas to 10/sec.

---

## 3. Long-Running / Autonomous Behavior

### Doctor (every 5 min, programmatic)

`run_health_check()` — **no LLM**, pure Python:
- Walks all agents' HEALTH.MD, CRASH.MD, OUTPUT.MD.
- Prunes HEALTH.MD entries older than `settings.health_log_retention_days` (default 7).
- Detects repeated timeouts (≥3), high error rate (≥5), stale running tasks (> 2× `task_timeout`), crashed processes (STATUS=terminated + TASK=running).
- Writes rolling `HEALTH_SUMMARY.MD` (overwritten each run).
- Publishes alerts to Redis `system:health`.

Doctor can also be spawned ad-hoc by master for LLM-driven diagnostics.

### Cron Agent (stub)

Real cron lives in APScheduler (`main.py:_cron_scheduler_tick`, every 10 min): parses `cron/NOTES.MD` entries (`job_name: cron_expression`), uses `app.utils.cron_parser`, creates `task_queue` rows for due jobs.

### Model Manager (every 24 hr)

`run_model_audit()` scans `app/config/agent-settings.json` and per-agent CONFIG.md for typos / unavailable models. Reports to master inbox.

### Goal-driven autonomous tasks

`dispatcher.py:_check_goals()` polls master `GOALS.MD` every 60s when no user/system task is running. Finds first `- [ ]` in `## Active`, creates a `task_queue` entry with `source: goal`. Capped by `settings.budget_per_autonomous_task_usd`.

### Continuous activation summary

| Component | Lifetime |
|-----------|----------|
| Master | Always alive (in-process) |
| Doctor / Model Manager | Always scheduled, only run on trigger |
| Cron / dispatcher | Always-on asyncio loops |
| Other sub-agents | Spawned on demand, idle-terminate after 15 min |

No agent runs **continuously** outside Master.

---

## 4. State Persistence

### Sessions

JSONL in `app/agents/master/sessions/{session_id}.jsonl`. Session id format: `YYYYMMDD-HHMMSS-{6hex}`.

### Cost & usage

- **Lifetime per agent**: `USAGE.json` (`total_input_tokens`, `total_output_tokens`, cache tokens, `total_tool_calls`, `total_turns`, `total_cost_usd`). Updated by `UsageTracker.record_turn()`.
- **Per-task**: `COSTS.json` (array of `task_id`, description, tokens, cost_usd, timestamp, model_used).
- **CLI session**: `TurnRenderer._session_cost` in-memory, printed per turn.
- **Budget**: `settings.budget_per_autonomous_task_usd` (default 0 = unlimited). `dispatcher.py:is_autonomous_budget_exhausted()` gates cron/goal/doctor tasks.

### Task queue (SQLite)

Table `task_queue`: `id, prompt, source (ui|webhook|cron|goal|doctor), status, result, error, session_id, metadata, started_at, completed_at`. Polled by `dispatcher_loop()` every 1s up to `settings.max_concurrent_tasks` slots.

### Restart recovery

- **Sub-agents**: `_cleanup_stale_agent_statuses()` marks dead PIDs `terminated`, clears stale `status: running` TASK.MDs. Result lost; next spawn creates fresh task.
- **Master**: `RESUME.MD` written on clean REPL exit; reloaded next start to show pending/running tasks.
- **Redis inbox**: messages persist in streams. `stream_claim_pending()` reclaims messages pending > 30s from a dead consumer. No task message is lost.
- **File notification queue**: skip-if-`consumed_at` prevents reprocessing.

---

## 5. Backend HTTP Layer (`app/backend/main.py`)

### Lifespan startup
1. AsyncIOScheduler init.
2. Load `NotificationQueue` + `SpawnRegistry` from disk.
3. Start `NotificationPoller` (30s).
4. Start `MessageBusRelay` (Redis → WebSocket).
5. Schedule background asyncio tasks:
   - `_doctor_tick` — 5 min
   - `_model_manager_tick` — 24 hr
   - `_cron_scheduler_tick` — 10 min
   - `_master_notification_watcher` — 3s
   - `dispatcher_loop` — 1s
6. `_cleanup_stale_agent_statuses()`.

### Endpoints

| Route | Method | Purpose |
|-------|--------|---------|
| `/task` | POST | Blocking task to master, returns text |
| `/task/stream` | POST | SSE stream of master events |
| `/agents` | GET | List + statuses |
| `/agents/{name}` | GET | Status + metadata |
| `/agents/{name}/memory` | GET | MEMORY.MD |
| `/agents/{name}/health` | GET | HEALTH.MD |
| `/agents/{name}/spawn` | POST | Manual start |
| `/agents/{name}/kill` | POST | SIGTERM |
| `/agents/{name}/restart` | POST | Clear TASK.MD + HEALTH.MD (no kill) |
| `/health` | GET | uptime |
| `/health/summary` | GET | Doctor's HEALTH_SUMMARY.MD |

Backend is always-on once `yapoc start` runs.

---

## 6. Tool Execution

- **Registry**: 40 tools in `app/utils/tools/__init__.py` (TOOL_REGISTRY).
- **Loop**: `BaseAgent.run_stream_with_tools()` — LLM returns `tool_use` → `_execute_tool()` with 1 auto-retry on transient errors → `asyncio.gather()` runs concurrent calls → results appended as `tool_result` → loop up to `max_turns`.
- **No approval gate** — tools fire immediately.
- **Notification-task blocklist**: `source == "notification"` passes `blocked_tools = {server_restart, process_restart, spawn_agent, kill_agent, shell_exec}`.
- **Sandboxing**: file tools enforce `_sandbox(path)` (must be inside `project_root`). `file_delete` refuses protected names (`.env`, `.git`, core agent files).
- **Shell**: hard-capped at `settings.max_shell_timeout` (120s); kills process group on timeout. Optional `CONFIG.md sandbox.shell_allowlist`.

---

## 7. Gaps for "Truly Alive" Agents

### Process management
- **No supervisor / auto-respawn.** Crashed sub-agents stay dead until manual intervention or server restart. Parent tasks waiting for results block until timeout.
- **Spawn-on-demand latency.** First task on a fresh agent: 5–15s for subprocess startup + watchdog init + first LLM call. No agent pool / pre-warm.
- **No per-agent concurrency limits.** `max_concurrent_agents` is a single global cap — one greedy parent can starve others.
- **No resource limits.** No CPU/memory/disk quotas; runaway tools consume whatever the OS allows. Containerization is left to the operator.

### Coordination & consistency
- **File-write races.** Shared files (`MEMORY.MD`, `NOTES.MD`, `LEARNINGS.MD`, `KNOWLEDGE.MD`) are written without `fcntl` locking. Only `notification_queue.json` and `spawn_registry.json` are locked. In practice each agent mostly owns its own files, so corruption is rare but possible.
- **No peer-to-peer comms.** Everything flows through parent→child task assignment. Flat agent networks aren't supported.
- **No task priority.** `task_queue` is FIFO; no SLAs, preemption, or priority levels.

### Liveness & recovery
- **PID-only liveness check.** `os.kill(pid, 0)` works on POSIX but is fragile on Windows (PID reuse). No heartbeat-driven liveness.
- **Stale-task detection lag.** Doctor runs every 5 min, so stale tasks take up to 5 min to surface, and parent-side wait timeout must be ≥ 2× that window.
- **Idle-timeout silent kill.** Default 15 min idle → agent dies. Master holding a long-lived reference to a planning agent will silently lose it across pauses; next call creates a fresh process with no in-memory continuity beyond MEMORY.MD.
- **Mid-task server restart loses state.** Cleanup clears `status: running` TASK.MDs. Redis inbox messages survive but agent must be respawned to consume them.

### Message-delivery semantics
- **Pub/sub events are ephemeral.** `session:*:events` deltas not persisted; clients that disconnect mid-stream miss them. Reconnect must read RESULT.MD for the final answer.
- **CRASH.MD never rotated.** Doctor rotates HEALTH.MD but not CRASH.MD. Unbounded growth on chronic crashers.

### Operational
- **No tests.** Per CLAUDE.md ("no tests yet — MVP phase"). No coverage for race conditions, crash recovery, distributed coordination.
- **Doctor alerts are advisory.** No auto-remediation — alerts land in HEALTH_SUMMARY.MD / Redis but nothing acts on them.
- **`run_stream_with_tools` override risk.** Custom agent subclasses overriding this method may bypass the notification-task `blocked_tools` safety.

### What "truly alive" would need
1. **Persistent agent processes** under a supervisor (systemd / supervisord / custom asyncio supervisor) with auto-restart-on-crash and exponential backoff.
2. **Event-driven activation as primary**, polling and watchdog as fallback only.
3. **Distributed task state machine** persisted to SQLite/Postgres — every state transition (pending → running → tool_call_N → done) durable.
4. **Cross-process file locking** for shared markdown files, or migration to a single writer per file.
5. **Heartbeat protocol** — agents publish liveness to message bus every N seconds; supervisor restarts on missed beats.
6. **Circuit breaker** — pause new spawns when error rate across running agents exceeds threshold.
7. **Agent pool / pre-warmed workers** for low-latency task pickup.
8. **Test coverage** for the runtime paths — at minimum, spawn / crash / restart / notification flows.

---

## Component map (one-liner reference)

- `app/agents/base/__init__.py` — `BaseAgent` (config load, context assembly, LLM loop)
- `app/agents/base/runner.py` — `AgentRunner` (watchdog, polling, Redis inbox, STATUS.json heartbeat)
- `app/agents/base/runner_entry.py` — subprocess entry, crash capture
- `app/agents/base/context.py` — `build_system_context()`
- `app/agents/master/agent.py` — in-process master
- `app/agents/doctor/agent.py` — programmatic + LLM doctor
- `app/utils/tools/delegation.py` — `SpawnAgentTool`, `KillAgentTool`, `WaitForAgentTool`, etc.
- `app/utils/tools/__init__.py` — TOOL_REGISTRY (40 tools)
- `app/backend/main.py` — FastAPI lifespan, background tasks, stale-cleanup
- `app/backend/dispatcher.py` — `task_queue` polling, goal-driven tasks
- `app/backend/message_bus.py` — Redis streams + pub/sub + outbox fallback
- `app/backend/relay.py` — `MessageBusRelay` (pub/sub → WebSocket)
- `app/backend/services/notification_queue.py` — fcntl-locked JSON queue
- `app/backend/services/notification_poller.py` — TASK.MD scanner + wake
- `app/backend/services/spawn_registry.py` — parent-child mapping
- `app/backend/services/agent_results.py` — RESULT.MD reads
