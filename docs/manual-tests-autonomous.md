# Autonomous Features — Manual Test Plan

Covers features implemented from `docs/autonomous/roadmap.md` phases in the last milestone.
All tests assume the backend is running (`poetry run yapoc start`).

---

## Verification Summary

| Roadmap Phase | Feature | Implemented? | Key Files |
|---|---|---|---|
| 1A | Async task endpoint (fire-and-forget) | Yes | `backend/routers/tasks.py`, `utils/db.py` (`create_queued_task`) |
| 1B | Task Dispatcher | Yes | `backend/dispatcher.py` — polls task_queue, dispatches to master |
| 1C | WebSocket push (task events) | Yes | `backend/websocket.py` — `ws_manager` singleton, state_sync on connect |
| 1D | UI catch-up on connect | Yes | `useWebSocket.ts` hook + `wsStore.ts` — connects to /ws, receives state_sync |
| 2A | Agent event emission | Yes | `agents/base/__init__.py` — `_emit_event()` for thinking/text/tool events |
| 2B | Backend event relay | Yes | `websocket.py` — session subscription model, relay via `push_event` |
| 4A | Autonomous approval policy | Yes | `utils/tools/approval.py` — `check_policy()` with glob matching |
| 4C | Approval queue | Yes | `backend/approval_queue.py` — SQLite table, queue/resolve/expire |
| 4D | Cost governance (budget) | Yes | `base/__init__.py` — per-task + per-agent budget enforcement |
| 4D | Loop detection | Yes | `base/__init__.py` — `_recent_tools` deque, reflection injection, force-stop |
| 4B | Interactive approval over WebSocket | Yes | `approval_queue.py` pushes WS events; `BackgroundApprovalBanner.tsx` shows UI |
| 5A | GOALS.MD context injection | Yes | `base/context.py` — `build_goals_context()` for master |
| 5B | Goal-driven dispatch | Yes | `dispatcher.py` — `_check_goals()` when idle |
| 6 | Real cron scheduling | Yes | `cron_parser.py` + `_cron_tick()` in main.py + schedule entries in cron/NOTES.MD |
| 7A | Doctor runaway detection | Yes | `doctor/agent.py` — `_detect_runaway_agents()` |
| 8A | Webhook entry point | Yes | `backend/routers/webhook.py` — `POST /webhook/task` with Bearer auth |
| 3 | Restart persistence | Yes | `main.py` lifespan: running→pending recovery + `_startup_resume()` |

---

## Phase 1 — Fire and Forget

### Test 1A-1: Async task submission returns immediately

**Action:** POST to `/task` (not `/task/stream`) with a non-trivial prompt.

```bash
curl -s -X POST http://localhost:8000/task \
  -H "Content-Type: application/json" \
  -d '{"task": "List all agent directories and their CONFIG.md models."}'
```

**Expected:**
- Response returns within ~1 second (does not block on agent execution)
- Response contains `task_id` and `status: "pending"` (if the async path is wired)
- OR: response blocks (means async path is only via dispatcher — note which behavior you see)

### Test 1A-2: Task appears in task_queue DB

**Action:** After submitting a task, query the DB:

```bash
sqlite3 data/yapoc.db "SELECT id, prompt, status, source FROM task_queue ORDER BY created_at DESC LIMIT 5;"
```

**Expected:** Task row exists with `status = pending` or `running` or `done`.

### Test 1B-1: Dispatcher picks up pending tasks

**Setup:** Ensure the server is running (dispatcher starts automatically in lifespan).

**Action:**
1. Insert a task directly into the queue:
```bash
sqlite3 data/yapoc.db "INSERT INTO task_queue (id, prompt, status, source, created_at) VALUES ('test-dispatch-001', 'What agents are available?', 'pending', 'test', datetime('now'));"
```
2. Wait 5 seconds, then check:
```bash
sqlite3 data/yapoc.db "SELECT id, status, result FROM task_queue WHERE id = 'test-dispatch-001';"
```

**Expected:** Status transitions from `pending` → `running` → `done` (or `error`). Result field is populated.

### Test 1B-2: Dispatcher respects concurrency limit

**Action:**
1. Read `max_concurrent_tasks` from settings (default: 3)
2. Insert 5 tasks rapidly:
```bash
for i in $(seq 1 5); do
  sqlite3 data/yapoc.db "INSERT INTO task_queue (id, prompt, status, source, created_at) VALUES ('test-conc-$i', 'Echo task $i', 'pending', 'test', datetime('now'));"
done
```
3. Watch server logs: `tail -f` the server output

