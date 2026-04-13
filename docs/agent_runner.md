# Agent Runner

The agent runner is the core execution engine. It manages the lifecycle of a single agent: assembling context, calling the LLM, executing tool calls, and writing results.

> **Implementation status:** The watchdog-based runner is **implemented** in `app/agents/base/runner.py` (`AgentRunner` class). It watches TASK.MD for changes, manages STATUS.json lifecycle, and spawns agent subprocesses. Context assembly is implemented in `app/agents/base/context.py` (`build_system_context()`). Direct execution is also available via `BaseAgent` methods (`run()`, `run_stream()`, `run_stream_with_tools()`) used by the CLI and API.

---

## Trigger Mechanism (implemented)

The runner uses **watchdog** to monitor the agent's `TASK.MD` for changes. When a write is detected:

1. Runner reads `TASK.MD` and parses the frontmatter.
2. If `status: pending`, the runner picks up the task and sets `status: running`.
3. If `status` is anything else, the runner ignores the event.

As a fallback, runners will also poll `TASK.MD` every **30 seconds** in case a watchdog event is missed (e.g., NFS, Docker volumes).

---

## Context Assembly

### Context Assembly (implemented)

`build_system_context()` in `app/agents/base/context.py` assembles the system prompt from multiple agent files:

| Order | Source | Role | Always loaded |
|-------|--------|------|---------------|
| 1 | `PROMPT.MD` | `system` | Yes |
| 2 | `MEMORY.MD` (last N entries) | `system` | Yes, if non-empty |
| 3 | `NOTES.MD` | `system` | Yes, if non-empty |
| 4 | `HEALTH.MD` (last N entries) | `system` | Yes, if non-empty |

Sections are joined with `---` separators. Empty sections are omitted. Limits are configurable per agent in CONFIG.md:
- `runner.context_memory_limit` (default: 50) — max MEMORY.MD lines
- `runner.context_health_limit` (default: 10) — max HEALTH.MD lines

The function parses CONFIG.md's `runner:` block to get these limits.

**Auto-compaction:** When context approaches the model's window limit (~85%), `app/utils/context.py` automatically summarizes the conversation history, re-injecting the system prompt fresh. The CLI shows "Context compacted: X,XXX → Y,YYY tokens".

---

## Execution Mode: Multi-Turn with Tools

The runner operates in a **tool-use loop**, not one-shot:

```
1. Send assembled context to LLM (with tool schemas)
2. LLM responds with either:
   a. Text only       → go to step 5
   b. Tool call(s)    → go to step 3
3. Execute tool call(s), collect results
4. Append tool results to conversation history → go to step 1
5. Write final text response to TASK.MD Result section
6. Set status: done
7. Append summary to MEMORY.MD
```

### Turn Limit

Maximum **20 turns** per task (a turn = one LLM call). If the limit is reached without completion, the runner:
- Sets `status: error`
- Writes "Turn limit exceeded" to the Error section
- Logs to HEALTH.MD

### Parallel Tool Calls

If the LLM returns multiple tool calls in one response, the runner executes them concurrently via `asyncio.gather`. Results are returned in the same order.

---

## Timeout

Each task has a **5-minute wall-clock timeout** (configurable in `CONFIG.md`). If exceeded:
- The runner cancels the current LLM call / tool execution
- Sets `status: error` with "Task timeout" in Error section
- Logs to HEALTH.MD

---

## Error Handling

| Error | Runner behavior |
|-------|----------------|
| LLM API call fails (network, rate limit) | Retry up to 3 times with exponential backoff (1s, 4s, 16s). On final failure → `status: error` |
| Tool execution fails (exception) | Return error message to LLM as tool result. LLM can retry or adjust. |
| Tool returns invalid output | Treat as tool failure (above) |
| Agent writes malformed TASK.MD | Runner logs parse error to HEALTH.MD, sets `status: error` |
| Unhandled exception in runner | Catch at top level, log to HEALTH.MD, set `status: error` |

Errors never crash the runner process. The runner always returns to its idle watch state after a task completes or fails.

---

## Runner Lifecycle

```
Runner start
  │
  ├─ Load CONFIG.md → instantiate adapter + register tools
  ├─ Start watchdog on TASK.MD
  ├─ Start fallback poll timer (30s)
  │
  ▼
Idle (watching)
  │
  ├─ TASK.MD change detected, status: pending
  │   ├─ Set status: running
  │   ├─ Assemble context
  │   ├─ Enter tool-use loop
  │   ├─ Write result / error
  │   └─ Return to Idle
  │
  ├─ TASK.MD change, status: not pending → ignore
  │
  └─ Shutdown signal → clean up, exit
```

---

## File Location

```
app/agents/base/
    __init__.py         # BaseAgent class (run, stream, tool loop, direct execution)
    runner.py           # AgentRunner class (implemented — watchdog-based TASK.MD watcher)
    runner_entry.py     # Subprocess entry point for spawned agents
    context.py          # Context assembly (implemented — build_system_context())
```

---

## Configuration

Runner behavior is configurable per agent in `CONFIG.md`:

```yaml
runner:
  max_turns: 20
  task_timeout: 300       # seconds
  poll_interval: 30       # seconds
  retry_attempts: 3
  context_memory_limit: 50  # max MEMORY.MD entries in context
  context_health_limit: 10  # max HEALTH.MD entries in context
```
