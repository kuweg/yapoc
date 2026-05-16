# Master Agent Audit Report

Comprehensive trace of three persistent problems. File:line references throughout.

---

## 1. Master Goes Idle Unexpectedly

### 1.1 All Code Paths Where Master Transitions to Idle

| Location | Code | Trigger |
|---|---|---|
| `app/agents/master/agent.py:20` | `self._write_status("idle")` | MasterAgent construction |
| `app/agents/master/agent.py:79` | `self._write_status("idle")` | `handle_task` finally block |
| `app/agents/master/agent.py:129` | `self._write_status("idle")` | `handle_task_stream` finally block |
| `app/backend/main.py:48` | `status["state"] = "terminated"` | `_cleanup_stale_agent_statuses` on startup, if master PID dead |

**Root cause pathways that prevent master from leaving idle:**

### 1.2 Guard: STATUS.json "running" Check — Drops Notifications Permanently

**Critical bug in `_master_redis_watcher` → `_process_inbox_message`:**

```
app/backend/main.py:324-331
```
```python
# Guard: don't interrupt a running master
try:
    state = json.loads(status_path.read_text()).get("state", "")
    if state == "running":
        await _bus.stream_ack(inbox, group, msg_id)  # ACKs BEFORE processing
        return                                        # notification LOST
except Exception:
    pass
```

**Root cause**: When master is already processing a task (STATUS.json = "running") and a Redis `task_result` message arrives, the message is ACKed (line 328) and discarded (line 329 return). This notification is **permanently lost** — no retry, no fallback to notification_queue. The sub-agent's result silently disappears.

**Same pattern in `_master_notification_watcher`:**
```
app/backend/main.py:122-130
```
```python
if state == "running":
    continue  # skips, will retry next poll (not permanently lost)
```
This watcher correctly just skips and retries on next poll — it does NOT consume the notification. The Redis watcher is the broken one.

**Fix**: Do not ACK before successfully processing. Skip the message (do not ACK) when master is busy; the message stays in the Redis stream pending list and will be re-delivered on next `stream_read_group` (with `>` for new messages) or claimed via `stream_claim_pending`. Alternatively, fall back to enqueuing into `notification_queue` so the notification watcher picks it up.

### 1.3 Guard: Redis Watcher Exception Swallowing

```
app/backend/main.py:384-388
```
```python
except Exception as _proc_exc:
    logger.warning("Redis master watcher: processing failed: {}", _proc_exc)

# ACK after successful processing (or best-effort on error)
await _bus.stream_ack(inbox, group, msg_id)
```

**Root cause**: If `master_agent.handle_task_stream` raises an exception, the message is still ACKed (line 388, unconditional). The notification is lost. The exception handler at line 384-385 logs the error but does NOT re-enqueue to notification_queue as a fallback.

### 1.4 Guard: _run_lock Contention

```
app/agents/master/agent.py:17, 69, 89
```
```python
self._run_lock = asyncio.Lock()
async with self._run_lock:  # blocks concurrent callers
```

**Root cause**: `handle_task` and `handle_task_stream` both acquire `_run_lock`. If the dispatcher (`_execute_task`) holds the lock processing a user task, both notification watchers are blocked:
- **Redis watcher**: `_process_inbox_message` calls `master_agent.handle_task_stream` which blocks on `_run_lock`. Meanwhile, the outer loop's `_bus.stream_read_group` with `block_ms=5000` may timeout (5s). If the lock is held longer than 5s, the Redis read returns empty, and no further processing happens until the next poll. The message stays in the stream (it was NOT yet read with `>`) and will be re-delivered. **However**, if the task is processed before the next 5s block, the message is seen and handled.
- **Notification watcher**: Checks STATUS.json = "running" (line 124) and skips — correct behavior.
- **But there's a race**: The status check at line 124 is NOT atomic with the `_run_lock` acquisition. Between checking STATUS.json and acquiring the lock, another task could start.

### 1.5 Guard: TASK.MD Status Must Be "pending"

```
app/backend/main.py:113
```
```python
if not re.search(r"^status:\s*pending", content, re.MULTILINE):
    continue
```

