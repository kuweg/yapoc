# Master Agent Solution Design

Companion to `docs/master-audit.md`. Where the audit traces *what* is broken at file:line precision, this doc proposes *how* to fix it under three constraints set by the project lead:

1. **Surgical fixes only.** Keep the dual-watcher topology, keep both the Redis stream and the notification_queue, keep the current agent file layout. Patch each path so it is correct under concurrency rather than reshaping the pipeline.
2. **No turn caps.** `notification_max_turns` is rejected; tasks run until done.
3. **Master is autonomous.** Master must be able to run indefinitely without being killed by per-task or chain-level timeouts.

Redis remains a hard runtime dependency. The notification_queue is its persistent fallback (engaged only on Redis failure), not a soft-dependency mode.

---

## §1. Context & Problem Statement

The audit identifies three persistent failure modes:

1. **Master goes idle unexpectedly.** Notifications arriving while master is processing another task can be silently dropped. Symptom: a sub-agent finishes successfully and master never reacts to its result.
2. **Tasks die at artificial bounds.** `task_timeout=300s` cancels deep reasoning chains; the dispatcher's `_chain_timeout=600s` cancels at the root even when individual sub-agents are still healthy. Symptom: long autonomous runs end with `TimeoutError` rather than a finished plan.
3. **Duplicate / racing notifications.** `NotifyParentTool` always emits *both* a Redis publish *and* a notification_queue enqueue. The two master watchers (`_master_redis_watcher`, `_master_notification_watcher`) can both pick up the same logical event from different sources. Dedup byte-comparison fails when the same content is read from `RESULT.MD` in one path and from `TASK.MD ## Result` in another. Symptom: the same task gets processed twice, or a duplicate appears in the queue and confuses ordering.

These problems share one root: the notification system has two parallel pipelines (Redis stream + notification_queue) intended as **primary + fallback** but currently behaving as **dual delivery with no coordination**. Each pipeline has its own ACK semantics, and the two watchers consume independently. Under no concurrency, the system works. Under any concurrency — and master is *defined* by handling concurrency — it leaks.

The autonomy problem is orthogonal: per-task and chain-level timeouts are externally-imposed lifetimes that conflict with master running until done.

---

## §2. Design Principles

Four rules that every fix below honors:

1. **Never ACK what you haven't processed.** Replace today's "ACK-on-busy" and "ACK-on-error" patterns with NACK semantics — let Redis redeliver, or hand off to the queue, but never silently consume.
2. **Primary + fallback, not dual.** `NotifyParentTool` mirrors `_notify_parent_via_bus`: try Redis first; only enqueue to `notification_queue` if Redis fails. Eliminates the unconditional double-delivery that today causes races.
3. **Canonical payload source.** All producers read result/error text from `RESULT.MD` through one shared accessor. Dedup byte-comparison only works if every path produces the same bytes for the same logical content.
4. **Master is unbounded.** Master gets no per-task timeout and no turn cap. The dispatcher's chain timeout is bypassed for master tasks. Sub-agents keep their normal bounds, and cost protection moves entirely to budget enforcement (`budget_per_task_usd`, `budget_per_agent_usd`).

---

## §3. Concrete Fixes

Ordered by severity. Each fix names the file:line, restates the bug from the audit, proposes a specific change, explains why it is correct, and gives a verification step.

### Problem 1 — Master Goes Idle Unexpectedly

#### Fix 1.1 (CRITICAL) — Don't ACK Redis messages when master is busy

**Where:** `app/backend/main.py:324-331`

**Bug:** `_process_inbox_message` ACKs the Redis message before checking master state. When `STATUS.json` reports `running`, the code calls `_bus.stream_ack(...)` then returns. The notification is removed from Redis with no fallback — permanently lost.

```python
# Current (buggy):
if state == "running":
    await _bus.stream_ack(inbox, group, msg_id)
    return
```

**Change:**

