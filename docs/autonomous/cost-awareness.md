# Cost Awareness — Self-Governing Resource Consumption

An autonomous agent that doesn't know it costs money is a liability.
This document defines how YAPOC governs its own resource consumption
at every level: per-call, per-turn, per-task, per-agent, per-day.

---

## Why cost awareness is a Level 3 requirement

At Level 1 (fire-and-forget), the user is implicitly accepting the cost
by initiating the task. At Level 3 (self-healing, cron, autonomous goals),
the system initiates work on its own. Nobody clicked "run this." The system
decided to spend money. It must be accountable for that decision.

Without cost governance, a single feedback loop can burn through a day's
budget in minutes:

```
Cron fires "run tests" → builder runs pytest → tests fail
  → doctor detects failure → spawns planning to investigate
    → planning spawns builder to fix → builder tries, fails again
      → doctor detects again → spawns planning again
        → infinite loop, each iteration costs $0.50-2.00
```

This loop is architecturally correct. Every component is doing its job.
It's also a $50/hour burn rate with no human in the loop.

---

## Current state

YAPOC already tracks costs. Per-agent, per-model, per-turn:

```
2026-04-12 12:05:05 [INFO ] [master] Usage turn=0 | in=3 out=252 cache_r=2430 cache_w=2385 tps=53.0 cost=$0.000000
```

What exists:
- `usage_tracker.py` — per-agent cost accumulation
- `USAGE.json` — per-agent usage stats
- `cli/renderer.py` — cost display in CLI
- `CostBar.tsx` — cost display in UI

What was added in M9D (April 2026):
- ✅ `budget_per_task_usd` — per-task cost limit, enforced in `run_stream_with_tools()` (`app/agents/base/__init__.py`)
- ✅ `budget_per_agent_usd` — per-agent cost limit, enforced per-turn in BaseAgent
- ✅ Runaway detection — `_detect_runaway_agents()` in Doctor, `cost_runaway_multiplier` setting (default 5×)
- ✅ Cost dashboard — `GET /metrics/usage`, `GET /metrics/usage/{name}` (`app/backend/routers/metrics.py`)

What does NOT exist yet:
- Daily autonomous budget (designed here, not built — Phase 4)
- Loop detection (consecutive tool calls — Phase 4)
- Cost injection into agent context ([COST] messages — Phase 4)
- Model routing based on task complexity (low priority)
- Cost-based decision making by agents (prompt-level)

---

## Five layers of cost governance

### Layer 1: Per-call awareness

Every LLM API call has a cost. The agent should know what it just spent.

```
After each turn, the agent receives:
  tokens_in: 2430
  tokens_out: 252
  cost_this_turn: $0.003
  cost_this_task: $0.15
  budget_remaining: $9.85
```

This is injected into the agent's context as a system message after each
turn (not in the prompt — in the conversation history). The agent can see
its own spending and make decisions accordingly.

**Implementation:**
- `BaseAgent._run_turn()`: after LLM response, append a system message
  with cost summary
- Format: `[COST] turn=$0.003 task=$0.15 remaining=$9.85/10.00`
- Agent prompt instruction: "Monitor [COST] messages. If task cost exceeds
  50% of budget_remaining, simplify your approach or escalate."

### Layer 2: Per-turn limits

No single turn should be catastrophically expensive. Guards against
prompt injection or pathological inputs that cause massive output.

```python
# app/agents/base/__init__.py

MAX_OUTPUT_TOKENS_PER_TURN = 16384  # hard cap
MAX_TOOL_CALLS_PER_TURN = 20       # prevents infinite tool loops
```

These are programmatic — not prompt instructions. The LLM cannot override them.

Already partially implemented:
- `max_turns` in settings (default 50) — limits total turns per task
- Tool call counting exists but doesn't enforce a per-turn limit

**Implementation:**
- After each tool call in a turn, increment counter
- If counter exceeds `MAX_TOOL_CALLS_PER_TURN`, inject message:
  "Tool call limit reached for this turn. Summarize progress and continue
  in the next turn."
- Output token limit: set `max_tokens` in LLM API call

### Layer 3: Per-task cost limit

