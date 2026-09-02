# YAPOC test findings — 2026-05-17 session

## ✅ Bug 1 (FIXED) — `execute_dag` returned 0.0s no-op when re-using the same agent across batches

**Symptom (pre-fix).** In a 4-node DAG with two `builder` nodes in different batches, the downstream node reported `status: done` with `duration_s: 0.0` and returned the **same result** as the upstream node — silent stale read.

**Root cause.** `SpawnAgentTool.execute` soft-rejects with the message `"Agent 'X' is currently processing a task (PID Y, state: running). Use wait_for_agent..."` when the target agent's `STATUS.json` still shows `state: running` from the prior batch. The rejection string does **not** start with `"Error"`, so `ExecuteDagTool` treated it as a successful spawn and immediately polled the agent's `TASK.MD` — which still contained the prior task's `status: done` + `## Result` — and silently returned that as the "new" node's result.

**Fix.** Two surgical additions to `app/utils/tools/delegation.py`:
1. `_wait_agent_not_running(agent, timeout_s=60)` — polls the target agent's `STATUS.json` until `state != "running"` (or timeout). Called before each spawn inside `ExecuteDagTool`.
2. `_spawn_response_indicates_failure(msg)` — broadens the failure-detection beyond `startswith("Error")` to recognize:
   - `"is currently processing"` (the mid-task soft-reject)
   - `"refusing to spawn"` (concurrency-cap reject)
   - `"not authorized to delegate"` (delegation auth)
   - `"no agent directory"` (target missing)

   `ExecuteDagTool` now uses this helper instead of the narrow `startswith` check.

**Verified.** Two same-agent DAG nodes (both `builder`) now both execute with realistic durations (4.98s + 3.01s) and `0 errors`. Pre-fix the second would have been `0.0s` with the first's result.

---

## ✅ Bug 2 (FIXED) — Agent sidebar showed `error` / stale state when agents were actually idle

**Symptom (pre-fix).** Sidebar showed `master`, `builder`, `planning` permanently in red "error" state even though their `STATUS.json` files cleanly read `idle` / `terminated`. Caused users to think the system was broken when it wasn't.

**Root cause.** `_build_agent_status` in `app/backend/services/__init__.py:265-266`:
```python
elif health_errors > 0:
    legacy_status = "error"
```
`health_errors` is the count of `ERROR`/`CRITICAL` entries in the **last 10 lines of HEALTH.MD**. For agents that rarely log, a single old entry from a past server restart (e.g., `shutdown: signal`) stays in the "last 10" indefinitely and the badge stays red forever.

**Fix.** Replaced the `health_errors > 0` branch with a check on the **current** task status:
```python
elif task and (task.status or "").lower() == "error":
    legacy_status = "error"
```
The "error" badge now only fires when the most recent task itself ended in error. Historical health entries are still surfaced separately (Observability tab + `/health` endpoint).

**Verified.** `curl /agents` now returns all 10 agents as `status=idle`. UI sidebar shows all green dots, no false "error" badges.

---

## ✅ Bug 3 (FIXED) — Runner subprocess gets stuck at `STATUS.json state: running` after a compaction failure

**Symptom.** Builder's `STATUS.json` showed `state: running` indefinitely (5+ minutes observed) after a task already completed. `TASK.MD` was correctly at `status: done`, but `STATUS.json` was never written back to `idle`. Subsequent same-agent spawns hit the soft-reject path until a manual restart.

**Likely cause.** Builder's `HEALTH.MD` contains:
```
httpx.HTTPStatusError: DeepSeek API error (400): The supported API model names
are deepseek-v4-pro or deepseek-v4-flash, but you passed claude-haiku-4-5-20251001.
```
This is raised in `app/agents/base/__init__.py:640` inside `_compact_messages`, called by `run_stream_with_tools` when context exceeds the compaction threshold. The exception propagates up from compaction. The runner's `_run_task` outer try/except catches generic `Exception`, but the cleanup path between `_run_task` returning and the main loop's `self._write_status("idle")` call (`runner.py:728-729`) seems to not execute in this case — STATUS.json never gets the idle write.

