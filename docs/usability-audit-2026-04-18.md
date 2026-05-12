# YAPOC Usability Bug Audit

Date: 2026-04-18
Scope: live observability, parent notifications, background completion delivery, session/event routing, memory-context hygiene

## Executive Summary

The reported issues were valid. The largest failures were plumbing failures rather than pure model quality:

1. Session-bound live events were not wired end-to-end in the UI.
2. Sub-agent notifications could be dropped by queue dedupe logic.
3. Notification polling latency was too high for interactive use.
4. Child-agent events were not consistently tied to the same UI session.
5. Recent memory injection could overfit agents to stale verbose lines.

Core event/session plumbing and notification reliability were fixed in this pass.

Second pass (same date) added deeper fixes for session isolation, master concurrency, and background delivery guarantees.

---

## Findings

### High: Session live stream not fully wired to UI

Symptoms:
- "Live" felt random or missing.
- Agents were active in logs but users could not see turn-level activity.

Root causes:
- Frontend opened WebSocket but did not actively subscribe/unsubscribe by session.
- Frontend store ignored `session_event` messages.
- `/task/stream` did not bind the current task to a stable `session_id`.

Fixes:
- Added session subscription management in WebSocket hook.
- Added `session_event` handling in frontend store.
- Added `session_id` to `TaskRequest`, propagated through `/task` and `/task/stream`.

Files:
- `app/frontend/src/hooks/useWebSocket.ts`
- `app/frontend/src/store/wsStore.ts`
- `app/backend/models/__init__.py`
- `app/backend/routers/tasks.py`

### High: Child completions could be silently dropped

Symptoms:
- "I'll notify you" followed by no visible completion.
- Same child agent completing multiple tasks could lose later notifications.

Root cause:
- Notification queue deduped by `(parent_agent, child_agent)` while unconsumed, dropping legitimate subsequent completions.

Fix:
- Dedup now matches full payload (`parent`, `child`, `status`, `result`, `error`) for unconsumed entries.

Files:
- `app/backend/services/notification_queue.py`

### Medium: Notification latency too high

Symptoms:
- Perceived "never notifies" despite eventual queue activity.

Root cause:
- Notification poller defaulted to 30s cadence.

Fix:
- Added `notification_poll_interval_seconds` setting and wired poller startup to it.
- Default set to 5s for interactive responsiveness.

Files:
- `app/config/settings.py`
- `app/backend/main.py`

### Medium: Child-agent events not consistently tied to same UI session

Symptoms:
- Parent stream visible, child activity opaque.

Root causes:
- Spawned tasks did not carry `session_id` in TASK frontmatter.
- Subprocess runner did not restore session binding into child agent runtime.
- Base event emitter broadcast semantics were not session-targeted.

Fixes:
- `spawn_agent` writes `session_id` into TASK frontmatter.
- Runner sets `self._agent._session_id` from TASK frontmatter before execution.
- BaseAgent emits session events through session-targeted websocket method.

Files:
- `app/utils/tools/__init__.py`
- `app/utils/tools/delegation.py`
- `app/agents/base/runner.py`
- `app/backend/websocket.py`
- `app/agents/base/__init__.py`

### Medium: User had poor visibility while waiting for background work

Symptoms:
- UI says background agents are working but gives little/no insight.

Fix:
- Chat panel now shows lightweight live background activity lines derived from session events (`tool_call`, `tool_result`, generation markers).

Files:
- `app/frontend/src/components/ChatPanel.tsx`
- `app/frontend/src/store/wsStore.ts`

### Low: Memory-context pollution risk

Symptoms:
- Current-task confusion after previous failures/noisy turns.

Fix:
- Recent memory lines injected into system context are now compacted and per-line truncated, reducing stale narrative carryover.

File:
- `app/agents/base/context.py`

### High: Cross-session notification leakage (root-cause of "wrong task context")

Symptoms:
- Results from one chat session could be injected while another session was active.
- Background completions could appear "random" or be consumed by the wrong turn.

Root causes:
- Notification queue had no `session_id`.
- Master drained notifications globally (`drain("master")`), not session-scoped.
- Notification wake triggers did not preserve `session_id`.

Fixes:
- Added `session_id` to notification queue entries and dedupe criteria.
- Added session-scoped queue APIs:
  - `drain(parent, session_id=...)`
  - `pending_count(parent, session_id=...)`
  - `pending_sessions(parent)`
- Propagated session through:
  - `notify_parent` tool
  - notification poller enqueue + wake-up
  - trigger TASK frontmatter (`session_id`).
- Master notification watcher now processes pending sessions one-by-one.