A single task cannot spend more than a configured amount.

```python
# app/config/settings.py

task_cost_limit: float = 5.00  # USD — hard stop per task
```

When a task's accumulated cost reaches this limit:

```
1. Agent receives: [COST] LIMIT REACHED — $5.00/$5.00
2. Agent is given one final turn to summarize what was accomplished
3. Task is force-completed with partial result
4. Task store: status=done, result="[PARTIAL — cost limit] ..."
5. If the task was goal-driven or cron-driven: log, do not retry automatically
6. If the task was user-initiated: notify user with partial result
```

**Implementation:**
- Check accumulated cost in `_run_turn()` before calling LLM
- If cost >= limit: inject final-turn message, set `_force_stop = True`
- After final turn: mark task as done with partial result

### Layer 4: Per-agent daily tracking

Each agent tracks its daily spending. Visible in Mission Control's
Agents tab. No enforcement at this layer — this is observability.

```json
// USAGE.json
{
  "master": { "today": 1.23, "total": 45.67, "turns_today": 34 },
  "planning": { "today": 0.89, "total": 23.45, "turns_today": 22 },
  "builder": { "today": 2.15, "total": 67.89, "turns_today": 45 },
  "doctor": { "today": 0.12, "total": 3.45, "turns_today": 8 }
}
```

Already built. Needs: daily reset logic and surfacing in the Agents tab.

### Layer 5: Global daily budget

The most important guardrail. Total autonomous spending per day.

```python
# app/config/settings.py

daily_autonomous_budget: float = 10.00  # USD
```

Rules:
- Only counts autonomous tasks (cron, goals, doctor-initiated)
- Interactive tasks (user-initiated) do NOT count against this budget
- When budget is exhausted:
  - All autonomous work pauses (cron skips, goals pause, doctor observes only)
  - User-initiated tasks still work (user chose to spend)
  - Notification pushed to UI: "Daily autonomous budget exhausted ($10.00)"
  - If Telegram configured: message sent to user
- Budget resets at midnight (configurable timezone)
- Budget can be adjusted at runtime via Mission Control settings panel

**Implementation:**
- `cost_tracker.py` (new or extend `usage_tracker.py`):
  - `record_cost(agent, task_id, amount, autonomous: bool)`
  - `get_autonomous_spend_today() -> float`
  - `is_budget_exhausted() -> bool`
- Dispatcher checks `is_budget_exhausted()` before dispatching autonomous tasks
- Cron checks before spawning jobs
- Doctor checks before spawning repair tasks

---

## Runaway detection

Beyond budget limits, the system detects behavioral patterns that indicate
a loop or a stuck agent:

| Signal | Threshold | Action |
|---|---|---|
| Same tool called consecutively | 10+ times | Break loop: inject reflection message |
| Task cost > 3× median task cost | Per-task | Warning in HEALTH.MD |
| Task cost > 5× median task cost | Per-task | Pause agent, alert user |
| Agent turns without progress | 10 turns with no tool_result or file change | Force-stop, mark as error |
| Spawn depth exceeds limit | 5 levels deep (master→plan→build→...→???) | Deny further spawns |
| Same task retried | 3+ times for same prompt | Stop retrying, escalate to user |

### Loop detection in detail

The most common runaway: agent calls the same tool repeatedly with
slight variations, hoping for a different result.

```
Turn 5: shell_exec("pytest tests/test_auth.py") → FAIL
Turn 6: shell_exec("pytest tests/test_auth.py -v") → FAIL
Turn 7: shell_exec("pytest tests/test_auth.py -v --tb=long") → FAIL
Turn 8: shell_exec("pytest tests/test_auth.py -v --tb=short") → FAIL
...
```

Detection: track last N tool calls. If the same tool name appears
10+ times consecutively, inject:

```
[SYSTEM] You have called {tool} {count} times consecutively.
This suggests a loop. Stop and assess:
1. What are you trying to achieve?
2. Why isn't it working?
3. Is there a fundamentally different approach?
If you cannot make progress, call notify_parent with what you've learned.
```

This is a programmatic guardrail, not a prompt instruction. The agent
receives it as a system message that cannot be ignored.

