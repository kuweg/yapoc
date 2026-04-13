# Autonomous Architecture

*The best from both worlds — Claude Code's interactive depth + OpenClaw's always-on gateway.*

---

## Full system diagram

```
╔══════════════════════════════════════════════════════════════════════════╗
║                           ENTRY POINTS                                   ║
║                                                                          ║
║  Mission Control (UI)   Telegram Bot   Webhook   Cron   Goals   CLI     ║
║         │                    │            │        │       │      │       ║
║         └────────────────────┴────────────┴────────┴───────┴──────┘       ║
║                                    │                                     ║
╚════════════════════════════════════╪═════════════════════════════════════╝
                                     │
                                     ▼
╔══════════════════════════════════════════════════════════════════════════╗
║                          FASTAPI BACKEND                                 ║
║                                                                          ║
║   POST /task            POST /webhook/task       GET /ws                 ║
║   POST /telegram        POST /approval           (WebSocket)             ║
║         │                      │                      ▲                  ║
║         └──────────────────────┘                      │                  ║
║                    │                                  │                  ║
║                    ▼                                  │                  ║
║   ┌────────────────────────┐    ┌──────────────────────────────────┐     ║
║   │     Task Store         │    │     WebSocket Manager            │     ║
║   │     (SQLite)           │───►│                                  │     ║
║   │                        │    │  Task events → all clients       │     ║
║   │  id, prompt, status,   │    │  Turn events → subscribed only   │     ║
║   │  source, session_id,   │    │  Approval events → subscribed    │     ║
║   │  result, error         │    │                                  │     ║
║   └────────┬───────────────┘    └──────────────────────────────────┘     ║
║            │                              ▲                              ║
║            │                              │                              ║
║   ┌────────▼───────────────┐    ┌─────────┴────────────────────────┐     ║
║   │   Approval Queue       │    │   Session Store                  │     ║
║   │   (CONFIRM-tier tools) │    │   (JSONL per session)            │     ║
║   │                        │    │   conversation context +         │     ║
║   │   pending → approved   │    │   turn-level event log           │     ║
║   │           → denied     │    │                                  │     ║
║   │           → expired    │    └──────────────────────────────────┘     ║
║   └────────────────────────┘                                             ║
║                                                                          ║
╚════════════════════════════════════╪═════════════════════════════════════╝
                                     │
                                     ▼
╔══════════════════════════════════════════════════════════════════════════╗
║                    TASK DISPATCHER (always-on)                            ║
║                                                                          ║
║   asyncio background loop — polls task store, writes TASK.MD            ║
║   + notification listener — reads notify_parent("user"), updates tasks  ║
║   + approval timeout — expires stale approval requests                  ║
║                                                                          ║
╚════════════════════════════════════╪═════════════════════════════════════╝
                                     │ writes TASK.MD
                                     ▼
╔══════════════════════════════════════════════════════════════════════════╗
║                         AGENT HIERARCHY                                  ║
║                                                                          ║
║  ┌──────────────┐                                                        ║
║  │    MASTER    │◄── GOALS.MD (self-directed work when idle)            ║
║  │              │◄── RESUME.MD (continue after restart)                 ║
║  │              │◄── LEARNINGS.MD (accumulated rules)                   ║
║  └──────┬───────┘                                                        ║
║         │ spawn_agent                                                    ║
║         ├─────────────────────────┐                                      ║
║         ▼                         ▼                                      ║
║  ┌──────────────┐          ┌──────────────┐                              ║
║  │   PLANNING   │          │   BUILDER    │                              ║
║  │              │          │              │◄── peer: KEEPER              ║
║  └──────┬───────┘          └──────┬───────┘                              ║
║         │                         │                                      ║
║         ▼                         ▼                                      ║
║  ┌──────────────┐          ┌──────────────┐                              ║
║  │   BUILDER    │          │  TEMP AGENTS │                              ║
║  └──────────────┘          └──────────────┘                              ║
║                                                                          ║
║  ┌───────────────────────────────────────────────────┐                   ║
║  │  DOCTOR (autonomous — detects AND acts)           │                   ║
║  │  → stale/crashed/errored agent detection          │                   ║
║  │  → spawns planning to investigate                 │                   ║
║  │  → kills zombie agents                            │                   ║
║  │  → bounded by autonomy envelope                   │                   ║
║  └───────────────────────────────────────────────────┘                   ║
║                                                                          ║
║  ┌───────────────────────────────────────────────────┐                   ║
║  │  CRON (schedule-driven, no human trigger)         │                   ║
║  │  → reads schedule from NOTES.MD                   │                   ║
║  │  → fires tasks on cron expressions                │                   ║
║  └───────────────────────────────────────────────────┘                   ║
║                                                                          ║
║  ┌───────────────────────────────────────────────────┐                   ║
║  │  KEEPER (config management, peer of builder)      │                   ║
║  │  → manages .env, settings.py, pyproject.toml     │                   ║
║  └───────────────────────────────────────────────────┘                   ║
║                                                                          ║
║  Each agent emits structured events via stdout JSON lines:              ║
║  thinking_delta, tool_call, tool_result, message_delta, approval_needed ║
║                                                                          ║
╚════════════════════════════════════╪═════════════════════════════════════╝
                                     │ notify_parent chain
                                     ▼
╔══════════════════════════════════════════════════════════════════════════╗
║                        RESULT DELIVERY                                   ║
║                                                                          ║
║  notify_parent("user")                                                   ║
║         │                                                                ║
║         ▼                                                                ║
║  Notification listener → Task Store updated (status=done, result=...)   ║
║         │                                                                ║
║         ├───────────────────────────────────────────────┐                ║
║         ▼                                               ▼                ║
║  WebSocket push → Mission Control                Channel reply           ║
║  (task events + turn events if subscribed)       (Telegram, webhook CB) ║
║         │                                                                ║
║         ├── Chat tab: conversation updated                              ║
║         ├── Dashboard: kanban card moves to Done                        ║
║         ├── Agents tab: agent status → idle                             ║
║         └── Approval badge: cleared if pending approvals resolved       ║
║                                                                          ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## Dual-mode operation

The same architecture serves both modes. The difference is whether a human
is actively observing.

### Interactive mode (Claude Code feel)

```
User in Chat tab → subscribed to session via WebSocket
  → turn-level events stream in real-time (thinking, tool calls, responses)
  → CONFIRM-tier tools prompt the user via ApprovalDialog
  → user can interrupt, redirect, continue the conversation
  → session context persists (JSONL) for follow-up messages
