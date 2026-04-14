# Autonomy Roadmap

Ordered implementation plan. Each phase produces a working, testable increment.
Do not start the next phase until the current one is verified.

> **M1–M9 status (April 2026):** Many items marked "not built" in original phases
> are now built. See annotations below marked with ✅. The async API boundary (R1)
> remains the critical blocker — everything below Phase 1 is unlocked by it.

---

## Phase 1 — Fire and Forget (the foundation)

**Goal:** Tasks survive browser close. User gets result when they return.
**Autonomy level:** 1 (fire-and-forget)

### 1A. Async task endpoint

Change `POST /task` to write to task store and return immediately.

```
File: app/backend/routers/tasks.py
Change: remove await on agent execution
Add: task_store.create(prompt, source, session_id)
Returns: { task_id, status: "pending" }
```

### 1B. Task Dispatcher

Background asyncio loop that polls task store and writes TASK.MD.

```
File: app/backend/dispatcher.py (new)
Start: app/backend/main.py startup hook
Logic: pending → running, write master/TASK.MD, push WebSocket event
Includes: notification listener (reads notify_parent("user"), updates task store)
Includes: timeout checker (marks stale tasks as timeout)
```

### 1C. WebSocket push (task-level events)

Push task state changes to all connected UI clients.

```
File: app/backend/websocket.py (new or extend existing)
Events: task_created, task_update, task_complete, task_error, agent_status
State sync: send recent tasks on WebSocket connect (catch-up)
```

### 1D. UI: catch-up on connect

Dashboard and Chat tabs fetch current task state on load,
then subscribe to WebSocket for live deltas.

```
Files: app/frontend/src/store/ (existing stores)
Change: fetch /api/tasks on mount, apply WebSocket events as deltas
```

**Acceptance criteria:**
- Create a task in UI, close browser immediately
- Task executes (verify in logs)
- Reopen browser — task shows as Done with result
- No polling needed, no manual refresh

---

## Phase 2 — Streaming & Interactive Mode

**Goal:** Chat tab shows agent thinking in real-time. Claude Code feel.
**Autonomy level:** 0 (interactive) — but built on Phase 1's async foundation

### 2A. Agent event emission

Agents emit structured JSON lines to stdout during execution.

```
File: app/agents/base/__init__.py
Add: _emit_event(type, payload) → writes JSON line to stdout
Events: thinking_delta, tool_call, tool_result, message_delta
```

### 2B. Backend event relay

Backend reads agent stdout events and pushes to subscribed WebSocket clients.

```
File: app/backend/websocket.py
Add: session subscription model (subscribe/unsubscribe per session_id)
Add: relay loop that reads agent events and pushes to subscribers
```

### 2C. Chat tab streaming

Chat tab subscribes to session and renders events in real-time.

```
Files: app/frontend/src/components/ChatPanel.tsx, ThinkingBlock.tsx, ToolCallBlock.tsx
Change: consume turn-level WebSocket events, render incrementally
```

### 2D. Session playback

When user opens a session they weren't watching, load event history.

```
Files: app/frontend/src/store/session.ts
Add: on session select, fetch recent events from session log
Render: full conversation history including thinking + tool calls
```

**Acceptance criteria:**
- Start a task from Chat tab
- See thinking blocks appear in real-time
- See tool calls with inputs/outputs
- See response stream token by token
- Close browser, reopen — full conversation history loads

---

## Phase 3 — Task Persistence & Recovery

**Goal:** Server restart does not lose running or pending tasks.
**Autonomy level:** 2 (self-managing)

### 3A. Task Store recovery on startup

```
File: app/backend/main.py startup hook
Logic:
  - tasks with status=running → check if agent actually running
    → if not: reset to pending
  - tasks with status=pending → dispatcher picks them up automatically
```

### 3B. Dispatcher deduplication

```
File: app/backend/dispatcher.py
Add: TASK.MD fingerprint (task_id in file) to prevent re-dispatch
```

**Acceptance criteria:**
- Start a long task (>30s)
- Kill and restart the server mid-task
- Task resumes or re-runs from pending
- Result eventually appears in UI

---

## Phase 4 — Autonomous Tool Approval + Cost Governance

**Goal:** CONFIRM-tier tools handled safely when user is absent.
System governs its own resource consumption.
**Autonomy level:** 2–3 (self-managing, partially self-healing)

### 4A. Autonomous approval policy engine

```
File: app/utils/tools/approval.py (new)
Reads: agent CONFIG.md autonomous_policy section
Logic: check tool + input against auto_approve / deny / queue rules
```

### 4B. Interactive approval over WebSocket

```
File: app/backend/websocket.py
Events: approval_needed → client, approval_response → backend → agent
File: app/frontend/src/components/ApprovalDialog.tsx (exists, wire up)
```

### 4C. Approval queue for absent users

```
File: app/backend/approval_queue.py (new)
Storage: SQLite table or JSON file
Logic: queue pending approvals, show badge in UI, expire after TTL
Optional: relay to Telegram for remote approval
```

### 4D. Cost governance (Level 3 requirement)

```
File: app/utils/cost_governor.py (new, or extend usage_tracker.py)
Features:
  - Per-task cost limit (default $5) — force-stop with partial result
  - Daily autonomous budget (default $10) — pause autonomous work when exhausted
  - Loop detection — same tool 10+ times consecutively → inject reflection
  - Cost injection — [COST] system messages after each turn so agent sees its spending
  - Spawn depth limit (max 5 levels) — prevent unbounded delegation chains
```

See [cost-awareness.md](cost-awareness.md) for full design.