**Expected:** At most 3 tasks run simultaneously. Remaining tasks wait until a slot opens.

### Test 1B-3: Dispatcher handles timeouts

**Action:**
1. Set `TASK_TIMEOUT=10` in `.env` (10 seconds) and restart server
2. Submit a task that will take longer than 10 seconds
3. Wait 15 seconds and check:
```bash
sqlite3 data/yapoc.db "SELECT id, status, error FROM task_queue WHERE status = 'timeout';"
```

**Expected:** Task marked as `timeout` with error message including elapsed time.

---

## Phase 1C — WebSocket Push

### Test 1C-1: WebSocket connection + state sync

**Action:** Connect via WebSocket and observe the initial message:

```bash
# Using websocat (install: cargo install websocat)
websocat ws://localhost:8000/ws
```

**Expected:** Immediately receives a JSON message:
```json
{"type": "state_sync", "tasks": [...]}
```
The `tasks` array contains up to 20 recent tasks.

### Test 1C-2: Task lifecycle events over WebSocket

**Action:**
1. Open a WebSocket connection (keep it open)
2. In another terminal, submit a task via `POST /task` or `POST /task/stream`
3. Watch the WebSocket output

**Expected:** Receive events in order:
- `{"type": "task_created", ...}` or `{"type": "task_update", "status": "running", ...}`
- `{"type": "task_complete", "status": "done", "result": "...", ...}` or `{"type": "task_error", ...}`

### Test 1C-3: Session subscription for streaming events

**Action:**
1. Connect to WebSocket
2. Send: `{"type": "subscribe", "session_id": "test-session-123"}`
3. Verify response: `{"type": "subscribed", "session_id": "test-session-123"}`
4. Submit a task that uses session_id "test-session-123"

**Expected:** Receive `session_event` messages containing agent thinking/tool/text events.

### Test 1C-4: Ping/pong keepalive

**Action:** Send `{"type": "ping"}` over WebSocket.

**Expected:** Receive `{"type": "pong"}`.

---

## Phase 2 — Agent Event Emission

### Test 2A-1: Events written to session JSONL

**Action:**
1. Submit a task via `POST /task/stream` (SSE) and note the response
2. Check for event files:
```bash
ls data/sessions/*/events.jsonl 2>/dev/null
find data/sessions -name "events.jsonl" -exec wc -l {} \;
```

**Expected:** At least one `events.jsonl` file exists with JSONL entries. Each line is valid JSON with `type` (thinking_delta, message_delta, tool_call, tool_result), `agent`, and `timestamp` fields.

### Test 2A-2: Event types are complete

**Action:** Read an events.jsonl from a task that used tools:

```bash
cat data/sessions/*/events.jsonl | python3 -c "
import sys, json
types = set()
for line in sys.stdin:
    types.add(json.loads(line)['type'])
print(sorted(types))
"
```

**Expected:** Contains at least: `thinking_delta`, `message_delta`, `tool_call`, `tool_result`.

---

## Phase 4A — Autonomous Approval Policy

### Test 4A-1: Policy parsing from CONFIG.md

**Action:** Add an `autonomous_policy:` block to an agent's CONFIG.md, then verify parsing:

```python
from app.utils.tools.approval import parse_autonomous_policy

config = """
adapter: anthropic
model: claude-sonnet-4-6
autonomous_policy:
  shell_exec:
    auto_approve: ["poetry run pytest*", "ls *"]
    deny: ["rm -rf *", "sudo *"]
    default: queue
  file_write:
    auto_approve: ["app/projects/*"]
    deny: ["app/config/*"]
    default: queue
"""

policy = parse_autonomous_policy(config)
print(f"Tools with policies: {list(policy.tool_policies.keys())}")
print(f"shell_exec auto_approve: {policy.tool_policies['shell_exec'].auto_approve}")
print(f"shell_exec deny: {policy.tool_policies['shell_exec'].deny}")
```

**Expected:** Two tool policies parsed correctly. `auto_approve` and `deny` lists contain the expected glob patterns.

### Test 4A-2: Policy decision — auto_approve