Files:
- `app/backend/services/notification_queue.py`
- `app/utils/tools/delegation.py`
- `app/backend/services/notification_poller.py`
- `app/backend/main.py`
- `app/agents/master/agent.py`

### High: Master concurrency race could corrupt session binding

Symptoms:
- With parallel dispatcher tasks, `master._session_id` could be overwritten mid-turn.
- Session events could route to the wrong UI chat.

Root cause:
- Master was shared singleton without execution lock; callers mutated `_session_id` externally.

Fix:
- Added internal run lock in `MasterAgent` to serialize turns.
- Added `session_id` argument to `handle_task`/`handle_task_stream`.
- Moved session binding inside MasterAgent and restored previous value after each run.
- Updated callers to pass `session_id` explicitly (SSE route + dispatcher + notification watcher).

Files:
- `app/agents/master/agent.py`
- `app/backend/routers/tasks.py`
- `app/backend/dispatcher.py`
- `app/backend/main.py`

### Medium: Background completion could finish but never appear in chat

Symptoms:
- User sees "agents working in background" but gets no final assistant message.

Root cause:
- Notification-triggered master runs were not task_queue items, so no `task_complete` event was emitted for ChatPanel.

Fix:
- Master notification watcher now emits a session event:
  - `event.type = "notification_result"` with final `RESULT.MD` text.
- ChatPanel listens for this event while awaiting background completion and appends it to history.
- `task_complete` handling now also filters by `session_id` to avoid cross-session append.

Files:
- `app/backend/main.py`
- `app/frontend/src/components/ChatPanel.tsx`
- `app/frontend/src/store/wsStore.ts`

### Medium: SSE reconnect could duplicate side-effectful tasks

Symptoms:
- Network blip mid-stream could replay `POST /task/stream`, causing duplicate spawns/tool calls.

Fix:
- Frontend now retries stream requests only before receiving first event.
- After any event is seen, disconnects bubble as errors instead of replaying the task.

Files:
- `app/frontend/src/hooks/useStream.ts`

### Medium: Live panel still opaque for tool-heavy agents

Symptoms:
- Agent running with no textual output appeared "stuck" in live view.

Fixes:
- Runner now writes tool/activity markers to `LIVE.MD`:
  - `[thinking...]`
  - `[tool:start] ...`
  - `[tool:done|error] ...`
- Agent detail file viewer now supports automatic 1s refresh when `LIVE.MD` is selected.

Files:
- `app/agents/base/runner.py`
- `app/frontend/src/agent-status/api/agentStatusClient.ts`
- `app/frontend/src/agent-status/components/detail/AgentFileViewer.tsx`

### Medium: Background task list could miss completions if task not already present

Symptoms:
- `task_complete` / `task_error` only updated existing rows and could be dropped if missing from local list window.

Fix:
- WebSocket store now upserts task rows for update/complete/error events.
- Dispatcher now includes `session_id` and `source` in task lifecycle websocket payloads.

Files:
- `app/frontend/src/store/wsStore.ts`
- `app/backend/dispatcher.py`

### Medium: Stale result injection across sessions

Symptoms:
- `/task/stream` could inject completed sub-agent results from unrelated sessions.

Fix:
- `collect_agent_results()` now supports `session_id` filtering.
- `/task/stream` calls it with active session id.

Files:
- `app/backend/services/agent_results.py`
- `app/backend/routers/tasks.py`

---

## Validation Performed

### Type/syntax checks
- `python3 -m py_compile` over changed backend files: PASS
- `pnpm -C app/frontend exec tsc --noEmit --pretty false`: PASS

### New targeted test (queue session behavior)
- Added: `app/backend/tests/test_notification_queue.py`
- Local execution in this environment failed at import-time due missing Python deps (`aiofiles`) in the test runtime, so full pytest confirmation is still pending.

### Test execution status
- `poetry` unavailable in environment (`poetry: command not found`)
- `pytest` without project deps failed at import-time (`pydantic`, `fastapi` missing)

Result:
- Full backend test suite could not be executed in this environment due missing Python dependencies.

---

## Remaining Risks / Follow-ups

1. Sub-agent final result quality is still partly prompt-dependent.
2. Session-event UX is now functional plumbing, but the rendering is still minimal and can be expanded into a richer timeline.
3. Memory hygiene improved, but a stronger task-scoped memory model would further reduce cross-task contamination.
4. Existing dirty workspace includes many unrelated modifications; this audit addressed targeted usability/reliability bugs only.

---

## Outcome

The major "unpleasant to use" path has been materially improved:
- session live stream is wired,
- child events can flow in-session,
- queue drop behavior is fixed,
- notification latency is reduced,
- chat provides visible background progress instead of blind waiting.
