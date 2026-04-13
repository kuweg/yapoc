# Entry Points

All the ways a task can enter YAPOC. Every entry point writes to the same Task Store.
The system does not behave differently based on where the task came from —
only result delivery changes.

---

## Entry point map

```
Mission Control (UI)     ──► POST /task
Telegram Bot             ──► POST /telegram/update  ──► task store
GitHub Webhook           ──► POST /webhook/github    ──► task store
Generic Webhook          ──► POST /webhook/task      ──► task store
Cron (internal timer)    ──► APScheduler tick        ──► task store
Goals (GOALS.MD)         ──► Dispatcher reads goals  ──► task store
CLI (legacy)             ──► POST /task (same API)
```

Every path converges at the Task Store. The dispatcher handles everything from there.

---

## 1. Mission Control (primary)

**Status: partially working — needs async decoupling**

The UI creates tasks via the Chat tab or Dashboard tab.

```
Chat tab:   user types message → POST /task { prompt, source: "ui" }
Dashboard:  user creates ticket → POST /task { prompt, source: "ui", ticket_id }
```

The critical change needed: FastAPI handler must return `task_id` immediately,
not wait for the agent response. See [execution-engine.md](execution-engine.md).

Result delivery: WebSocket push to the open browser session.

---

## 2. Telegram Bot

**Status: not yet built**

Transforms YAPOC from a local tool into an agent that exists in the world.
You can fire tasks from your phone while away from your desk.
The system replies when done.

### How it works

```
User sends Telegram message
  → Telegram calls POST /telegram/update
  → Backend validates bot token
  → Checks allowlist (only known user IDs can trigger tasks)
  → Creates task: { prompt: msg.text, source: "telegram", source_chat_id: msg.chat.id }
  → Sends "received, working on it..." reply immediately
  → Returns 200 OK to Telegram

[Agent hierarchy executes...]

  → notify_parent("user") triggers result delivery
  → Backend sends reply to source_chat_id via Telegram Bot API
```

### Implementation notes

- Library: `python-telegram-bot` (async, well-maintained)
- Config: `settings.telegram_bot_token`, `settings.telegram_allowed_user_ids`
- The allowed user IDs list is the security boundary — no pairing ceremony needed for personal use
- Long-running tasks: send interim "still working..." updates every N minutes
- File: `app/backend/routers/telegram.py`

---

## 3. GitHub Webhook

**Status: not yet built**

Connects YAPOC to the software development lifecycle.
A new issue → a task. A failing CI run → a task. No human needed in the loop.

### Events to handle

| GitHub event | Task created |
|---|---|
| `issues.opened` | "Investigate and resolve: {issue.title}\n\n{issue.body}" |
| `issues.labeled` with `agent-task` | Same as above, opt-in label |
| `workflow_run.completed` with failure | "CI failed on {branch}: {logs_url}. Investigate and fix." |
| `pull_request_review.submitted` | "Address review comments on PR #{number}: {comments}" |

### Implementation notes

- Config: `settings.github_webhook_secret` (HMAC validation)
- File: `app/backend/routers/github.py`
- Only handle events that have a clear actionable task — ignore the rest

---

## 4. Generic Webhook

**Status: not yet built**

Anything can fire a task. CI systems, monitoring alerts, other services.
The simplest and most flexible entry point.

```
POST /webhook/task
Authorization: Bearer <webhook_token>

{
  "prompt": "Database CPU spiked to 95%. Investigate and remediate.",
  "priority": "high",
  "source": "datadog-alert"
}

→ 200 OK { "task_id": "task_abc123" }
```

- Config: `settings.webhook_token` (static bearer token)
- File: `app/backend/routers/webhook.py`
- Priority field maps to dispatcher queue ordering (high priority = dispatched first)

---

## 5. Cron (internal)

**Status: stub — schedule not wired**

The Cron agent runs on a schedule independent of any human trigger.
No one has to ask YAPOC to run tests every morning. It just does.

### Schedule format (in `app/agents/cron/NOTES.MD`)

```yaml
schedule:
  - cron: "0 8 * * *"
    task: "Run the full test suite. Create a ticket for any failures."
    assign_to: builder

  - cron: "0 */4 * * *"
    task: "Check all agent HEALTH.MD files for new ERROR entries. Summarize findings."
    assign_to: doctor

  - cron: "0 9 * * 1"
    task: "Check poetry show --outdated. Create keeper tickets for critical updates."
    assign_to: keeper

  - cron: "0 23 * * *"
    task: "Summarize today's completed tasks from MEMORY.MD files. Write to projects/daily-log.md."
    assign_to: master
```

### How it works

```
APScheduler fires every 10 minutes
  → Cron agent runs
  → Reads schedule from NOTES.MD
  → For each job due since last check:
    → Creates task in task store: { source: "cron", schedule_id: "..." }
  → Dispatcher picks it up like any other task
```

---

## 6. Goals (self-directed)

**Status: not yet built — highest autonomy level**

The system works toward goals without any trigger. Between user tasks, between cron jobs,
Master reads GOALS.MD and picks the next goal to work on.

```
app/agents/master/GOALS.MD:

## Active
- [ ] Reduce average response latency — profile tool_call overhead
- [ ] Add docstrings to all public BaseAgent methods
- [ ] Investigate why builder occasionally produces syntax errors

## Backlog
- [ ] Write integration tests for the notification chain

## Done
- [x] Fix the TASK.MD race condition in AgentRunner
```

### How it works

```
Master receives wakeup (cron tick, notification, startup)
  → No pending user tasks in queue?
  → Read GOALS.MD
  → Pick top active goal
  → Treat it as a task: spawn planning, execute, update goal status
  → Continue until goal is done or blocked
```

User steers the system by editing GOALS.MD.
Master works without being asked.

---

## 7. CLI (legacy)

**Status: implemented — no changes needed**

```bash
poetry run yapoc chat "build a user auth module"
```

Calls `POST /task` on the local backend — same API as the UI.
Result is streamed back to the terminal.

The CLI remains the emergency fallback when the UI is unavailable.
It is not the primary interface.

---

## Entry point comparison

| Entry point | Human required | Async | Result delivery | Status |
|---|---|---|---|---|
| Mission Control | Yes | Needs fix | WebSocket | Partial |
| Telegram | No | Yes | Telegram reply + WebSocket | Not built |
| GitHub Webhook | No | Yes | WebSocket (no reply) | Not built |
| Generic Webhook | No | Yes | WebSocket + callback | Not built |
| Cron | No | Yes | WebSocket | Stub |
| Goals | No | Yes | WebSocket | Not built |
| CLI | Yes | No (streams) | Terminal | Done |