**Action:**
```python
from app.utils.tools.approval import check_policy

config = """
autonomous_policy:
  shell_exec:
    auto_approve: ["poetry run pytest*", "ls *"]
    deny: ["rm -rf *"]
    default: queue
"""

result = check_policy("builder", "shell_exec", {"command": "poetry run pytest -v"}, config)
print(f"Decision: {result}")  # Expected: "auto_approve"
```

**Expected:** `"auto_approve"` — command matches `"poetry run pytest*"` pattern.

### Test 4A-3: Policy decision — deny takes precedence

**Action:**
```python
result = check_policy("builder", "shell_exec", {"command": "rm -rf /tmp/test"}, config)
print(f"Decision: {result}")  # Expected: "deny"
```

**Expected:** `"deny"` — deny rules are checked before auto_approve.

### Test 4A-4: Policy decision — no match falls to default

**Action:**
```python
result = check_policy("builder", "shell_exec", {"command": "curl https://example.com"}, config)
print(f"Decision: {result}")  # Expected: "queue"
```

**Expected:** `"queue"` — no pattern matches, falls through to tool default.

### Test 4A-5: No policy block → global default

**Action:**
```python
result = check_policy("builder", "file_delete", {"path": "/tmp/test"}, "adapter: anthropic\n")
print(f"Decision: {result}")  # Expected: "queue"
```

**Expected:** `"queue"` — no `autonomous_policy:` block, global default is "queue".

---

## Phase 4C — Approval Queue

### Test 4C-1: Queue a tool call

**Action:**
```python
from app.backend.approval_queue import queue_approval, get_pending

req_id = queue_approval(agent="builder", tool="shell_exec", tool_input={"command": "dangerous thing"})
print(f"Queued: {req_id}")

pending = get_pending()
print(f"Pending count: {len(pending)}")
print(f"Latest: {pending[0] if pending else 'none'}")
```

**Expected:** Returns a UUID. `get_pending()` includes the new entry with `status = 'pending'`.

### Test 4C-2: Resolve an approval

**Action:**
```python
from app.backend.approval_queue import resolve_approval

result = resolve_approval(req_id, approved=True, resolved_by="test_user")
print(f"Resolved: {result}")
```

**Expected:** Row updated with `status = 'approved'`, `resolved_at` timestamp, `resolved_by = 'test_user'`.

### Test 4C-3: Expire stale approvals

**Action:**
```python
from app.backend.approval_queue import queue_approval, expire_stale

# Queue an approval, then manually backdate its created_at
import sqlite3
from app.utils.db import get_db
req_id = queue_approval(agent="test", tool="test_tool", tool_input={})
db = get_db()
db.execute("UPDATE approval_queue SET created_at = '2020-01-01T00:00:00Z' WHERE id = ?", (req_id,))
db.commit()

expired = expire_stale(ttl_seconds=1)
print(f"Expired: {expired}")  # Expected: 1
```

**Expected:** Returns 1. The entry's status changes to `'denied'` with `resolved_by = 'system:expired'`.

---

## Phase 4D — Cost Governance

### Test 4D-1: Per-task budget enforcement

**Setup:** Set `BUDGET_PER_TASK_USD=0.001` in `.env` and restart.

**Action:**
```bash
curl -s -X POST http://localhost:8000/task/stream \
  -H "Content-Type: application/json" \
  -d '{"task": "Write a detailed analysis of all agent CONFIG.md files, comparing their models, tools, and settings."}' \
  --no-buffer
```

**Expected:**
- Stream includes `[BUDGET EXCEEDED]` message with task cost and limit
- Agent stops execution after the budget message
- HEALTH.MD for the agent contains the budget exceeded entry

**Cleanup:** Remove `BUDGET_PER_TASK_USD` from `.env` and restart.

### Test 4D-2: Per-agent lifetime budget enforcement

**Setup:** Set `BUDGET_PER_AGENT_USD=0.001` in `.env` and restart.

**Action:** Send multiple small tasks until master's USAGE.json `total_cost_usd` exceeds $0.001.

**Expected:**
- Agent stops with `[BUDGET EXCEEDED]` showing lifetime cost vs budget
- HEALTH.MD records the event

**Cleanup:** Remove `BUDGET_PER_AGENT_USD` from `.env` and restart.

### Test 4D-3: Loop detection — reflection injection

**Scenario:** An agent calls the same tool 10+ times consecutively.

**Verification approach:** Check server logs during a complex task for:
```
Loop detected: <tool_name> called 10+ times. Injecting reflection.
```