```python
# Proposed:
if state == "running":
    # Don't ACK — let Redis hold the message in the consumer-group pending list.
    # Also enqueue to notification_queue as a belt-and-suspenders safety net so
    # the notification watcher can pick it up the moment master idles. Queue
    # dedup (notification_queue.enqueue) makes the double-write safe if Redis
    # later redelivers the same message.
    try:
        notification_queue.enqueue(
            parent_agent="master",
            child_agent=payload.get("child_agent", ""),
            status=payload.get("status", "done"),
            result=payload.get("result", ""),
            error=payload.get("error", ""),
            session_id=payload.get("session_id", ""),
        )
    except Exception as e:
        logger.warning("Redis watcher: queue safety-enqueue failed: {}", e)
        # Still don't ACK — message stays pending in Redis for redelivery.
    return
```

**Why correct:** Unacknowledged stream messages remain in the consumer group's pending list and are re-delivered on the next `stream_read_group` / `stream_claim_pending` cycle. The queue safety-enqueue ensures the notification watcher also has a path to the message. The queue's 6-field dedup (`notification_queue.py:177-195`) prevents double-processing if both paths fire.

**Verification (V1):**
1. Start a long master task (something that occupies the runner for ≥30s).
2. While master is mid-task, send a `task_result` payload to `agent:master:inbox`.
3. Expected: master finishes its current task, transitions to idle, then processes the deferred notification exactly once.
4. Failure signal: master goes idle and never processes the notification; or processes it twice.

---

#### Fix 1.2 (HIGH) — Re-enqueue on processing failure

**Where:** `app/backend/main.py:384-388`

**Bug:** The exception handler around `handle_task_stream` ACKs the Redis message unconditionally after a failed processing attempt. Failure → ACK → notification lost.

```python
# Current (buggy):
except Exception as _proc_exc:
    logger.warning("Redis master watcher: processing failed: {}", _proc_exc)

# ACK after successful processing (or best-effort on error)
await _bus.stream_ack(inbox, group, msg_id)
```

**Change:**

```python
# Proposed:
except Exception as _proc_exc:
    logger.warning("Redis master watcher: processing failed: {}", _proc_exc)
    # Attempt safety enqueue so the notification watcher can retry.
    try:
        notification_queue.enqueue(
            parent_agent="master",
            child_agent=payload.get("child_agent", ""),
            status=payload.get("status", "done"),
            result=payload.get("result", ""),
            error=payload.get("error", ""),
            session_id=payload.get("session_id", ""),
        )
        await _bus.stream_ack(inbox, group, msg_id)  # safe to ACK — queue has it
    except Exception as _enq_exc:
        logger.error(
            "Redis master watcher: BOTH process AND queue enqueue failed: "
            "{} / {}. Leaving message pending for Redis redelivery.",
            _proc_exc, _enq_exc,
        )
        # Don't ACK. Redis will redeliver.
    return

# ACK after successful processing only.
await _bus.stream_ack(inbox, group, msg_id)
```

**Why correct:** Preserves at-least-once semantics in every failure mode. If processing fails but the queue accepts the payload, the notification watcher retries. If both fail, Redis redelivers.

**Verification (V2):**
1. Patch `handle_task_stream` to raise on a specific marker payload.
2. Send a Redis notification carrying that marker.
3. Expected: notification appears in `data/notification_queue.json`, gets picked up by the notification watcher, processes successfully on retry.
4. Failure signal: notification disappears with no trace; or appears twice.

---

#### Fix 1.3 (MEDIUM) — Replace STATUS.json polling with lock state

**Where:** `app/backend/main.py:122-130` (notification watcher), `:324-331` (Redis watcher); plus `app/agents/master/agent.py:17`

**Bug:** Both watchers read `STATUS.json` from disk to decide whether master is busy. This is non-atomic with `_run_lock` acquisition — a notification can land in the gap between status read and lock acquisition. STATUS.json read failures are silently swallowed (`except Exception: pass`).

**Change:**

In `app/agents/master/agent.py`, add a small accessor:

```python
def is_busy(self) -> bool:
    """True if master is currently inside a handle_task / handle_task_stream call."""
    return self._run_lock.locked()
```

In both watchers, replace the STATUS.json read pattern:

```python
# Was:
try:
    state = json.loads(status_path.read_text()).get("state", "")
    if state == "running":
        ...
except Exception:
    pass

# Becomes:
if master_agent.is_busy():
    ...
```

`STATUS.json` continues to be written for UI/observability; it is just no longer load-bearing for routing decisions.

**Why correct:** `_run_lock.locked()` is the actual concurrency primitive. Reading from a file is a stale, slow, failure-prone denormalization of the same fact.

**Verification (V10):**
1. Instrument the watcher to log every `is_busy()` check.
2. Send rapid notifications around a master task boundary.
3. Expected: no notification is processed concurrently with another (lock serializes); no notification is dropped by an `is_busy()` false-negative.

---

#### Fix 1.4 (MEDIUM) — Await `_startup_resume` before scheduling watchers

**Where:** `app/backend/main.py:603-613` (lifespan startup); `_startup_resume` at `:391-509`

**Bug:** `_startup_resume`, `_master_redis_watcher`, and `_master_notification_watcher` all start concurrently via `loop.call_later(5, ...)`. They compete for the same pending Redis messages. The `stream_claim_pending` 10-message cap means resume only catches a slice before the watchers race in.

**Change:** In the FastAPI `lifespan`, await `_startup_resume()` to completion *before* scheduling either watcher:

```python
# Was (concurrent):
loop.call_later(5, lambda: asyncio.ensure_future(_startup_resume()))
asyncio.ensure_future(_master_redis_watcher())
asyncio.ensure_future(_master_notification_watcher())

# Becomes (sequential):
await _startup_resume()  # one-shot recovery; latency cost ~seconds
if bus.connected:
    asyncio.ensure_future(_master_redis_watcher())
asyncio.ensure_future(_master_notification_watcher())
```

**Why correct:** `_startup_resume` is a one-shot recovery step. Running it to completion first ensures the queue contains every pre-existing pending notification before any live watcher starts consuming. Latency cost is bounded (a few seconds at most for the Redis claim cycle).

**Verification (V3):**
1. Start master, kick off a sub-agent that completes mid-master-processing.
2. Kill master before it ACKs the notification.
3. Restart master.
4. Expected: the in-flight notification is processed exactly once after restart.
5. Failure signal: it's processed twice (race) or zero times (drop).

---

### Problem 2 — Lifting Bounds for Autonomous Master

#### Fix 2.1 (HIGH) — Remove per-task timeout for master

**Where:** `app/agents/master/CONFIG.yaml:41-47` (runner block); `app/agents/base/__init__.py:665-689` (timeout-resolution chain and `asyncio.timeout(...)` wrap)

**Bug:** Master inherits `task_timeout=300s` from `settings.py`. Deep autonomous reasoning chains routinely exceed 5 minutes — especially when waiting on serial sub-agent results. The `asyncio.timeout(...)` wrap cancels master mid-thought.

**Change:**

*Config side* — in `app/agents/master/CONFIG.yaml`, add to the runner block:

```yaml
runner:
  task_timeout: 0   # unbounded — master runs until done
  poll_interval: 30
  retry_attempts: 3
  context_memory_limit: 10
  context_health_limit: 5
  context_notes_limit: 3000
```

*Code side* — in `run_stream_with_tools` (`app/agents/base/__init__.py:665-689`), treat `0` (or any non-positive value) as "no timeout":

```python
# Was:
task_timeout = _runner.get("task_timeout", settings.task_timeout)
async with asyncio.timeout(task_timeout):
    ...

# Becomes:
task_timeout = _runner.get("task_timeout", settings.task_timeout)
timeout_ctx = asyncio.timeout(task_timeout) if task_timeout and task_timeout > 0 else asyncio.timeout(None)
async with timeout_ctx:
    ...
```

`asyncio.timeout(None)` is a documented no-op — the wrap stays in place but never fires.