**Root cause**: `_master_notification_watcher` only fires when TASK.MD has `status: pending`. If a previous notification task left TASK.MD in "done" or "error" state (because `run_stream_with_tools` cleared it via `manage_task_file=True` default, which is NOT passed explicitly by the watcher), the watcher skips. However, `handle_task_stream` calls `run_stream_with_tools` with *default* `manage_task_file=True` which clears TASK.MD after run (init.py:1000). So after processing, TASK.MD is empty (no frontmatter). Next trigger write to TASK.MD will have `status: pending` — this guard works correctly.

**But there's a subtlety**: `NotifyParentTool` → `_wake_agent_if_idle` writes the trigger TASK.MD with `status: pending`. The watcher's regex check at line 113 expects `^status:\s*pending` in multiline mode. The trigger template at `delegation.py:762-773` writes it correctly. OK.

### 1.6 Guard: Must Match Notification Trigger Pattern

```
app/backend/main.py:116-118
```
```python
trigger_body = re.search(r"\[Process incoming notifications from sub-agents\]", content)
if not trigger_body:
    continue  # user task — leave it alone
```

**Root cause**: This guard prevents the watcher from processing user-sent tasks. It only handles notification triggers. Correct behavior.

### 1.7 _startup_resume — What It Does and What It Misses

```
app/backend/main.py:391-509
```

**What it does correctly**:
1. Reads `RESUME.MD` for `next_action` and creates task_queue entries (line 413-431)
2. Claims pending Redis messages from `master_group` consumer group (line 450)
3. Enqueues those messages into `notification_queue` instead of processing directly (line 467)
4. Checks `GOALS.MD` for unchecked active goals and creates tasks (line 483-504)
5. Calls `get_tasks_by_status("running")` in lifespan to recover stale running tasks (line 574-578)

**What's fragile**:
- Claims only 10 messages at a time (`stream_claim_pending` has `count=10` in message_bus.py:193). If more than 10 messages are pending, the rest are left unclaimed. On subsequent calls of `_master_redis_watcher`, they will be picked up, but this means master won't process them during the resume phase.
- **Race condition**: `_startup_resume` runs via `loop.call_later(5, ...)` (line 613). By the time it runs, `_master_redis_watcher` (line 604) and `_master_notification_watcher` (line 605) are already running. All three could compete for the same pending messages.

### 1.8 Additional Idle Trap: _check_task Returns False for Empty Task Body

```
app/agents/base/runner.py:343-352
```
```python
async def _check_task(self) -> bool:
    status = await self._agent.get_task_status()
    if status == "pending":
        task_body = await self._agent.get_task_body()
        if task_body:                    # if empty, returns False
            await self._run_task(task_body)
            return True
    return False
```

If TASK.MD has `status: pending` but an empty `## Task` section, the runner sees a pending task but does nothing and returns False. This matters for the notification watcher self-trigger path (runner.py:670-718), where `_wake_agent_if_idle` writes a trigger that the runner then self-processes.

### Summary for Problem 1

| Issue | Severity | File:Line |
|---|---|---|
| Redis watcher drops notifications when master is running | **Critical** | `main.py:327-329` |
| Redis watcher ACKs on error — notification lost | **High** | `main.py:384-388` |
| Notification watcher skips correctly on running (retries) | OK | `main.py:122-130` |
| `_run_lock` contention blocks watchers | **Medium** | `agent.py:89` |
| Race between status check and lock acquisition | **Low** | `main.py:122-130` |
| Startup resume competes with already-running watchers | **Medium** | `main.py:604-613` |
| STATUS.json exception swallows silently in watcher | **Low** | `main.py:126-130` |
| TASK.MD guard prevents user-task interference | OK | `main.py:113-118` |

---

## 2. Turn Limitations

### 2.1 max_turns — The Primary Limiter

```
app/config/settings.py:60
```
```python
max_turns: int = 999
```

**Usage in `run_stream_with_tools`:**
```
app/agents/base/__init__.py:729
```
```python
max_turns = _runner.get("max_turns", settings.max_turns)
```

**Master CONFIG.yaml runner block** (`app/agents/master/CONFIG.yaml:41-47`):
```yaml
runner:
  task_timeout: 300
  poll_interval: 30
  retry_attempts: 3
  context_memory_limit: 10
  context_health_limit: 5
  context_notes_limit: 3000
```