**Repro.** Spawn builder for a task that triggers context compaction, with `agent-settings.json` fallback chain that includes a Claude model name (`claude-haiku-4-5-20251001`) but routes through the DeepSeek adapter. The compaction call uses `settings.context_compact_model` directly against the configured adapter, ignoring the adapter's model registry.

**Fix candidates.**
- **A.** In `BaseAgent._compact_messages`, only use `context_compact_model` if it's compatible with the current adapter; otherwise fall back to the agent's own model.
- **B.** In `runner.py` main loop, write `state=idle` in a `finally` block after `_run_task` returns, so even an uncaught exception from compaction doesn't leave STATUS.json stuck at `running`.
- **C.** Wrap `_compact_messages` in a try/except that logs the error to HEALTH.MD but doesn't propagate, so the task completes (already half-implemented — the error WAS logged to HEALTH.MD; just the runner side needs hardening).

**File pointers:** `app/agents/base/__init__.py:_compact_messages`, `app/agents/base/runner.py:run()` main loop around line 728.

**Severity.** Medium — masks Bug 1 fix in the field (same-agent DAG nodes time out if the agent gets stuck). Bug 1 fix now correctly flags it as a `spawn failed` instead of silent corruption.

---

## ✅ Bug 4 (FIXED) — DAG upstream-context injection ignored by downstream agent