**Why correct:** Master is the orchestrator; bounding it externally fights its purpose. Sub-agents keep `task_timeout=300` (or whatever they're configured for), so a runaway leaf still terminates. Master's only remaining guardrail is budget enforcement, which is the intended cost cap.

**Verification (V7):**
1. Run a master task that spawns three sub-agents serially and reasons between each.
2. Configure the task so it takes 20+ minutes total.
3. Expected: master completes without `TimeoutError`.
4. Failure signal: master is cancelled before any sub-agent finishes.

---

#### Fix 2.2 (HIGH) — Bypass dispatcher `_chain_timeout` for master

**Where:** `app/backend/dispatcher.py:122` (`_chain_timeout = settings.task_timeout * 2`)

**Bug:** Even with `task_timeout=0` for master, the dispatcher wraps `_execute_task` in `asyncio.timeout(_chain_timeout)` (600s when master inherits the default; would be `0 * 2 = 0` post-Fix-2.1, which `asyncio.timeout(0)` treats as immediate timeout — worse, not better). So the chain timeout still kills master at the parent level.

**Change:** In `_execute_task` (or wherever the chain timeout is applied), skip the wrap when the target agent is master:

```python
# Was:
_chain_timeout = settings.task_timeout * 2
async with asyncio.timeout(_chain_timeout):
    ...

# Becomes:
if agent_name == "master":
    # Master is unbounded — see claude-solution-design.md Fix 2.2.
    chain_ctx = asyncio.timeout(None)
else:
    _chain_timeout = settings.task_timeout * 2 if settings.task_timeout > 0 else None
    chain_ctx = asyncio.timeout(_chain_timeout)
async with chain_ctx:
    ...
```

**Why correct:** The chain timeout exists to protect against runaway sub-agent trees, but master is supposed to *be* the long-running root. Sub-agent chains spawned *by* master remain individually bounded by each agent's own `task_timeout`.

**Verification:** Same as V7 — master task ≥20 minutes; confirm the dispatcher does not cancel.

---

#### Fix 2.3 (LOW) — Remove the `notification_max_turns` reference from docs

**Where:** `app/agents/base/CLAUDE.md:35`

**Bug:** Documents a setting that does not exist in `settings.py` and is no longer planned. Grep confirms zero `.py` references.

**Change:** Strike the line; replace with explicit "notification-processing tasks share the same turn budget as regular tasks; budget enforcement is the bound, not turn count."

**Why correct:** Documentation must match implementation. The user has explicitly rejected the bound.

No verification needed (doc-only).

---

#### Note on the deepseek-chat 64K context window

`deepseek-chat`'s 64K window triggers auto-compaction at `0.85 × 64,000 = 54,400` estimated tokens (`init.py:730-732`). On long autonomous runs master will visibly summarize and continue. This is an *observable behavior*, not a bug; model selection is out of scope per the design constraints. Documenting here only to set expectations.

---

### Problem 3 — Queue / Duplicate Messages

#### Fix 3.1 (HIGH) — `NotifyParentTool`: Redis-first, queue-on-failure

**Where:** `app/utils/tools/delegation.py:929-956`

**Bug:** `NotifyParentTool.execute` unconditionally fires *both* `notification_queue.enqueue` *and* `bus.stream_add` for every notify call. This is the primary source of dual delivery and watcher races.

**Change:** Mirror the pattern already used by `runner._notify_parent_via_bus` (`runner.py:513-570`) — Redis first, queue only on Redis failure:

```python
# Was (dual delivery — both always fire):
notification_queue.enqueue(...)
try:
    await bus.stream_add(f"agent:{parent_name}:inbox", {...})
except Exception:
    pass  # non-fatal
await _wake_agent_if_idle(parent_name, session_id=session_id or "")

# Becomes (Redis-first, queue as fallback):
redis_ok = False
try:
    await bus.stream_add(
        f"agent:{parent_name}:inbox",
        {
            "type": "task_result",
            "child_agent": self._agent_dir.name,
            "parent_agent": parent_name,
            "status": status,
            "result": result_text if status == "done" else "",
            "error": result_text if status == "error" else "",
            "session_id": session_id or "",
        },
        agent_name=self._agent_dir.name,
    )
    redis_ok = True
except Exception as e:
    logger.warning("NotifyParentTool: Redis publish failed, falling back to queue: {}", e)

if not redis_ok:
    notification_queue.enqueue(
        parent_agent=parent_name,
        child_agent=self._agent_dir.name,
        status=status,
        result=result_text if status == "done" else "",
        error=result_text if status == "error" else "",
        session_id=session_id or "",
    )

# Wake signal always fires — it doesn't carry payload, only triggers a TASK.MD probe.
await _wake_agent_if_idle(parent_name, session_id=session_id or "")
```

**Why correct:** Eliminates unconditional double-delivery. The queue still gets the notification when Redis is unavailable, preserving fallback semantics. `_wake_agent_if_idle` continues to fire either way because it carries no payload — it only writes a trigger TASK.MD if the parent is currently idle.

**Verification (V4, V5):**
- V4 (Redis up): Trigger `notify_parent` from a sub-agent. Confirm `data/notification_queue.json` does *not* gain an entry. Confirm master receives the notification via the Redis path.
- V5 (Redis down): Stop Redis. Trigger `notify_parent`. Confirm the queue *does* gain an entry. Confirm master receives it via the notification watcher.

---

#### Fix 3.2 (MEDIUM) — Canonical result source for dedup

**Where:** `app/agents/base/runner.py:267-268` (reads `RESULT.MD`); `app/backend/services/notification_poller.py:56` (`_read_result_section` reads `## Result` from `TASK.MD`)

**Bug:** Two notification producers read the same logical result from two different files. `RESULT.MD` and `TASK.MD ## Result` should hold byte-identical content, but tool-call XML stripping, whitespace normalization, and frontmatter handling differ between the writer paths. When dedup in `notification_queue.enqueue` (`queue.py:177-195`) compares the two byte-by-byte, it fails to recognize them as duplicates, and both enter the queue.

**Change:** Add a single canonical reader on `BaseAgent`:

```python
# app/agents/base/__init__.py
async def read_result_text(self) -> str:
    """Canonical result-text source for notification payloads.

    All producers (NotifyParentTool, runner._notify_parent_via_bus,
    NotificationPoller) must use this method so dedup byte-comparison works.
    """
    text = await self._read_file("RESULT.MD")
    return text.strip()
```

Update `NotificationPoller._poll_once` (`notification_poller.py:191-201`) to call `await agent.read_result_text()` instead of `_read_result_section(task_md)`. Update any other producer that reads result text to use the same accessor.

`_read_result_section` remains as a legacy helper used only by UI / result-collection paths that genuinely want the `## Result` section from `TASK.MD` (e.g., human-readable history rendering). It is no longer used for notification payloads.

**Why correct:** Single source of truth. `RESULT.MD` is already authoritative — `run_stream_with_tools` writes it at `init.py:1048`, and the `## Result` field in `TASK.MD` is a denormalization written afterward by `set_task_status`. Reading from one file in all producers guarantees byte-identical payloads.

**Verification (V9):**
1. Trigger a sub-agent completion.
2. Within the same 5s `NotificationPoller` cycle, force `NotifyParentTool` to also fire (via Redis failure path).
3. Expected: `data/notification_queue.json` contains exactly one entry for that completion.
4. Failure signal: two entries with byte-different `result` fields.

---

#### Fix 3.3 (MEDIUM) — `consumed_at` ↔ queue consistency on restart

**Where:** `app/backend/main.py:391-509` (`_startup_resume`)

**Bug:** TASK.MD `consumed_at` (set by `mark_task_consumed`) and `notification_queue` `consumed` flag (set by `drain`) are independent. A master crash between "mark TASK.MD consumed" and "drain queue" leaves the queue entry alive across restart, and the notification gets re-processed even though the underlying task was already handled.

**Change:** In `_startup_resume`, after `notification_queue.load()` (`main.py:590`) and *before* scheduling live watchers, reconcile the two:

```python
# Pseudocode addition to _startup_resume:
async def _reconcile_queue_with_consumed_at():
    pending = notification_queue.pending_entries("master")
    for entry in pending:
        child_name = entry["child_agent"]
        task_md_path = settings.agents_dir / child_name / "TASK.MD"
        if not task_md_path.exists():
            continue
        content = task_md_path.read_text(encoding="utf-8")
        fm = parse_frontmatter(content)
        if fm.get("consumed_at"):
            notification_queue.mark_consumed(entry["id"])  # or equivalent
            logger.info(
                "Startup reconcile: marked queue entry consumed (TASK.MD already consumed): "
                "child={} session={}", child_name, entry.get("session_id", ""),
            )

await _reconcile_queue_with_consumed_at()
```

Symmetrically, in the Redis-claim section (`main.py:467-478`), check `consumed_at` *before* enqueueing a claimed Redis message — if the source TASK.MD is already consumed, ACK the Redis message and skip enqueue.

**Why correct:** Makes the two ACK systems explicitly consistent at the only point that matters (startup boundary). At runtime they drift briefly but converge on the next restart.

**Verification (V3 — extended):**
1. Mark a sub-agent's TASK.MD consumed (simulating successful notification processing).
2. Crash master before the queue drain commits.
3. Restart master.
4. Expected: queue entry is reconciled to `consumed=true` during startup; notification is *not* re-processed.

---

#### Fix 3.4 (LOW) — Transitional Redis-watcher defer

**Where:** `app/backend/main.py:298-388` (`_process_inbox_message`)

**Bug:** During the rollout window (Phase 1 deployed but not all producers updated), `NotifyParentTool` may still emit both paths. If a matching unconsumed queue entry exists, both watchers might fire on the same logical event.

**Change:** Before processing a Redis message, check whether the notification_queue already has a matching unconsumed entry. If so, defer (return without ACK) and let the notification watcher process — Redis will redeliver if the queue path also fails.

```python
async def _process_inbox_message(...):
    if master_agent.is_busy():
        # ... Fix 1.1 ...
        return

    # Transitional dedup: check queue for an existing matching entry.
    if notification_queue.has_matching_unconsumed("master", payload):
        logger.debug("Redis watcher: deferring to notification watcher (queue match)")
        return  # don't ACK — wait for queue or Redis redelivery

    # Proceed with processing as before.
    ...
```

**Why correct:** Belt-and-suspenders during rollout. Once Fix 3.1 is fully deployed, this branch should rarely fire (only on the genuine Redis-failure fallback path).

**Verification:** With Fix 3.1 *deferred* in a test build, trigger `notify_parent`. Confirm exactly one processing event (not two).

---

#### Fix 3.5 (LOW) — Persist `NotificationPoller._notified` set

**Where:** `app/backend/services/notification_poller.py:94`

**Bug:** Process-local dedup set `self._notified` is lost on restart. Combined with Fix 3.3 this is redundant defense; cheap to add.

**Change:** Persist alongside the queue as `data/poller_notified.json` (one entry per `(agent_name, dedup_marker)` tuple). Load at `NotificationPoller.__init__`; save on every mutation (use the same fcntl pattern as `notification_queue`).

**Why correct:** Closes the last restart-dedup hole. With both Fix 3.3 and Fix 3.5 in place, no notification can be replayed by any path after a crash.

**Verification:** Restart master immediately after Poller observes a completed task; confirm Poller does not re-notify for the same task.

---

## §4. Sequencing

Two phases. Each is independently shippable and leaves the system in a working state.

### Phase 1 — Stop the bleeding (ship together)

| Fix | What it stops |
|---|---|
| **1.1** Don't ACK on busy | Notifications silently dropped when master is mid-task |
| **1.2** Re-enqueue on error | Notifications lost when `handle_task_stream` raises |
| **3.1** NotifyParentTool: Redis-first | Unconditional dual delivery |

These three remove every confirmed active failure mode for notification loss and duplication. They require no API changes, no schema changes, no removal of code paths.

### Phase 2 — Autonomy & polish

| Fix | What it enables |
|---|---|
| **2.1** Master `task_timeout: 0` | Master runs until done |
| **2.2** Dispatcher bypass for master | Chain timeout doesn't override Fix 2.1 |
| **1.3** Lock-state replaces STATUS.json | Atomic busy check, fewer file IO failures |
| **1.4** Await `_startup_resume` first | Eliminates 3-way startup race |
| **3.2** Canonical result source | Dedup byte-comparison works |
| **3.3** Restart consistency | `consumed_at` ↔ queue reconciled on startup |
| **3.4** Transitional defer | Safety during rollout |
| **3.5** Persist Poller dedup | Restart-safe Poller |
| **2.3** Doc strike | Remove dead `notification_max_turns` reference |

Phase 2 fixes are individually safe to ship in any order, but bundling them keeps the system's mental model consistent ("after Phase 2, master is autonomous and notifications converge").

---

## §5. Verification Plan

| # | Scenario | Setup | Expected | Fix(es) |
|---|---|---|---|---|
| V1 | Notification mid-task | Long master task; send `task_result` while busy | Processed exactly once after master idles | 1.1 |
| V2 | `handle_task_stream` raises | Inject exception in handler | Notification appears in queue, processed on retry | 1.2 |
| V3 | Crash + restart with in-flight | Mark TASK.MD consumed; kill master pre-drain; restart | Notification is *not* re-processed | 1.4, 3.3 |
| V4 | Notify with Redis up | Sub-agent calls `notify_parent` | No new queue entry; master receives via Redis | 3.1 |
| V5 | Notify with Redis down | Stop Redis; sub-agent calls `notify_parent` | Queue gains entry; master receives via watcher | 3.1 |
| V6 | 10 concurrent completions | 10 sub-agents finish near-simultaneously | Exactly 10 master processings; no duplicates | 1.1, 3.1, 3.2 |
| V7 | 20-minute master task | Master spawns 3 serial sub-agents | Completes without `TimeoutError` | 2.1, 2.2 |
| V8 | Sub-agent runaway (negative) | One sub-agent loops indefinitely | Sub-agent hits its own `task_timeout`; master continues | 2.1 (negative) |
| V9 | Poller + NotifyParent same cycle | Force both to fire on one completion | Exactly one queue entry | 3.2 |
| V10 | Lock contention at boundary | Rapid notifications around task start/end | No drops, no concurrent processing | 1.3 |

Each scenario should be runnable manually against a dev instance; automated test infrastructure is out of scope per project rule.

---

## §6. Open Questions

These are deliberately *not* answered in the design — they require product/architecture judgment beyond the surgical scope:

1. **What guards master against runaway cost after Fix 2.1/2.2?** Recommendation: rely on `budget_per_agent_usd` (currently `0.0` = unlimited). Setting a non-zero default (e.g., `$20`) would put a real cap in place. Worth a separate decision.
2. **Should `is_busy()` expose more state?** The minimal version is `bool`. A richer accessor could return current task ID / start time for UI diagnostics. Not load-bearing for these fixes.
3. **Is `NotificationPoller` still needed after Phase 1?** Its only remaining role is recovery for sub-agents that crashed without ever calling `notify_parent`. `_startup_resume` may already cover that. Worth measuring whether the poller fires meaningfully post-Phase-1.
4. **deepseek-chat's 64K context window** triggers frequent auto-compaction on long autonomous runs. Model selection is out of scope, but if compaction is observed to be lossy, a larger-window model would be the obvious next lever.

---

## §7. Out of Scope

- Architectural restructure of the notification pipeline (per user constraint).
- Turn caps of any kind, including `notification_max_turns` (per user constraint).
- Master LLM model selection (per user constraint).
- Making Redis a soft dependency (per user constraint — Redis stays hard).
- Test infrastructure (per project rule).
- UI/CLI surface changes.
- Token/cost telemetry changes.

---

## §8. Summary

The audit traced three problems to one root: dual notification pipelines without coordination. Under the constraint of surgical fixes only, the design preserves the pipeline topology and instead makes each path correct under concurrency. The critical paths — Redis watcher and `NotifyParentTool` — are converted from "ACK first, ask questions later" to "process first, ACK only after." `RESULT.MD` becomes the canonical payload source so dedup actually works. Master is freed from per-task and chain-level timeouts, so it can be the autonomous orchestrator it was designed to be.

Phase 1 (three fixes) stops every confirmed active failure. Phase 2 cleans up the remaining races and unlocks unbounded master runs. No architectural changes, no new dependencies, no schema migrations.