**Acceptance criteria:**
- Interactive: CONFIRM tool shows dialog in Chat, user approves, agent continues
- Autonomous (auto_approve match): tool executes without prompt
- Autonomous (no match): tool queued, agent pauses, user approves on return
- Task exceeding $5 limit: force-stopped with partial result, user notified
- Daily budget exhausted: autonomous tasks pause, user tasks still work
- Tool called 10+ times in a row: loop broken with reflection injection

---

## Phase 5 — Self-Direction: Goals

**Goal:** System works between user sessions without being asked.
**Autonomy level:** 4 (self-directed)

### 5A. GOALS.MD parser + context injection

```
File: app/agents/base/context.py
Add: build_goals_context() — reads GOALS.MD, formats for prompt
Inject: into master's system context
```

### 5B. Goal-driven behavior in master

```
File: app/agents/master/PROMPT.MD
Add: ## Goal-Driven Behavior section
Logic: when no user task pending, read GOALS.MD, work on top active goal
```

### 5C. Goal completion tracking

```
Master edits GOALS.MD via file_write after completing a goal.
No new tool needed — prompt instruction is sufficient.
```

**Acceptance criteria:**
- Add an active goal to master/GOALS.MD
- Do not send any user message
- After idle time: master begins working on the goal autonomously
- Goal marked [x] when complete

---

## Phase 6 — Cron

**Goal:** Scheduled tasks fire without human trigger.
**Autonomy level:** 3 (self-healing via scheduled health checks)

### 6A. Real cron schedule in NOTES.MD

```
File: app/agents/cron/NOTES.MD
Add: real schedule entries (daily-tests, health-check, daily-digest)
```

### 6B. Cron agent prompt + last-run tracking

```
File: app/agents/cron/PROMPT.MD — read schedule, calculate due jobs, spawn agents
File: data/cron_runs.json — tracks last execution time per job
```

**Acceptance criteria:**
- Schedule a cron job for "every minute" (for testing)
- After one minute: job fires without any user action
- Task appears in Dashboard
- Result delivered via WebSocket

---

## Phase 7 — Doctor as an Actor

**Goal:** System heals itself without human intervention.
**Autonomy level:** 3 (self-healing)

### 7A. Doctor response actions

```
File: app/agents/doctor/agent.py
Add: _act_on_findings() — for each finding, create appropriate repair task
```

### 7B. Doctor autonomy envelope

```
File: app/agents/doctor/CONFIG.md
Add: spawn_agent, kill_agent tools + autonomy_envelope section
```

**Acceptance criteria:**
- Force an agent into an error state
- Doctor detects it within its next run
- Doctor spawns a repair task
- No human involvement at any step

---

## Phase 8 — External Entry Points

**Goal:** Tasks can enter from outside the local browser.
**Autonomy level:** 1+ (fire-and-forget from anywhere)

### 8A. Generic webhook

```
File: app/backend/routers/webhook.py (new)
Endpoint: POST /webhook/task
Auth: Bearer token
```

### 8B. Telegram bot

```
File: app/backend/routers/telegram.py (new)
Library: python-telegram-bot
Features: send tasks, receive results, approve queued tools via /approve
```

**Acceptance criteria:**
- curl POST /webhook/task → task appears in Dashboard → result delivered
- Telegram message → bot acknowledges → agents execute → bot replies with result

---

## Phase 9 — Extensibility

**Goal:** Users can add tools without editing core code.
**Autonomy level:** N/A (capability expansion)

### 9A. Workspace skills (no code)

```
Convention: app/projects/skills/*.md read by master before task execution
```

### 9B. Python tool plugins (hot-loadable)

```
File: app/utils/tools/plugin_loader.py (new)
Directory: plugins/
Discovery: scan for BaseTool subclasses, register in TOOL_REGISTRY
```

### 9C. MCP server support (later)

```
File: app/utils/mcp_client.py (new)
Config: mcp_servers list in settings
Protocol: spawn MCP server processes, proxy tool calls
```

**Acceptance criteria:**
- Drop a .md file in skills/ → master uses it for relevant tasks
- Drop a .py plugin in plugins/ → tool available to agents after restart

---

## Phase 10 — Resume on Startup

**Goal:** System continues interrupted work after restart.
**Autonomy level:** 2 (self-managing)

### 10A. Active resume hook

```
File: app/backend/main.py
Add: on startup, read RESUME.MD + GOALS.MD, create task store entries
```

**Acceptance criteria:**
- Start a 5-minute task, kill server at 2 minutes
- Restart server
- Task continues or re-runs
- Result eventually delivered

---

## Phase summary

| Phase | Capability | Level | Claude Code | OpenClaw | YAPOC-only |
|---|---|---|---|---|---|
| 1 | Fire and forget | 1 | | x | |
| 2 | Streaming + interactive | 0 | x | | |
| 3 | Restart persistence | 2 | | x | |
| 4 | Autonomous tool approval | 2-3 | x | x | x |
| 5 | Self-directed goals | 4 | | | x |
| 6 | Cron scheduling | 3 | | x | |
| 7 | Doctor self-healing | 3 | | | x |
| 8 | External entry points | 1+ | | x | |
| 9 | Extensibility (plugins/MCP) | N/A | x | x | |
| 10 | Active resume | 2 | | x | |

**After Phase 1:** matches OpenClaw's fire-and-forget.
**After Phase 2:** matches Claude Code's interactive experience.
**After Phase 4:** has something neither has — autonomous safety policy for tool approval.
**After Phase 5:** exceeds both — self-directed work toward goals.
**After Phase 7:** does what OpenClaw explicitly will not do — self-healing agent hierarchy.

---

## What not to build (yet)

- Voice wake / companion apps (out of scope)
- Multi-user support (single-user by design, for now)
- Horizontal scaling (one process is fine)
- Full skill registry / marketplace
- Agent-to-agent peer delegation without Master (M8 from agentic roadmap covers basics)