**Master has NO `max_turns` in its CONFIG.yaml runner block.** Falls back to `settings.max_turns` = 999. No hard low limit here.

### 2.2 notification_max_turns — Documented but NOT Implemented

The CLAUDE.md at `app/agents/base/CLAUDE.md:35` states:
> Notification tasks are capped at `settings.notification_max_turns` (3)

**This setting does NOT exist in `app/config/settings.py` and is NOT referenced in ANY `.py` file.** Grep: zero matches for `notification_max_turns` in Python files. The notification-processing tasks (`[Process incoming...]`) run with the full `max_turns` (999). There is no turn cap for notification tasks.

### 2.3 Auto-Compaction — Context Compact Threshold

```
app/agents/base/__init__.py:730-732
```
```python
threshold_tokens = int(
    adapter.context_window_size() * settings.context_compact_threshold
)
```

- **Master's model**: `deepseek-chat` (from CONFIG.yaml, line 2)
- **Context window**: 64,000 tokens (`app/utils/adapters/models/deepseek.py:13`)
- **Threshold**: `0.85 * 64,000 = 54,400` estimated tokens
- **Estimation**: `len(json.dumps(messages)) // 4` (init.py:40) — very rough

**What happens when threshold hit** (`init.py:738-755`):
1. Calls `_compact_messages()` which sends the entire conversation to `claude-haiku-4-5-20251001` for summarization
2. Replaces ALL messages with a single compacted user message
3. Yields `CompactEvent`

**Potential issues**:
- If `claude-haiku-4-5-20251001` is unavailable (no Anthropic key), compaction fails silently? No — `_compact_messages` at `init.py:600-654` uses `get_adapter(compact_config)` which would fail at adapter construction time if the API key is missing. The exception propagates up to the `Exception` handler at line 1015.
- The compacted summary replaces all conversation history — if the summary is lossy, context is lost.

### 2.4 task_timeout — 300s Default

```
app/config/settings.py:61
```
```python
task_timeout: int = 300
```

**Resolution chain** (`init.py:665-683`):
1. `resolve_runner_settings(agent_name)` from `agent-settings.json` (returns task_timeout)
2. CONFIG.yaml `runner:` block `task_timeout`
3. `settings.task_timeout` (300)

**Master's effective timeout**: 300s. This is the `asyncio.timeout` wrapping `run_stream_with_tools` at `init.py:689`.

**Chain timeout in dispatcher** (`app/backend/dispatcher.py:122`):
```python
_chain_timeout = settings.task_timeout * 2  # 600s
```
This wraps the parent `_execute_task` call which includes master processing + any sub-agent work. But sub-agents spawned by master run in separate processes — this timeout only covers the master's own processing time. Sub-agents have their own 300s timeout.

**Realistic scenario**: Master spawns planning agent. Planning runs for up to 300s. Meanwhile, master's `_chain_timeout` (600s) is counting. If planning takes 250s, master has 350s left — fine. But if master itself also has a long stream (multiple turns), the 300s per-task timeout applies AND the 600s chain timeout applies.

### 2.5 max_tool_calls_per_turn — 20 Per Turn

```
app/config/settings.py:127
```
```python
max_tool_calls_per_turn: int = 20
```

```
app/agents/base/__init__.py:957-963
```
```python
_turn_tool_count = sum(1 for _ in results)
if _turn_tool_count >= settings.max_tool_calls_per_turn:
    messages.append({"role": "user", "content": (
        "[SYSTEM] Tool call limit reached for this turn. "
        "Summarize your progress and continue in the next turn."
    )})
```

**This does NOT break the loop** — it only injects a system message. The next turn continues. This is reasonable but could lead to model confusion if 20 tools is genuinely too many for one turn.

### 2.6 Budget Enforcement

```
app/agents/base/__init__.py:817-838
```

**Two checks**:
1. **Per-agent lifetime**: `settings.budget_per_agent_usd` (`0.0` = unlimited) — checked against `_usage.snapshot()["total_cost_usd"]`
2. **Per-task**: `settings.budget_per_task_usd` (`2.0`) — checked against accumulated `_task_cost_usd`

