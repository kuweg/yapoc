# Agent Autonomy — What's Missing

*Written: 2026-04-13*

YAPOC is currently a **reactive coding assistant with multi-agent architecture**.
Every action traces back to something the user typed. This document maps the gap between
that and a genuinely autonomous agent — one that exists and acts independently of the
user being present.

---

## The core problem: YAPOC is Claude Code with more steps

The fundamental loop is identical to Claude Code:

```
User types → Master reasons → Tools execute (file/shell/web) → Result returned
```

The multi-agent layer (Planning → Builder) is decomposition of a coding request.
It's not autonomy — it's better execution of a user-initiated task.

**Three things distinguish an autonomous agent from a coding assistant:**

1. **It acts when you're not there** — driven by goals, schedules, and events
2. **It perceives the outside world** — not just files and shells, but channels, APIs, signals
3. **It has a persistent identity** — state and intent that survive across sessions and restarts

YAPOC has none of these. The following sections map what needs to be built.

---

## Gap 1: No goal system (biggest missing piece)

### Current state
Master only acts when a message arrives. Between messages: nothing. No concept of
"what should I be doing right now?"

### What's needed: `GOALS.MD`

A prioritized list of ongoing objectives master maintains and works through:

```markdown
## Active
- [ ] Keep all tests green — check after every builder task
- [ ] Reduce token cost in hot paths — profile and optimize

## Backlog
- [ ] Write missing docstrings for public API surface
- [ ] Investigate why Doctor is firing warnings on model_manager

## Done
- [x] Implement ticket cascade completion
```

**Behavior change:**
On every wakeup (notification, cron tick, startup), master reads `GOALS.MD` first.
If no user task is pending and active goals exist → pick the top goal → work on it →
update status → go back to waiting.

User steers the system by editing `GOALS.MD`. Master executes without being asked.

**What needs to be built:**
- `GOALS.MD` schema and parser in master's context builder
- Goal-pick logic in `_master_notification_watcher` (already fires every 3s)
- Master PROMPT.MD section: "when no user task pending, check GOALS.MD"
- Tool or endpoint for master to update goal status

---

## Gap 2: Cron is a stub

### Current state
`_cron_tick()` in `main.py` spawns the cron agent every 10 minutes.
Cron agent has no schedule in `NOTES.MD` → immediately returns → notifies master →
master wastes a token processing an empty notification.

This was fixed (cron now skips if NOTES.MD is empty) but the underlying feature
— scheduled autonomous work — is not implemented.

### What's needed: real cron schedule

`app/agents/cron/NOTES.MD` should drive real recurring tasks:

```yaml
schedule:
  - cron: "0 */4 * * *"
    task: "Run pytest and create a ticket if any test fails"
    assign_to: builder

  - cron: "0 9 * * 1"
    task: "Check for outdated dependencies with `poetry show --outdated`, create tickets for critical ones"
    assign_to: keeper

  - cron: "*/30 * * * *"
    task: "Check if any agent HEALTH.MD has new ERROR entries. If yes, spawn doctor."
    assign_to: master

  - cron: "0 8 * * *"
    task: "Summarize what was built yesterday from MEMORY.MD files, write to projects/daily-log.md"
    assign_to: master
```

**What needs to be built:**
- Cron agent prompt: read schedule from NOTES.MD, execute due jobs, use `add_task_trace`
- Cron agent tools: needs `check_task_status`, `spawn_agent`, `notify_parent`
- Schedule parser (already hinted in docs, not built)

---

## Gap 3: Doctor detects but doesn't fix

### Current state
Doctor reads HEALTH.MD files, counts errors, writes summaries. It observes.
When it finds problems, it writes them to its own HEALTH_SUMMARY.MD.
Nothing happens as a result.

### What's needed: Doctor as a responder

Close the detect → fix loop:

| Detection | Response |
|---|---|
| Agent HEALTH.MD has 3+ recent ERRORs | Spawn planning with "investigate and fix {agent_name} errors" |
| Agent CRASH.MD has new entry | Spawn builder to read crash, identify root cause, propose fix |
| Agent stuck `in_progress` > 10 min | Kill agent + create retry ticket + notify master |
| Test file exists but hasn't run in 24h | Add task to cron schedule |

**What needs to be built:**
- Doctor PROMPT.MD: section on response actions, not just observation
- Doctor tools: add `spawn_agent`, `check_task_status`, `kill_agent`
- Doctor CONFIG.md: add delegation tools