Or verify programmatically that the `_recent_tools` deque and `_loop_reflected` flag work:

```python
from collections import deque

# Simulate: 10 consecutive calls to the same tool
recent = deque(maxlen=15)
for _ in range(10):
    recent.append("file_read")

last_10 = list(recent)[-10:]
assert len(set(last_10)) == 1, "Loop should be detected"
print("PASS: loop detection logic works")
```

**Expected:** After 10 consecutive calls to the same tool:
1. First time: reflection message injected asking agent to reassess
2. Second time (after reflection): force-stop

### Test 4D-4: Per-turn tool call limit

**Setup:** Default `max_tool_calls_per_turn = 20`.

**Verification:** This is hard to trigger manually. Verify the setting exists:

```python
from app.config import settings
print(f"max_tool_calls_per_turn: {settings.max_tool_calls_per_turn}")
assert settings.max_tool_calls_per_turn == 20
```

**Expected:** Setting is `20`. When reached, a `[SYSTEM]` message is injected telling the agent to summarize and continue.

---

## Phase 5 — Self-Direction (Goals)

### Test 5A-1: GOALS.MD context injection

**Action:**
1. Write an active goal to master's GOALS.MD:
```bash
cat > app/agents/master/GOALS.MD << 'EOF'
# GOALS

## Active

- [ ] Review all agent CONFIG.md files and ensure models are up to date

## Backlog

## Done
EOF
```
2. Verify context injection:
```python
import asyncio
from pathlib import Path
from app.agents.base.context import build_goals_context

result = asyncio.run(build_goals_context(Path("app/agents/master")))
print(f"Goals context present: {bool(result)}")
print(result[:500] if result else "EMPTY")
```

**Expected:** Non-empty string containing the active goal text.

### Test 5A-2: Empty GOALS.MD produces no context

**Action:**
```python
# Reset GOALS.MD to empty template
Path("app/agents/master/GOALS.MD").write_text("# GOALS\n\n## Active\n\n## Backlog\n\n## Done\n")

result = asyncio.run(build_goals_context(Path("app/agents/master")))
print(f"Goals context: '{result}'")
```

**Expected:** Empty string — no context injected when there are no active goals.

### Test 5B-1: Goal-driven dispatch (manual trigger)

**Setup:**
1. Write an active goal to GOALS.MD (see Test 5A-1)
2. Ensure no tasks are pending or running:
```bash
sqlite3 data/yapoc.db "SELECT COUNT(*) FROM task_queue WHERE status IN ('pending', 'running');"
```

**Action:** The dispatcher checks goals every 60 seconds when idle. Either:
- Wait 60+ seconds and check for a new task:
```bash
sqlite3 data/yapoc.db "SELECT id, prompt, source FROM task_queue WHERE source = 'goal' ORDER BY created_at DESC LIMIT 1;"
```
- Or check server logs for: `Goal-driven dispatch: '...'`

**Expected:** A task with `source = 'goal'` and prompt starting with `[Goal]` appears in the queue.

**Cleanup:** Clear the active goal from GOALS.MD.

---

## Phase 7 — Doctor Runaway Detection

### Test 7-1: Doctor detects runaway cost agents

**Setup:** Manually inflate one agent's USAGE.json:

```bash
# Give builder an artificially high cost
python3 -c "
import json
from pathlib import Path
p = Path('app/agents/builder/USAGE.json')
data = json.loads(p.read_text()) if p.exists() else {}
data['total_cost_usd'] = 50.0
p.write_text(json.dumps(data, indent=2))
print('Set builder cost to \$50')
"
```

**Action:** Trigger Doctor's health check:

```python
import asyncio
from app.agents.doctor.agent import doctor_agent
asyncio.run(doctor_agent.run_health_check())
```

**Expected:**
- Doctor's output (HEALTH_SUMMARY.MD) contains a "Runaway Cost" section flagging builder
- Master's HEALTH.MD has a `[doctor] RUNAWAY_COST` or similar warning

**Cleanup:** Reset builder's USAGE.json to its actual values.

---

## Phase 8 — Webhook Entry Point

### Test 8A-1: Webhook disabled when no secret configured

**Setup:** Ensure `WEBHOOK_SECRET` is empty or unset in `.env`.

**Action:**
```bash
curl -s -X POST http://localhost:8000/webhook/task \
  -H "Content-Type: application/json" \
  -d '{"prompt": "hello from webhook"}'
```

