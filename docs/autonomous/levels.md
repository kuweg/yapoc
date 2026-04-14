# Autonomy Levels — What Each Level Means and What YAPOC Needs

This is the definitive reference for what "autonomous" means in YAPOC.
Each level is defined by observable behavior, not aspirational language.
The test is simple: what does the system do when no human is present?

---

## The litmus test

An agent is truly autonomous when you can turn off your phone, fly to
another country, and come back in a week — and the system has been doing
useful work the entire time without a single human input.

Not "it kept running." Not "it didn't crash."
It made decisions, encountered problems, solved them, and produced value.

---

## Level 0 — Request-Response

**Behavior:** System waits for human input. Does nothing between messages.
Every action traces back to something the user typed.

**Examples:** ChatGPT, most coding assistants, YAPOC's current API boundary.

**What it looks like:**
```
User types → agent thinks → agent responds → silence until next message
```

**YAPOC at Level 0:** The sync POST /task endpoint. Close the browser,
task dies. No persistence, no background execution, no initiative.

---

## Level 1 — Fire and Forget

**Behavior:** System accepts a task and continues executing after the human
disconnects. The task completes whether the user is watching or not.
Result is persisted and available when the user returns.

**Observable test:** Create a task. Close the browser immediately.
Come back in 10 minutes. The result is there.

**What it requires:**

| Requirement | YAPOC status | Documented in |
|---|---|---|
| Async task endpoint (returns immediately) | Not built | [execution-engine.md](execution-engine.md) |
| Task Store persistence (SQLite) | Built | [architecture.md](architecture.md) |
| Task Dispatcher (background loop) | Not built | [execution-engine.md](execution-engine.md) |
| Notification listener (closes the loop) | **Built** — `NotificationQueue`, `NotificationPoller`, `_master_notification_watcher()` | [delivery.md](delivery.md) |
| WebSocket push (result delivery) | Not built | [delivery.md](delivery.md) |
| UI catch-up on reconnect | Not built | [delivery.md](delivery.md) |

**What it does NOT require:**
- Self-healing (agent errors are reported, not fixed)
- Self-direction (system only works on what you asked for)
- External channels (UI is sufficient)

**Roadmap:** Phase 1

---

## Level 2 — Self-Managing

**Behavior:** System tracks its own state, persists across restarts,
recovers interrupted work, and provides real-time observability.
The human can watch the system think (interactive mode) or leave
(autonomous mode) and switch between them freely.

**Observable test:** Start a long task. Kill the server mid-execution.
Restart the server. The task resumes or re-runs automatically.
Open the Chat tab — see the full execution history including what
happened before the restart.

**What it requires (on top of Level 1):**

| Requirement | YAPOC status | Documented in |
|---|---|---|
| Task recovery on restart | Not built | [execution-engine.md](execution-engine.md) |
| Session persistence (conversation context) | Built (JSONL) | [architecture.md](architecture.md) |
| Streaming events (agent → UI) | Not built | [streaming.md](streaming.md) |
| Interactive mode (watch + steer) | Not built | [streaming.md](streaming.md) |
| Session playback (catch up on missed events) | Not built | [streaming.md](streaming.md) |
| Interactive tool approval (CONFIRM-tier) | Not built | [safety.md](safety.md) |
| Dispatcher deduplication | Not built | [execution-engine.md](execution-engine.md) |

**What it does NOT require:**
- Autonomous tool approval (user approves interactively when present)
- Self-direction (no goals, no cron)
- Self-healing (errors reported, not auto-fixed)

**Roadmap:** Phases 2–3

---

## Level 3 — Self-Healing

**Behavior:** System detects failures, diagnoses root causes, and repairs
itself without human intervention. It handles CONFIRM-tier tools safely
when no human is present. It executes scheduled work on a timer.
It governs its own resource consumption.

