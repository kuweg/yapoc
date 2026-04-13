# Task Lifecycle

How a task moves from creation to result delivery.
Two paths through the same pipeline — interactive and autonomous.

---

## Lifecycle states

```
pending → running → done
                 → error
                 → timeout
                 → paused (waiting for approval)
```

| State | Meaning |
|---|---|
| `pending` | Task created, waiting for dispatcher |
| `running` | Dispatcher assigned to master, agent working |
| `paused` | Agent hit a CONFIRM-tier tool, waiting for approval |
| `done` | Agent completed successfully, result stored |
| `error` | Agent failed, error message stored |
| `timeout` | Agent exceeded time limit |

---

## Path A — Interactive (Claude Code feel)

User is present. Chat tab is open. Session is subscribed via WebSocket.

```
1. USER TYPES IN CHAT TAB
   ─────────────────────────────────────────────────
   User types: "build a user auth module"

   POST /task { prompt: "...", source: "ui", session_id: "current_session" }
   → task_id returned immediately
   → WebSocket: task_created event
   → Chat tab shows "working..." indicator

2. DISPATCHER ASSIGNS TO MASTER
   ─────────────────────────────────────────────────
   Dispatcher writes master/TASK.MD with task_id + session_id
   AgentRunner wakes master

3. AGENT STREAMS TO CHAT (real-time)
   ─────────────────────────────────────────────────
   Master emits events via stdout JSON lines:

     thinking_delta → ThinkingBlock appears in Chat, streams live
     tool_call      → ToolCallBlock shows tool name + input
     tool_result    → ToolCallBlock shows output + duration

   Master spawns Planning → Planning emits events too
   (turn events tagged with agent name so Chat can show "Planning is thinking...")

   Planning spawns Builder → Builder events stream

4. APPROVAL PROMPT (if needed)
   ─────────────────────────────────────────────────
   Builder needs shell_exec("poetry add pyjwt")
   → RiskTier.CONFIRM → user is subscribed → prompt the user

   approval_needed event → Chat tab → ApprovalDialog appears:
     "Builder wants to run: poetry add pyjwt"
     [Approve] [Deny]

   User clicks Approve → approval_response sent via WebSocket
   → Agent receives approval → continues execution

5. RESULT IN CONVERSATION
   ─────────────────────────────────────────────────
   Builder → notify_parent(planning) → notify_parent(master) → notify_parent(user)

   Final response appears as a message in the conversation.
   Session context updated — user can send follow-up:
     "also add rate limiting to the auth endpoints"

   Master reads session history, understands the context, continues.
```

**Key difference from autonomous:** the user sees everything happening,
can approve tools interactively, and can steer mid-execution.

---

## Path B — Autonomous (OpenClaw feel)

User fires and leaves. No WebSocket subscriber on the session.

```
1. USER FIRES AND LEAVES
   ─────────────────────────────────────────────────
   User creates a ticket in Dashboard, or sends via Telegram, or cron fires.

   POST /task { prompt: "...", source: "ui|telegram|cron|goals" }
   → task_id returned
   → User closes browser / puts phone away

   Task exists in task store. No active observer.

2. DISPATCHER ASSIGNS TO MASTER
   ─────────────────────────────────────────────────
   Same as interactive. Dispatcher writes TASK.MD. Runner wakes master.

3. AGENTS EXECUTE IN BACKGROUND
   ─────────────────────────────────────────────────
   Master, Planning, Builder all emit events via stdout.
   Events written to session event log (data/sessions/{id}/events.jsonl).
   NOT pushed via WebSocket — no subscriber.

   If user opens Mission Control mid-execution:
     → Chat tab loads session → subscribes → begins receiving live events
     → Transitions from autonomous to interactive seamlessly

4. TOOL APPROVAL (policy-based)
   ─────────────────────────────────────────────────
   Builder needs shell_exec("poetry add pyjwt")
   → RiskTier.CONFIRM → no subscriber → check autonomous policy

   Policy in builder CONFIG.md:
     "poetry add *" → not in auto_approve → default: queue

   Tool request added to approval queue.
   Task status: paused
   WebSocket: task_update { status: "paused", reason: "approval_needed" }

   Options:
   a) User returns to Mission Control → sees approval badge → approves → resumes
   b) Telegram notification sent → user replies /approve → resumes
   c) TTL expires (24h) → auto-denied → agent adjusts approach

   Alternative: if "poetry run pytest*" → auto_approve → executes immediately, no pause

5. RESULT PERSISTED
   ─────────────────────────────────────────────────
   notify_parent("user") → notification listener → task store updated

   Task store: { status: "done", result: "Auth module created..." }
   WebSocket push: task_complete (if anyone is connected)

   If no one is connected:
     result sits in task store
     user returns → UI loads → sees completed task with result

   If Telegram source:
     bot sends reply: "Done. Auth module created in app/auth/..."
```

---

## Failure paths

### Agent error

```
Builder throws exception
  → writes ERROR to HEALTH.MD
  → notify_parent("planning") with error context
  → Planning: retry up to 2 times (with adjusted approach)
  → if retries exhausted: notify_parent("master") with [DECISION NEEDED]

Interactive: Master presents options in Chat tab, user decides
Autonomous: Master applies error recovery prompt, attempts alternative
           if no recovery possible: task store → status: error
```

### Agent timeout

```
Dispatcher: task running > task_timeout
  → task store: status: timeout
  → WebSocket: task_update { status: "timeout" }
  → Doctor detects on next run → spawns investigation task
```

### Server restart mid-task

```
Server starts → dispatcher starts
  → query tasks with status=running
  → check each: is agent process still alive?
    → alive: let it continue
    → dead: reset to pending → dispatcher re-dispatches
```

### Browser disconnect during interactive

```
WebSocket drops
  → mode transitions: interactive → autonomous
  → agent continues executing (subprocess doesn't know about WebSocket)
  → turn events still written to session log (not pushed)
  → CONFIRM tools: fall back to autonomous policy (not prompt)
  → when browser reconnects: catch-up from session log
```

### Approval timeout in autonomous mode

```
CONFIRM tool queued → no one approves for 24 hours
  → auto-denied
  → agent receives denial
  → agent adjusts approach (use alternative tool, or escalate to master)
  → if no alternative: task → status: error with "approval timeout" reason
```

---

## Task metadata

```json
{
  "id": "task_abc123",
  "prompt": "build a user auth module",
  "status": "done",
  "source": "ui",
  "session_id": "session_def456",
  "source_channel": null,
  "source_chat_id": null,
  "assigned_agent": "master",
  "result": "Auth module created in app/auth/. JWT tokens, bcrypt hashing. Tests pass.",
  "error": null,
  "created_at": "2026-04-13T22:00:00Z",
  "updated_at": "2026-04-13T22:14:32Z",
  "duration_seconds": 872
}
```

The `session_id` links the task to its conversation context.
The `source` field drives result delivery channel.