When exceeded:
1. Appends to `HEALTH.MD`
2. Yields `TextDelta` with budget message
3. Sets `_budget_exceeded = True`
4. Next iteration: `if _budget_exceeded: break` at line 864

**`_task_cost_usd` accumulation**: Tracked from `UsageStats` events (line 812-816). Uses `_calc_turn_cost()` which looks up pricing from `ALL_PRICING`. For `deepseek-chat`: $0.27/MTok in, $1.10/MTok out.

### 2.7 Context Window Size — deepseek-chat = 64K

```
app/utils/adapters/deepseek.py:273-274
```
```python
def context_window_size(self) -> int:
    return ALL_CONTEXT_WINDOWS.get(self._config.model, _DEFAULT_CONTEXT_WINDOW)
```

- `deepseek-chat` → 64,000 tokens (`app/utils/adapters/models/deepseek.py:13`)
- `_DEFAULT_CONTEXT_WINDOW` = 64,000 (`deepseek.py:37`)

### 2.8 Context Injection Caps

From `app/config/settings.py:113-117`:
```
context_notes_chars: int = 4000
context_learnings_chars: int = 2000
context_knowledge_chars: int = 2000
context_memory_lines: int = 20
context_health_lines: int = 10
```

Master CONFIG.yaml overrides (line 45-47):
```
context_memory_limit: 10    # only 10 memory lines
context_health_limit: 5     # only 5 health lines
context_notes_limit: 3000   # 3000 chars instead of 4000
```

These caps limit system prompt size per turn but don't cap the conversation messages (the main token consumer).

### Summary for Problem 2

| Limiter | Value | Location | Impact |
|---|---|---|---|
| max_turns | 999 | `settings.py:60` | Not a practical limit |
| notification_max_turns | NOT IMPLEMENTED | — | Notification tasks get full 999 turns |
| context_compact_threshold | 0.85 × 64K = 54,400 tokens | `init.py:731` | Fires auto-compaction |
| task_timeout | 300s | `settings.py:61` | **Primary limiter** — kills long tasks |
| chain_timeout | 600s | `dispatcher.py:122` | Covers master + sub-agent wait |
| max_tool_calls_per_turn | 20 | `settings.py:127` | Injects warning, doesn't stop |
| budget_per_task_usd | $2.00 | `settings.py:123` | Hard stop when exceeded |
| budget_per_agent_usd | $0.00 (unlimited) | `settings.py:124` | No limit by default |
| context_window | 64,000 | `models/deepseek.py:13` | deepseek-chat limit |
| context injection caps | various | `settings.py:113-117` | Limits system prompt, not messages |

**Root cause for early termination**: The `task_timeout: 300s` is the most likely cause of master stopping early. Deep reasoning tasks that need many tool calls can easily exceed 5 minutes. The `_chain_timeout: 600s` in the dispatcher provides headroom but only covers master's own processing.

---

## 3. Queue Message Problems

### 3.1 The Five Notification Delivery Paths

#### Path A: Redis (runner → master, fast)
```
app/agents/base/runner.py:527-537  (stream_add to agent:{parent}:inbox)
app/backend/main.py:246-295         (_master_redis_watcher reads via stream_read_group)
app/backend/main.py:298-388         (_process_inbox_message handles task_result)
```
- **Trigger**: Runner._notify_parent_via_bus publishes `task_result` to Redis inbox
- **Latency**: ~0ms (real-time, blocking read with 5s timeout)
- **Dedup**: After processing, drains notification_queue (main.py:357)

#### Path B: Notification Queue (runner → master, fallback)
```
app/agents/base/runner.py:554-562  (notification_queue.enqueue)
app/backend/main.py:92-243          (_master_notification_watcher reads via pending_count)
```
- **Trigger**: Runner._notify_parent_via_bus falls back to queue when Redis fails
- **Latency**: ~3s (polled by watcher)
- **Dedup**: After processing, drains notification_queue (main.py:178)

#### Path C: NotifyParentTool (explicit tool, always dual)
```
app/utils/tools/delegation.py:929-936  (notification_queue.enqueue — ALWAYS)
app/utils/tools/delegation.py:941-951  (bus.stream_add to Redis — ALWAYS)
app/utils/tools/delegation.py:958      (_wake_agent_if_idle — writes trigger TASK.MD)
```
- **This always fires BOTH paths** — there is no conditional. Even if Redis succeeds, the queue path also fires. This is the primary source of dual delivery.