**Observable test:** Leave the system running for 48 hours with active
cron jobs. Introduce failures: kill an agent mid-task, write invalid
Python in a project file, let a task timeout. Come back. The system
has detected each failure, attempted repair, escalated what it couldn't
fix, and continued working on scheduled tasks. API spend is within budget.

**What it requires (on top of Level 2):**

| Requirement | YAPOC status | Documented in |
|---|---|---|
| Autonomous tool approval policy | Not built | [safety.md](safety.md) |
| Approval queue (for tools that can't auto-approve) | Not built | [safety.md](safety.md) |
| Doctor as actor (detect AND respond) | Detection built, response not | [self-direction.md](self-direction.md) |
| Doctor autonomy envelope | Not built | [safety.md](safety.md) |
| Cron schedule (real, not stub) | **APScheduler + subprocess (M7)** — needs real schedule parsing | [self-direction.md](self-direction.md) |
| Cost-aware self-governance | **Per-task + per-agent limits built (M9D)** | [cost-awareness.md](cost-awareness.md) |
| Daily budget enforcement | Not built (Phase 4) | [cost-awareness.md](cost-awareness.md) |
| Runaway detection | **Built (M9D)** — Doctor `_detect_runaway_agents()` | [cost-awareness.md](cost-awareness.md) |
| Programmatic behavioral guardrails | Partial (sandbox only) | [safety.md](safety.md), [risks.md](risks.md) R4 |
| Active resume on startup | Not built | [self-direction.md](self-direction.md) |

### Level 3 properties in detail

#### 3A. Closed-loop error recovery

Not just "log the error." Close the loop:

```
Builder fails
  → Planning reads the error output
  → Planning adjusts the approach (different tool, different strategy)
  → Planning retries with the adjusted approach
  → If retry fails: escalates with context about what was tried
  → Master either tries a different decomposition or marks as [DECISION NEEDED]
```

Currently: the prompt tells agents to do this. No programmatic enforcement.
The LLM decides whether to actually retry or just give up.

**What needs to be built:**
- Retry counter in `_execute_tool()` — track consecutive failures per tool type
- Forced retry injection: if builder fails and planning doesn't retry within
  the same task, the runner injects a "retry with different approach" message
- Escalation timeout: if a task has been in error-recovery for > 5 minutes,
  force escalation to master

#### 3B. Doctor response actions

Doctor detects → Doctor acts. The full loop:

| Detection | Response | Autonomy envelope |
|---|---|---|
| 3+ errors in agent HEALTH.MD | Spawn planning to investigate | Can spawn planning/builder |
| Stale task (running > 2× timeout) | Kill agent, reset task to pending | Can kill builder/keeper/cron |
| Zombie task (PID dead, status=running) | Clean up STATUS.json, reset task | Can modify STATUS.json |
| Cross-agent error pattern | Create master ticket | Can create tasks |
| Test suite not run in 48h | Add to cron schedule | Can modify cron/NOTES.MD |
| Builder produced invalid syntax | Spawn builder with fix task | Can spawn builder |

What Doctor CANNOT do (hard rules, enforced in code):
- Kill master or itself
- Modify any PROMPT.MD
- Modify settings.py
- Spawn more than 3 tasks per run
- Override the approval queue

#### 3C. Cron — scheduled autonomous work

Real schedule, real execution, no human trigger:

```yaml
# cron/NOTES.MD
schedule:
  - id: daily-tests
    cron: "0 8 * * *"
    task: "Run full test suite. Create ticket for failures."
    assign_to: builder

  - id: health-sweep
    cron: "0 */4 * * *"
    task: "Check all HEALTH.MD files. Summarize errors."
    assign_to: doctor

  - id: daily-digest
    cron: "0 23 * * *"
    task: "Summarize today's completed tasks."
    assign_to: master
```

#### 3D. Cost-aware self-governance

The system knows it costs money and governs itself:

- Daily autonomous budget (default $10) — when hit, autonomous work pauses
- Per-task cost limit (default $5) — runaway tasks killed
- Model routing: cheap model for simple subtasks, expensive for complex reasoning
- Runaway detection: same tool called 10+ times → break loop
- Token tracking per agent, per task, per day — visible in Mission Control

Full details: [cost-awareness.md](cost-awareness.md)

#### 3E. Autonomous tool approval

When no human is present, CONFIRM-tier tools are handled by policy:

```yaml
# builder/CONFIG.md
autonomous_policy:
  shell_exec:
    auto_approve: ["poetry run pytest*", "ls *", "cat *"]
    deny: ["rm -rf *", "sudo *", "curl * | bash"]
    default: queue
```

- `auto_approve`: pattern match → execute immediately
- `deny`: pattern match → deny, agent must find alternative
- `queue`: add to approval queue → agent pauses → user approves on return
- Queue items expire after 24 hours → auto-denied

Full details: [safety.md](safety.md)

**Roadmap:** Phases 4–7

---

## Level 4 — Self-Directed (target, not yet designed in detail)

**Behavior:** System decides what to work on without being asked.
It has ongoing goals, identifies new problems proactively, and
improves its own processes based on accumulated experience.

**Observable test:** Set up GOALS.MD with 5 objectives. Leave the system
running for a week. Come back. Goals have been progressed or completed.
New goals have been identified from patterns the system observed.
LEARNINGS.MD has entries that demonstrably changed agent behavior.

**What it requires (on top of Level 3):**

| Requirement | YAPOC status | Documented in |
|---|---|---|
| GOALS.MD system (persistent intent) | Designed, not built | [self-direction.md](self-direction.md) |
| Goal-driven behavior in master | Not built | [self-direction.md](self-direction.md) |
| Compounding knowledge (learnings → behavior) | Infrastructure built, usage low | [self-direction.md](self-direction.md) |
| Environmental perception (beyond own files) | Narrow | [entry-points.md](entry-points.md) |
| External entry points (webhooks, Telegram) | Not built | [entry-points.md](entry-points.md) |
| Goal generation (system identifies new goals) | Not designed | — |

Level 4 is the aspiration. Level 3 is what must be solid first.
Do not build Level 4 features until Level 3 passes the 48-hour test.

---

## Current state summary

```
Level 0  ████████████████████  fully operational (request-response works)
Level 1  ████░░░░░░░░░░░░░░░░  notifications built, SSE streaming built — async API + dispatcher missing
Level 2  ███░░░░░░░░░░░░░░░░░  sessions built, SSE streaming built — WebSocket streaming + recovery missing
Level 3  ███░░░░░░░░░░░░░░░░░  cost enforcement + runaway detection built — approval policy + daily budget + doctor actions missing
Level 4  ░░░░░░░░░░░░░░░░░░░░  goals designed, nothing active
```

The progress bar is misleading because the infrastructure underneath
Level 3 is extensive (20+ tools, SQLite, embeddings, Doctor, cost tracking,
notification chain, spawn registry, learnings, shared knowledge, peer delegation).
What's missing is the connective tissue at the top: async API, dispatcher,
streaming, approval policy, budget enforcement.

---

## The five properties of true autonomy

For reference. These are the properties an agent needs to pass the
"fly to another country" test:

| Property | What it means | YAPOC mechanism |
|---|---|---|
| **Persistent intent** | Goals survive sessions and restarts | GOALS.MD + RESUME.MD |
| **Closed-loop recovery** | Diagnose, adjust, retry, escalate | Doctor + retry logic + error recovery prompts |
| **Environmental perception** | Notice things without being told | Cron + webhooks + file watchers |
| **Resource-aware self-governance** | Don't burn money, don't cause damage | Budget limits + approval policy + runaway detection |
| **Compounding knowledge** | Get better over time | LEARNINGS.MD + search_memory + behavioral change |

No system has all five today. YAPOC has infrastructure for all five.
The gap is activation, not architecture.