**Symptom.** In the test DAG, the downstream `second` node was told *"your final message must be `BETA_2_SAW_ALPHA_2`, where ALPHA_2 should be replaced with whatever the first node's result was"*. The first node correctly returned `ALPHA_2`. The second node received `ALPHA_2` in its `## Context` section (via `ExecuteDagTool`'s upstream-result injection) — but its final message was `...ALPHA_2`, not `BETA_2_SAW_ALPHA_2`. The agent apparently confused its own task instruction with the injected context.

**Likely cause.** The upstream-context block in the spawned `TASK.MD` looks like:
```
## Context
[from upstream node 'first' (agent=builder)]
The task is clear — my final message must be exactly the single line: `ALPHA_2`...ALPHA_2
```
This text includes the upstream agent's *thinking* ("The task is clear — my final message must be exactly..."), which the downstream agent may re-interpret as its own current instruction.

**Fix candidates.**
- Strip the upstream agent's reasoning text from the injected context; include only the bare result lines.
- Frame upstream results with a clearer separator like `[UPSTREAM RESULT — for reference only, NOT your task]`.
- Or: have `ExecuteDagTool` insert upstream results into the *task* prompt as data, not into the context section that the agent might mistake for instructions.

**File:** `app/utils/tools/delegation.py` — `ExecuteDagTool.execute` context-building loop.

**Severity.** Low — agents can be prompted around it. But for reliable handoff in DAGs, worth a polish.

---

## Triage summary

| # | Status | Severity | Effort | Notes |
|---|---|---|---|---|
| 1 | ✅ FIXED | Medium | S — done | execute_dag soft-reject detection + pre-wait |
| 2 | ✅ FIXED | Low (UX) | S — done | Stop deriving sidebar state from historical health log |
| 3 | ✅ FIXED | Medium | S — done | Runner forces an idle write when `_check_task` raises; compact model is adapter-aware |
| 4 | ✅ FIXED | Low | S — done | Upstream results injected as labelled REFERENCE DATA with reasoning stripped |
| 5 | ✅ FIXED | **High** | S — done | Compaction split tool_use/tool_result pairs → provider 400 killed the task |
| 6 | ✅ FIXED | Medium | S — done | Late results leaked into whichever chat session was open |
| 7 | ✅ FIXED | Low | S — done | Agent card rendered a `<button>` inside a `<button>` |

Bugs 3 and 4 were discovered during the verification of Bug 1's fix. Bugs 5-7 were
found on 2026-08-31 while verifying that 3 and 4 were closed out.

---

## ✅ Bug 5 (FIXED) — Compaction orphaned `tool_result` blocks and killed the task

**Symptom.** Long runs died shortly after an auto-compact. The visible error came
from the provider, not from YAPOC, so it read as a flaky API rather than a bug here.

**Root cause.** `BaseAgent._compact_messages` preserved the tail with a blind
`messages[-tail_n:]` slice. Conversations alternate `assistant` (holding `tool_use`
blocks) and `user` (holding the matching `tool_result` blocks), so whenever the
distance from a pair to the end of the list was odd — the common case, since a run
usually ends with a plain assistant answer — the slice began *on* a `tool_result`
whose `tool_use` was in the discarded middle. The next request then carried a
`tool_result` with no matching `tool_use`: a hard 400 from Anthropic, and the same
via `normalize.py` for the OpenAI-compatible adapters.

Note this is a *different* cause from Bug 3, which blamed the compact model name.
That fix was correct but incomplete — compaction stayed fragile for a second reason.

**Fix.** `_safe_tail_start()` walks the tail boundary backwards while it would land
on a `tool_result` message, pulling the owning assistant message into the tail.
Used by `_compact_messages` and by the new `_deterministic_trim` fallback.

**Also hardened.** The `_compact_messages` call site is now wrapped: if compaction
raises for any reason (e.g. the compact adapter cannot be constructed), the run
degrades to `_deterministic_trim` — anchor + marker + tool-pair-safe tail — instead
of aborting a task that was otherwise healthy. The failure is logged to HEALTH.MD.

**Verified.** Repro across uniform pairs, an assistant text turn mid-conversation,
an injected `[SYSTEM]` nudge, and a trailing assistant answer. Only the last
orphaned before the fix (`tu_5`); all four are clean after, and the below-threshold
and no-user-message cases are passed through untouched.

**Files:** `app/agents/base/__init__.py` — `_has_tool_result`, `_safe_tail_start`,
`_deterministic_trim`, `_compact_messages`, and the auto-compact call site.

---

## ✅ Bug 6 (FIXED) — Late results leaked into whichever session was open

**Symptom.** Start a delegation, hit **+ NEW** before it finishes, and the previous
session's assistant messages appear in the brand-new empty chat — with no user
message above them.

**Root cause.** `useSessionStore.appendMessage` always wrote to `activeId` *at call
time*. Any message that arrives after the user switches chats — a stream finishing,
a delegation completing, an orphan notification — was therefore persisted into the
wrong session. `ChatPanel` already guarded the `lastCompletedTask` and
`lastSessionEvent` paths by session id, but the guards could not help: the write
itself had no notion of which session the message belonged to.

**Fix.** `appendMessage` takes an optional `sessionId`; when it names a different
session, the message is appended to that session's stored history and the visible
`history` is left alone. `TaskGroup` carries the `sessionId` it was started in, and
the stream-completion, stream-error, and task-group persist paths all pass it.

**Verified.** Switch away 4s into a delegation: the new session stays empty through
completion, and the result lands in the originating session (store shows the new
session with 0 messages, the origin with `roles: "ua"`). The result is routed, not
dropped.

**Files:** `app/frontend/src/store/session.ts`,
`app/frontend/src/components/ChatPanel.tsx`,
`app/frontend/src/components/TaskGroupBubble.tsx`.

---

## ✅ Bug 7 (FIXED) — `<button>` nested inside a `<button>` on the agent card

**Symptom.** Two React console errors on every run: *"In HTML, `<button>` cannot be
a descendant of `<button>`. This will cause a hydration error."*

**Root cause.** The whole agent card in `AgentCard.tsx` is a `<button>`, and the
"Agent flow →" control inside it was also a `<button>`. Click behaviour was already
correct (`openAgentFlow` calls `stopPropagation`), so this was invalid markup and a
hydration hazard rather than a broken interaction.

**Fix.** The inner control is now `<span role="button" tabIndex={0}>` — the same
pattern the card's own stop control already uses.

**Verified.** `document.querySelectorAll('button button')` is empty during a live
streaming turn, and the run logs zero console errors.

**File:** `app/frontend/src/components/AgentCard.tsx`.