#### Path D: NotificationPoller (passive file-based)
```
app/backend/services/notification_poller.py:194-201  (notification_queue.enqueue)
app/backend/services/notification_poller.py:125-128   (_wake_agent_if_idle)
```
- **Trigger**: Polls completed TASK.MD files every `notification_poll_interval_seconds` (5s)
- **Guard**: Skips tasks with `consumed_at` set (line 166-168)
- **Dedup**: In-memory `_notified` set (line 94, 174) — per-process only, lost on restart

#### Path E: Agent Self-Trigger (runner without Redis)
```
app/agents/base/runner.py:670-718
```
- When agent has no Redis connection and `notification_queue.pending_count > 0`, self-writes a trigger TASK.MD
- Looks up real parent via SpawnRegistry

### 3.2 Dual Delivery: NotifyParentTool Sends to BOTH Redis AND Queue

**Source**: `app/utils/tools/delegation.py:885-960`

```python
# Lines 929-936: Always enqueue to notification_queue
notification_queue.enqueue(
    parent_agent=parent_name,
    child_agent=self._agent_dir.name,
    status=status,
    result=result_text if status == "done" else "",
    error=result_text if status == "error" else "",
    session_id=session_id or "",
)

# Lines 941-951: Always try Redis too
try:
    await bus.stream_add(
        f"agent:{parent_name}:inbox",
        {"type": "task_result", ...},
        agent_name=self._agent_dir.name,
    )
except Exception:
    pass  # non-fatal

# Line 958: Also writes trigger TASK.MD
await _wake_agent_if_idle(parent_name, session_id=session_id or "")
```

**Three deliveries for one `notify_parent` call**:
1. notification_queue.enqueue → picked up by `_master_notification_watcher`
2. bus.stream_add → picked up by `_master_redis_watcher`
3. _wake_agent_if_idle → writes TASK.MD trigger → picked up by either runner or notification watcher

**Mitigation that exists**:
- `notification_queue.enqueue` dedup (queue.py:177-195): Matches all fields (parent, child, status, result, error, session_id) against existing unconsumed entries. If NotifyParentTool and NotificationPoller both enqueue for the SAME completion with the SAME payload, the second is deduped.
- Redis watcher drains notification_queue after processing (main.py:357), preventing the notification watcher from also firing.
- Notification watcher drains notification_queue after processing (main.py:178), but this does NOT prevent the Redis watcher from also firing.