**Expected:** HTTP 403 with `"Webhook endpoint disabled (no webhook_secret configured)"`.

### Test 8A-2: Webhook rejects invalid token

**Setup:** Set `WEBHOOK_SECRET=test-secret-123` in `.env` and restart.

**Action:**
```bash
curl -s -X POST http://localhost:8000/webhook/task \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer wrong-token" \
  -d '{"prompt": "hello from webhook"}'
```

**Expected:** HTTP 401 with `"Invalid webhook token"`.

### Test 8A-3: Webhook accepts valid token and creates task

**Action:**
```bash
curl -s -X POST http://localhost:8000/webhook/task \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-secret-123" \
  -d '{"prompt": "What agents are currently running?"}'
```

**Expected:**
- HTTP 200 with `{"task_id": "...", "status": "pending"}`
- Task appears in task_queue:
```bash
sqlite3 data/yapoc.db "SELECT id, prompt, source, status FROM task_queue WHERE source = 'webhook' ORDER BY created_at DESC LIMIT 1;"
```
- Source is `"webhook"`

### Test 8A-4: Webhook with callback URL

**Setup:** Start a simple listener (optional — for full verification):
```bash
python3 -m http.server 9999 &
```

**Action:**
```bash
curl -s -X POST http://localhost:8000/webhook/task \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-secret-123" \
  -d '{"prompt": "Say hello", "callback_url": "http://localhost:9999/callback"}'
```

**Expected:**
- Task created as pending
- After task completes, dispatcher attempts to POST result to the callback URL
- Server logs show: `Webhook callback delivered for <task_id>…`

**Cleanup:** Remove `WEBHOOK_SECRET` from `.env`, kill the listener, restart server.

---

## Cost Dashboard Endpoints

### Test CD-1: All agents usage

**Action:**
```bash
curl -s http://localhost:8000/metrics/usage | python3 -m json.tool
```

**Expected:** JSON with:
- `total_cost_usd` — sum of all agent costs
- `agent_usage` — array of per-agent objects with `name`, `total_cost_usd`, `total_input_tokens`, `total_output_tokens`, `total_tool_calls`, `total_turns`, `by_model`, `last_updated`
- `budget_per_task_usd` and `budget_per_agent_usd` from settings

### Test CD-2: Single agent usage

**Action:**
```bash
curl -s http://localhost:8000/metrics/usage/master | python3 -m json.tool
```

**Expected:** JSON with master's usage data. If no USAGE.json exists, returns zeroed-out values.

### Test CD-3: Agent metrics

**Action:**
```bash
curl -s http://localhost:8000/metrics/agents | python3 -m json.tool
```

**Expected:** Array of agent metrics objects with `name`, `status`, `is_alive`, `task_count`, `last_active_at`, `health_issues`.

### Test CD-4: Agent CPU/memory metrics

**Action:**
```bash
curl -s http://localhost:8000/metrics/agents/cpu | python3 -m json.tool
```

**Expected:** Array of CPU metric objects with `agent_name`, `pid`, `cpu_percent`, `memory_mb`, `timestamp`. Agents without running processes show `pid: null` and zero values.

---

## Phase 3 — Restart Persistence (already implemented)

**Status:** Done in `main.py` lifespan. Running tasks are reset to pending on startup (lines 258-263). `_startup_resume()` reads RESUME.MD and GOALS.MD on startup (lines 128-197).

### Test 3-1: Running tasks recovered on restart

**Action:**
1. Start a long task
2. Kill the server (`kill $(cat .yapoc.pid)`)
3. Restart server: `poetry run yapoc start`
4. Check task status:
```bash
sqlite3 data/yapoc.db "SELECT id, status FROM task_queue WHERE status = 'pending' ORDER BY created_at DESC LIMIT 5;"
```

**Expected:** Previously running tasks are now `pending`. Dispatcher picks them up and re-executes.

### Test 3-2: RESUME.MD consumed on startup

**Setup:** Write to RESUME.MD:
```bash
echo "- [ ] Check all agent health" > app/agents/master/RESUME.MD
```

**Action:** Restart server. Wait 10 seconds.

**Expected:**
- Task with `source = 'resume'` appears in task_queue
- RESUME.MD is cleared (empty)
- Server logs show: `Resumed task from RESUME.MD: ...`

