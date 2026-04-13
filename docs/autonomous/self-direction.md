# Self-Direction

How YAPOC acts without a human trigger.
This is the difference between a tool and an agent.

A tool waits to be used.
An agent has work it is always moving toward.

---

## Three sources of self-directed work

```
1. GOALS.MD     — ongoing objectives master works toward when idle
2. Cron         — scheduled tasks that fire on a time basis
3. Doctor       — anomaly detection that generates repair tasks
```

Together these mean the system is never truly idle.
There is always something to do. The human sets direction; the system executes.

---

## 1. Goals

### What it is

`app/agents/master/GOALS.MD` is a prioritized list of objectives.
Master reads it on every wakeup and works on the top active goal
when no user task is pending.

### Format

```markdown
# GOALS

## Active
- [ ] Keep test suite green — run after every builder task, create tickets for failures
- [ ] Reduce tool call overhead — profile and find bottlenecks above 500ms
- [ ] Document all public BaseAgent methods

## Backlog
- [ ] Investigate builder syntax error patterns from last month
- [ ] Add memory compaction for agents with MEMORY.MD > 500 lines

## Done
- [x] Fix AgentRunner race condition on concurrent TASK.MD writes
- [x] Implement hybrid RRF search for memory retrieval
```

### Behavior

```
Master wakes up (any trigger — notification, cron, startup)
  → Is there a pending user task? → yes: handle user task
  → No user task pending?
    → Read GOALS.MD
    → Pick top active unchecked goal
    → Treat it as a task: spawn planning, execute
    → On completion: mark goal as [x] in GOALS.MD
    → Go back to waiting
```

### What this enables

- System continues producing value between user sessions
- Background maintenance happens automatically (tests, docs, cleanup)
- User can steer the system's focus without being present by editing GOALS.MD
- "Set it and forget it" for ongoing concerns

### What needs to be built

- `GOALS.MD` parser in `app/agents/base/context.py` (include in master's context)
- Goal-pick logic in master's prompt: "when no user task, check GOALS.MD and work on top goal"
- Goal-update tool or prompt instruction: master marks goals done after completion
- Master PROMPT.MD section: `## Goal-Driven Behavior`

---

## 2. Cron

### What it is

The Cron agent runs on APScheduler's 10-minute tick.
It reads a schedule from its own `NOTES.MD` and fires tasks for due jobs.
No human involvement needed.

### Schedule format

```yaml
# app/agents/cron/NOTES.MD

schedule:
  - id: daily-tests
    cron: "0 8 * * *"
    task: "Run the full test suite with `poetry run pytest`. Create a ticket for any failure."
    assign_to: builder

  - id: health-check
    cron: "0 */4 * * *"
    task: "Read all agent HEALTH.MD files. Summarize errors in the last 4 hours. Write to projects/health-digest.md."
    assign_to: doctor

  - id: weekly-deps
    cron: "0 9 * * 1"
    task: "Run `poetry show --outdated`. Create keeper tickets for packages with security advisories."
    assign_to: keeper

  - id: daily-digest
    cron: "0 23 * * *"
    task: "Summarize today's completed tasks from all agent MEMORY.MD files. Write to projects/daily-log.md."
    assign_to: master

  - id: context-compaction
    cron: "0 */6 * * *"
    task: "Check agent MEMORY.MD files. Archive entries older than 7 days to MEMORY_ARCHIVE/YYYY-MM.md."
    assign_to: builder
```

### What needs to be built

- Cron agent prompt: read NOTES.MD, find due jobs, spawn appropriate agent
- Cron needs `spawn_agent` and `add_task_trace` in its CONFIG.md tools
- Schedule parser: compare job `cron` expression against current time + last run timestamp
- Last-run tracking: `app/agents/cron/last_runs.json` or a `cron_runs` table in SQLite

---

## 3. Doctor as an actor

### Current state

Doctor detects problems and writes to HEALTH_SUMMARY.MD.
That is observation, not action. Nothing happens as a result of the detection.

### Target state

Doctor closes the loop. When it detects a problem, it creates a task to fix it.

| Detection | Action |
|---|---|
| Agent HEALTH.MD has 3+ errors in last hour | Spawn planning: "investigate and fix {agent_name} errors" |
| Stale task detected (running > 2× timeout) | Kill agent via `kill_agent`, create retry task, notify master |
| Zombie task (STATUS.json=running, PID dead) | Clean up STATUS.json, reset task to pending in task store |
| Cross-agent pattern (3+ agents, same error) | Create master ticket: "systemic error across agents: {pattern}" |
| Builder produced syntactically invalid Python | Spawn builder with error context to fix the file |
| Test suite has not run in 48 hours | Add job to cron schedule: run tests now |

### Autonomy envelope for Doctor

Doctor must operate within defined boundaries — it cannot do anything:

```yaml
# app/agents/doctor/CONFIG.md

autonomy_envelope:
  can_kill_agents: [builder, keeper, cron]   # not master, not itself
  can_create_tasks: true
  can_modify_files: [HEALTH.MD, HEALTH_SUMMARY.MD]
  cannot_modify_files: [TASK.MD, PROMPT.MD, settings.py]
  max_tasks_per_run: 3
  escalate_to_master_if: "cannot determine root cause after 2 attempts"
```

### What needs to be built

- Doctor PROMPT.MD: response actions section, not just observation
- Doctor tools: add `spawn_agent`, `kill_agent`, `check_task_status`
- Doctor CONFIG.md: add delegation tools + autonomy envelope
- Separate `_act_on_findings()` method from `_detect_*()` methods in `doctor/agent.py`

---

## 4. Resume on startup

### Current state

`RESUME.MD` is populated on startup by scanning in-flight TASK.MD files.
Master does not proactively read it. It waits for a user message.

### Target state

On startup, master actively resumes interrupted work.

```
Server starts
  → Dispatcher recovers running tasks (resets to pending)
  → Master startup hook fires after 2 seconds:
    → Reads RESUME.MD
    → Reads GOALS.MD
    → If RESUME.MD has incomplete tasks: continues them
    → If GOALS.MD has active goals and no user task: starts working on top goal
    → Logs "resumed N tasks, working on goal: {title}"
```

### What needs to be built

- Startup hook in `app/backend/main.py`: `asyncio.create_task(_startup_resume())`
- `_startup_resume()`: reads RESUME.MD, creates task store entries for each incomplete task
- Master PROMPT.MD: "on startup check, read RESUME.MD and continue any incomplete work"

---

## Self-direction hierarchy

When master wakes up, it follows this priority order:

```
1. CONFIRM-tier tool waiting for approval    ← highest priority (unblocks execution)
2. Pending user task in task store           ← user asked for something
3. Incomplete task from RESUME.MD            ← was working on something before restart
4. Doctor escalation or health alert         ← something is broken
5. Active goal from GOALS.MD                 ← ongoing work
6. Cron-generated task                       ← scheduled maintenance
7. Nothing to do → idle, wait for next tick  ← lowest priority
```

This priority order ensures:
- Users are always served first
- Broken things are fixed before new goals are pursued
- The system is never truly idle when there is work to do