```

### Autonomous mode (OpenClaw feel)

```
User fires task and leaves → no WebSocket subscriber
  → turn-level events written to session log (not pushed)
  → CONFIRM-tier tools checked against autonomous approval policy
    → auto_approve: execute immediately
    → deny: agent adjusts
    → queue: waits in approval queue for user return
  → result stored in task store when complete
  → user returns → UI catches up from task store + session log
```

The mode is determined per-session, not globally. One task can be interactive
(user watching in Chat) while another runs autonomously in background.

---

## Session-task bridge

This is the key architectural concept that connects conversations to tasks.

Every task has a `session_id`. A session is a conversation context.

```
Chat tab conversation:
  user says: "build a user auth module"
    → creates task with session_id = current session
    → task dispatched to master
    → master's turn events flow back to that session
    → when done, result appears as next message in the conversation

Dashboard ticket:
  user creates ticket: "Fix login bug"
    → creates task with session_id = new session (auto-created)
    → task executes in background
    → result stored on the ticket
    → if user opens ticket in Chat view: session loads with full history
```

Sessions give tasks memory. A follow-up message in the same Chat session
carries the full conversation context. Master reads the session history
and understands "when you say 'also add rate limiting,' you mean on the
auth module we just built."

This is what makes the Chat tab more than a task input box — it's a
Claude Code-style conversation with persistent context.

---

## Component responsibilities

### Mission Control (UI)
- Primary human interface — Chat (interactive), Dashboard (autonomous), Agents (observability)
- Real-time observer via WebSocket (task events always, turn events when subscribed)
- Approval surface for queued CONFIRM-tier tools
- Does NOT drive execution — fires and watches, or fires and leaves

### FastAPI Backend
- Thin HTTP + WebSocket layer
- Accepts tasks, returns task_id immediately
- Routes WebSocket events (task-level to all, turn-level to subscribers)
- Hosts approval queue
- Does NOT run agents — delegates to dispatcher

### Task Store (SQLite)
- Persistent task state (survives everything)
- Schema: `tasks(id, prompt, status, source, session_id, assigned_agent, result, error, created_at, updated_at)`
- Status: `pending → running → done | error | timeout`

### Session Store (JSONL)
- Conversation context per session
- Turn-level event log (for playback when user returns)
- Messages: user input + agent responses + tool calls + thinking
- Bridges the gap between "task" and "conversation"

### Approval Queue
- Pending CONFIRM-tier tool requests from autonomous execution
- Items have TTL (default 24h) — expired = auto-denied
- Surfaced in UI as notification badge + dedicated panel
- Can also be resolved via Telegram (/approve, /deny)

### Task Dispatcher
- Always-on asyncio loop
- Polls task store, writes TASK.MD, reads notification queue
- Manages concurrency (max N parallel tasks)
- Handles timeout detection and restart recovery
- Runs approval timeout expiry

### Agent Hierarchy
- Master, Planning, Builder, Doctor, Cron, Keeper
- Communicate via markdown files + notify_parent chain
- Emit structured events via stdout JSON lines
- Each agent runs as a subprocess (via AgentRunner)

### Notification Chain
- `notify_parent` tool + `NotificationQueue` + `SpawnRegistry`
- Final `notify_parent("user")` → notification listener → task store update
- Already implemented — notification listener is the missing consumer

---

## Key architectural properties

**Dual-mode from the same architecture**
Interactive and autonomous are not separate systems. They are the same pipeline
with different observation and approval policies.

**Sessions bridge tasks and conversations**
A task is a unit of work. A session is a conversation. They are linked by `session_id`.
This means task results flow into conversation context, and conversation context
informs task execution.

**Push, not poll**
Task events push to all WebSocket clients. Turn events push to subscribed clients.
State sync on reconnect ensures no missed events.

**Entry-point agnostic**
Every source writes to the same task store. The dispatcher doesn't care about origin.
Delivery adapts based on `source` field.

**Safety scales with autonomy**
Interactive mode: user approves everything. Autonomous mode: policy engine decides.
The same tools, the same agents, different approval paths.