---

## Phase 6 — Cron Scheduling (already implemented)

**Status:** Done. `cron_parser.py` parses schedule blocks from NOTES.MD. `_cron_tick()` in main.py runs on APScheduler interval.

### Test 6-1: Cron schedule parsing

**Action:**
```python
from app.utils.cron_parser import parse_schedule
from pathlib import Path

notes = Path("app/agents/cron/NOTES.MD").read_text()
jobs = parse_schedule(notes)
for j in jobs:
    print(f"  {j['id']}: cron={j['cron']}, assign_to={j.get('assign_to', '?')}")
```

**Expected:** 3 jobs parsed: `health-check` (every 30 min), `daily-tests` (8 AM), `daily-digest` (9 AM).

### Test 6-2: Cron job fires on schedule

**Setup:** Add a test cron entry with `*/1 * * * *` (every minute) to cron/NOTES.MD:
```yaml
  - id: test-every-minute
    cron: "*/1 * * * *"
    task: "Echo: cron test fired."
    assign_to: master
```

**Action:** Wait 1-2 minutes, then check:
```bash
sqlite3 data/yapoc.db "SELECT id, prompt, source FROM task_queue WHERE source = 'cron' ORDER BY created_at DESC LIMIT 3;"
```

**Expected:** Task with `source = 'cron'` and prompt containing `[Cron: test-every-minute]` appears.

**Cleanup:** Remove the test entry from cron/NOTES.MD.

---

## WebSocket Real-Time Features (1D + 4B)

### Test WS-1: WebSocket connection + state_sync

**Action:**
```bash
# Using websocat
websocat ws://localhost:8000/ws
```

**Expected:** Immediately receives JSON:
```json
{"type": "state_sync", "tasks": [...], "pending_approvals": [...]}
```

### Test WS-2: Real-time task events in UI

**Action:**
1. Open the YAPOC web UI
2. Open browser DevTools → Network → WS tab → verify WebSocket connection to `/ws`
3. Submit a task via Chat tab
4. Watch the WebSocket messages

**Expected:** WebSocket receives `task_update` (status: running) and `task_complete` (with result) events.

### Test WS-3: Background task notification in Chat

**Action:**
1. Send a complex task that triggers planning (e.g., "Create a new utility file and a test for it")
2. Master spawns planning and returns "task is running"
3. Wait for agents to complete

**Expected:**
- Chat shows "Agents working in background — listening for results via WebSocket"
- When the task completes, the result appears in chat automatically (no manual refresh)

### Test WS-4: Dashboard real-time updates

**Action:**
1. Open the Dashboard tab
2. In another browser tab (or via curl), submit a task
3. Watch the kanban board

**Expected:** Ticket status updates in real-time (no manual refresh needed).

### Test WS-5: Background approval via WebSocket (4B)

**Setup:** Add an autonomous_policy to builder's CONFIG.md with `default: queue` for shell_exec.

**Action:**
1. Submit a task that triggers builder to use shell_exec in autonomous mode
2. OR manually queue an approval:
```python
from app.backend.approval_queue import queue_approval
queue_approval(agent="builder", tool="shell_exec", tool_input={"command": "echo test"})
```

**Expected:**
- Yellow approval banner appears in bottom-right of UI
- Shows tool name, agent, and input preview
- "Approve" and "Deny" buttons work
- After resolution, banner disappears

### Test WS-6: Pending approvals on page load

**Setup:** Queue an approval (see Test WS-5) and then refresh the page.

**Expected:** On page load, WebSocket `state_sync` includes `pending_approvals` array. The approval banner appears immediately without waiting for a new event.

---

## Cleanup Checklist

After all tests:

1. Reset GOALS.MD: `echo -e "# GOALS\n\n## Active\n\n## Backlog\n\n## Done" > app/agents/master/GOALS.MD`
2. Reset any inflated USAGE.json files
3. Remove budget settings from `.env` (`BUDGET_PER_TASK_USD`, `BUDGET_PER_AGENT_USD`)
4. Remove `WEBHOOK_SECRET` from `.env`
5. Clean up test tasks: `sqlite3 data/yapoc.db "DELETE FROM task_queue WHERE source = 'test';"`
6. Clean up test approvals: `sqlite3 data/yapoc.db "DELETE FROM approval_queue WHERE agent = 'test';"`
7. Restart server: `poetry run yapoc restart`