**Implementation:**
- `_execute_tool()` in BaseAgent: maintain `_recent_tool_calls: deque(maxlen=15)`
- After each call: check if last 10 entries share the same tool name
- If yes: inject reflection message, set `_loop_detected = True`
- If agent calls the same tool again after reflection: force-stop the turn

---

## Model routing (cost optimization)

Not all subtasks need a frontier model. Cost-aware agents should route
to the cheapest model that can handle the task.

```
Task complexity → Model selection:
  Simple file read/write         → haiku ($0.25/M input)
  Test execution and reporting   → haiku
  Code generation (small)        → sonnet ($3/M input)
  Complex reasoning/planning     → sonnet or opus ($15/M input)
  Architecture decisions         → opus
```

### How it works in YAPOC

Agent CONFIG.md already supports model configuration. The extension:

```yaml
# app/agents/builder/CONFIG.md

model: claude-sonnet-4-5          # default model
model_routing:
  simple_tasks: claude-haiku-4-5  # file ops, formatting, simple edits
  complex_tasks: claude-sonnet-4-5 # code generation, debugging
  fallback: ollama/llama3          # when budget is tight
```

The agent doesn't choose its own model — the runner selects based on
task metadata:

```python
def select_model(task_prompt: str, budget_remaining: float) -> str:
    if budget_remaining < 1.00:
        return config.model_routing.get("fallback", config.model)
    if is_simple_task(task_prompt):
        return config.model_routing.get("simple_tasks", config.model)
    return config.model
```

`is_simple_task()` is a heuristic: task contains only file operations,
no reasoning required, short prompt. This can be a simple keyword check
or a haiku classifier (meta: using a cheap model to decide if you need
an expensive model).

**Implementation priority:** Low. This is optimization, not safety.
Build budget enforcement first. Add model routing when cost patterns
are visible from real usage data.

---

## Cost visibility in Mission Control

The UI should surface cost at every level:

### Chat tab
- Per-turn cost badge next to each agent response
- Running task cost in the header
- "Budget: $7.23 / $10.00 remaining" indicator

### Agents tab
- Per-agent daily cost
- Per-agent total cost
- Cost trend (sparkline over last 7 days)
- Top cost driver highlighted

### Dashboard tab
- Per-ticket cost (sum of all tasks for that ticket)
- Cost column in kanban cards

### Settings panel
- Daily autonomous budget (editable)
- Per-task cost limit (editable)
- Current day's spending breakdown

---

## Cost awareness as agent behavior

Beyond programmatic limits, the agent should reason about cost.
This is prompt-level, not code-level, but it matters:

```markdown
# In master/PROMPT.MD

## Cost Awareness

You have a budget. Every LLM call, every tool invocation costs money.

Rules:
1. Check [COST] messages after each turn. If task cost > 50% of remaining
   daily budget, simplify your approach.
2. Prefer spawning agents with cheaper models for simple subtasks.
3. Do not retry the same failing approach more than twice. If it didn't
   work twice, it won't work a third time — change strategy or escalate.
4. When decomposing tasks, prefer fewer subtasks with broader scope over
   many narrow subtasks. Each spawn has fixed overhead.
5. If a task can be done with file_read + file_write, do not spawn a
   sub-agent. Direct tool use is 10x cheaper than delegation.
```

This is guidance, not enforcement. The programmatic limits in Layers 1-5
are the real guardrails. The prompt guidance helps the agent make better
decisions within those limits.

---

## Implementation priority

```
Phase 4 (alongside autonomous approval):
  ├── Per-task cost limit enforcement
  ├── Daily autonomous budget enforcement
  ├── Loop detection (consecutive tool calls)
  └── Cost injection into agent context ([COST] messages)

Phase 6 (alongside external entry points):
  ├── Spawn depth limit
  ├── Retry deduplication (same task retried 3x → stop)
  └── Cost visibility in Mission Control

Later:
  ├── Model routing
  ├── Cost trend analytics
  └── Budget adjustment via UI
```

Budget enforcement and loop detection are Level 3 requirements.
Model routing is optimization. Build the guardrails first.