**Mitigation that does NOT exist**:
- **The two watchers can race**: If Redis watcher and notification watcher both detect the same completion (one via Redis, one via queue), the Redis watcher processes first and drains the queue (removing the notification watcher's trigger). But if the notification watcher processes first, it drains the queue but the Redis message still exists and will be processed on the next Redis read — causing **duplicate processing**.

### 3.3 NotificationPoller Dedup vs. NotifyParentTool

**Scenario**: Sub-agent completes → AgentRunner._run_task calls set_task_status("done") → Runner._notify_parent_via_bus enqueues to queue AND publishes to Redis

**Simultaneously**: NotificationPoller polls TASK.MD (next 5s cycle), sees status "done", enqueues to notification_queue.

**Dedup check** at `notification_queue.py:177-195`:
```python
for existing in items:
    if (
        existing["parent_agent"] == parent_agent
        and existing["child_agent"] == child_agent
        and existing["status"] == status
        and existing.get("result", "") == result
        and existing.get("error", "") == error
        and existing.get("session_id", "") == (session_id or "")
        and not existing["consumed"]
    ):
        # DEDUPED
        return
```

**This works correctly** when both enqueues have identical payloads. The critical question: do they have identical payloads?

- `Runner._notify_parent_via_bus` (runner.py:554-562): `result=result if status == "done" else ""`, `error=result if status == "error" else ""`
- `NotificationPoller._poll_once` (poller.py:191-192): `result = _read_result_section(task_md) if status == "done" else ""`, `error = _read_error_section(task_md) if status == "error" else ""`

**Potential mismatch**: `_read_result_section` reads from TASK.MD's `## Result` section. `_notify_parent_via_bus` gets `result` from the runner's `result_text` variable which was read from RESULT.MD (runner.py:267-268). If RESULT.MD and TASK.MD `## Result` are not byte-identical (different whitespace, etc.), the dedup will fail and the notification will be enqueued twice.

**Note on `_notify_parent_via_bus` result source** (`runner.py:267-268`):
```python
result_text = await self._agent._read_file("RESULT.MD")
result_text = result_text.strip()
```
This is the RESULT.MD content. Meanwhile `NotificationPoller._read_result_section` reads `## Result` from TASK.MD. The run_stream_with_tools writes to RESULT.MD (init.py:1048) and then set_task_status writes `result` to TASK.MD `## Result` (init.py:375). These should be the same content, but tool call XML stripping in the `finally` block could introduce differences.

### 3.4 consumed_at Marking Reliability

**Where consumed_at is set**:

| Location | Context |
|---|---|
| `init.py:350-357` | `mark_task_consumed()` — sets `consumed_at` in TASK.MD frontmatter |
| `runner.py:293-294` | After successful notification task processing |
| `runner.py:316-317` | After timeout error on notification task |
| `runner.py:338-339` | After exception on notification task |
| `agent_results.py:88` | `collect_agent_results` marks consumed |

**Who checks consumed_at**:

| Location | Context |
|---|---|
| `notification_poller.py:166-168` | Poller skips consumed tasks |
| `agent_results.py:76` | `collect_agent_results` skips consumed tasks |
| `delegation.py:836` | `_wake_agent_if_idle` checks before overwriting |
| `cli/main.py:573` | CLI REPL result collection checks |

**Reliability issue**: `consumed_at` is written to TASK.MD in the agent's directory. The notification_queue's `consumed` flag is separate — set during `drain()`. These are **two independent systems**:

1. TASK.MD `consumed_at` prevents re-reading the result
2. Notification queue `consumed` flag prevents re-processing the notification

If `mark_task_consumed` succeeds but `notification_queue.drain` fails (or vice versa), state is inconsistent across restarts.

### 3.5 Post-Restart Reliability

```
app/backend/main.py:391-509  (_startup_resume)
```

On restart:
1. Pending Redis messages are claimed and **enqueued to notification_queue**, not processed directly (line 467-478)
2. `notification_queue.load()` is called (line 590) which loads `data/notification_queue.json`
3. `_master_redis_watcher` starts (line 604)
4. `_master_notification_watcher` starts (line 605)

**Issue**: If a task was marked `consumed_at` in TASK.MD before shutdown but the corresponding notification_queue entry was NOT drained, the notification survives restart. The watcher will pick it up and re-process a task that was already handled. The `consumed_at` guard in `NotificationPoller` (poller.py:166-168) prevents re-polling, but the notification_queue entry bypasses this — the watchers check `pending_count` on the queue, not `consumed_at` on TASK.MD.

**Notification queue persistence**: `data/notification_queue.json` survives restarts. `_disk_transaction` uses `fcntl.flock` for cross-process safety. Thread-safe via `threading.Lock`. However, `_items` in-memory is not guaranteed consistent with disk on first access — `load()` is called at startup (queue.py:127-145) but only logs state, doesn't set `_items`. The first `_disk_transaction` call reloads from disk properly.

### 3.6 _wake_agent_if_idle — Dual Delivery Summary

```
app/utils/tools/delegation.py:806-882
```

Called from:
1. `NotifyParentTool.execute` (line 958) — always
2. `NotificationPoller._poll_loop` (line 126) — for every completed task found
3. Nowhere else

**What it does**:
1. Checks STATUS.json for "idle" state
2. Publishes "wake" message to Redis (`agent:{name}:inbox`) (line 862-873)
3. Writes trigger TASK.MD (line 875-882)

**This always delivers to both Redis and filesystem** — same dual-delivery pattern.

### Summary for Problem 3

| Issue | Severity | File:Line |
|---|---|---|
| NotifyParentTool always delivers to both Redis + queue | **High** | `delegation.py:929-958` |
| Two watchers can race, causing duplicate processing | **High** | `main.py:92-243` vs `main.py:246-295` |
| Dedup in notification_queue.enqueue works correctly | OK | `queue.py:177-195` |
| RESULT.MD vs TASK.MD ## Result content mismatch can break dedup | **Medium** | `runner.py:267-268` vs `poller.py:56` |
| consumed_at (TASK.MD) vs consumed flag (queue) are independent | **Medium** | `init.py:350` vs `queue.py:228-229` |
| Post-restart: consumed TASK.MD but unconsumed queue entries survive | **Medium** | `main.py:467-478` |
| _wake_agent_if_idle always dual-delivers (Redis + TASK.MD) | **Medium** | `delegation.py:862-882` |
| NotificationPoller dedup set is process-local, lost on restart | **Low** | `poller.py:94` |
| Double `return False` dead code in runner._process_inbox_message | **Cosmetic** | `runner.py:489-490` |

---

## Fix Recommendations

### Problem 1: Master Going Idle

1. **CRITICAL — Don't ACK Redis messages when master is busy**
   `app/backend/main.py:324-331`: Change to skip (return without ACK) instead of ACK+return. The message will stay in the consumer group's pending list and be re-delivered on next claim cycle.
   
   ```python
   # Instead of:
   if state == "running":
       await _bus.stream_ack(inbox, group, msg_id)
       return
   # Do:
   if state == "running":
       return  # skip, don't ACK — message stays pending for re-delivery
   ```

2. **HIGH — Fall back to notification_queue on Redis processing failure**
   `app/backend/main.py:384-388`: In the exception handler, enqueue the failed notification to `notification_queue` before ACKing.

3. **MEDIUM — Make STATUS.json check and _run_lock acquisition atomic**
   `app/backend/main.py:122-130`: The status check in the notification watcher is not atomic with lock acquisition. Consider having the watcher attempt to acquire the lock (with a short timeout) rather than checking STATUS.json.

4. **MEDIUM — Startup resume should NOT compete with already-running watchers**
   `app/backend/main.py:604-613`: Either start watchers after `_startup_resume` completes, or use a signal to coordinate. Currently all three run concurrently.

### Problem 2: Turn Limitations

1. **LOW — Implement `notification_max_turns` or remove from documentation**
   The CLAUDE.md documents it but it doesn't exist in code. Either add it to `settings.py` and use it in `run_stream_with_tools` when the task starts with `[Process incoming`, or remove the documentation.

2. **MEDIUM — Consider increasing `task_timeout` for complex tasks**
   `app/config/settings.py:61`: 300s may be too low for deep reasoning with many tool calls. Consider 600s or making it configurable per task type.

3. **LOW — Context window limitation for deepseek-chat**
   The 64K context window for deepseek-chat is significantly smaller than Claude's 200K. Auto-compaction at 85% (54,400 tokens) may fire frequently for long conversations. Consider monitoring compaction events.

### Problem 3: Queue Messages

1. **HIGH — NotifyParentTool should try Redis first, fall back to queue**
   `app/utils/tools/delegation.py:929-951`: Change from always-deliver-to-both to try Redis first, only enqueue to notification_queue on failure. Match the pattern in `runner._notify_parent_via_bus`.

2. **HIGH — Coordinate the two watchers to prevent dual processing**
   `app/backend/main.py:92-388`: Either:
   - Have the Redis watcher drain the notification queue BEFORE processing (so notification watcher sees empty queue)
   - Or have the notification watcher check if a pending Redis message exists before firing
   - Or merge the two watchers into one that checks both sources

3. **MEDIUM — Normalize result content for dedup matching**
   `runner.py:267-268` and `poller.py:56`: Strip/trim consistently so that the same content from RESULT.MD and TASK.MD `## Result` produce the same string for dedup comparison.

4. **MEDIUM — Cross-reference consumed_at with queue drain on restart**
   `app/backend/main.py:391-509`: On `_startup_resume`, check if TASK.MD has `consumed_at` set for any enqueued notifications and drain them from the queue preemptively.

5. **LOW — Make NotificationPoller dedup set persistent**
   `app/backend/services/notification_poller.py:94`: Store the `_notified` set alongside the notification queue JSON so it survives restarts.