---

## Gap 4: No feedback loop after builder finishes

### Current state
Builder writes code. Task is marked done. Nobody checks if the code works.
The user finds out when they manually run tests (or when things break).

### What's needed: verify-then-done loop

After builder completes a code task, planning should automatically:

```
builder done
    → planning reads result
    → planning spawns test-runner (shell_exec: pytest on affected files)
    → if tests pass: notify master with "done + tests green"
    → if tests fail: spawn builder again with test output as context
    → loop up to N times before escalating to master
```

This is a closed autonomy loop. Code isn't "done" until tests pass.
No user involvement required for the verification step.

**What needs to be built:**
- Planning PROMPT.MD: instruction to verify code changes if test files exist
- Test-runner pattern: `shell_exec("poetry run pytest {affected_paths} -x 2>&1")`
- Exit condition: max 3 retry loops before escalating

---

## Gap 5: No external world perception

### Current state
YAPOC is blind to the outside world unless the user explicitly asks it to `web_search`.
No events arrive that weren't initiated by the user.

### What's needed: at least one external input channel

Even a single channel transforms the identity of the system:

| Channel | What it enables |
|---|---|
| **Telegram bot** | User or collaborators can trigger tasks from phone while away from desk |
| **GitHub webhook** | New issue opened → ticket created in dashboard → agent picks it up |
| **Email hook** | Forward an email to a local endpoint → master summarizes + creates task |
| **File watcher** | File changed on disk → builder updates related files automatically |
| **HTTP webhook** | Any external system (CI, monitoring, alerts) can push a task into YAPOC |

A simple `POST /webhook/task` endpoint that writes to master's task queue is enough
to start. Combined with a Telegram bot or GitHub webhook, YAPOC stops being a
local tool and starts being an agent that exists in the world.

**What needs to be built:**
- `app/backend/routers/webhook.py`: `POST /webhook/task` with token auth
- (optional) Telegram bot adapter mirroring OpenClaw's approach
- (optional) GitHub webhook handler: creates a ticket from issue payload

---

## Gap 6: Session does not survive restarts

### Current state
`RESUME.MD` exists and is auto-populated on startup by scanning in-flight TASK.MD files.
But master doesn't proactively read it and continue working. It waits for a user message.

### What's needed: active resume on startup

On startup, master should:
1. Read `RESUME.MD` — find any in-flight tasks
2. Read `GOALS.MD` — find any active goals
3. If either has actionable items → immediately begin working without waiting for user

This is the difference between a service that *remembers* what it was doing and one
that *resumes* what it was doing.

**What needs to be built:**
- `_master_notification_watcher`: check RESUME.MD on first tick after startup
- Master PROMPT.MD: "on startup, check RESUME.MD and GOALS.MD before waiting for user"
- Startup trigger: `loop.call_later(2, lambda: asyncio.ensure_future(_resume_check()))`

---

## Gap 7: No self-improvement path

### Current state
`learnings_append` tool exists. Master can write rules to `LEARNINGS.MD`.
`LEARNINGS.MD` content is injected into master's system prompt on every turn.

This is good infrastructure. But agents rarely use it proactively, and there's no
mechanism for the system to act on accumulated learnings beyond prompting.

### What's needed: learning → behavior change

- **Prompt: agents should use `learnings_append` after recurring failures** — two
  occurrences of the same error class should trigger a learning
- **Model Manager should propose CONFIG.md changes** based on performance patterns
  (agent X keeps timing out → increase `task_timeout`)
- **Planning should consult `search_memory` before every task** to avoid
  repeating past mistakes — this tool exists but isn't mandated

---

## Summary: autonomy gap table

| Capability | Status | Effort | Impact |
|---|---|---|---|
| Goal system (GOALS.MD) | Missing | Medium | Critical |
| Real cron schedule | Missing | Small | High |
| Doctor fixes, not just detects | Partial | Medium | High |
| Test-verify loop after builder | Missing | Small | High |
| External input channel (webhook/Telegram) | Missing | Medium | High |
| Active resume on startup | Missing | Small | Medium |
| Self-improvement via learnings | Partial (tool exists) | Small | Medium |

---

## The one-sentence version

**YAPOC needs to switch from "answer when asked" to "work toward goals continuously,
fix what breaks, and accept signals from the outside world."**

The infrastructure is there. The goals, triggers, and feedback loops are not.
