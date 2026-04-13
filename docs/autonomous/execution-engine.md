# Execution Engine

The execution engine is everything between "task accepted" and "result ready."
It runs independently of HTTP connections, browser sessions, or user presence.

---

## The fundamental shift: sync → async

### Current state (blocking)

```python
@router.post("/task")
async def handle_task(req: TaskRequest):
    response = await master_agent.run(req.prompt)  # waits here, maybe minutes
    return {"response": response}
```

Problems:
- HTTP connection held open for the entire execution
- Browser close = task lost
- Server restart = task lost
- Only one task can run per connection

### Target state (non-blocking)

```python
@router.post("/task")
async def handle_task(req: TaskRequest):
    task_id = await task_store.create(req.prompt, source="ui")
    return {"task_id": task_id, "status": "pending"}
    # returns in < 50ms, execution happens elsewhere
```

The task now lives in the database. It exists regardless of what happens to HTTP.

---

## Task Dispatcher

The dispatcher is an `asyncio` background task that starts with the FastAPI app
and never stops while the process is running.

```python
# app/backend/dispatcher.py

import asyncio
from app.utils.db import task_store
from app.agents.master import write_task_md
from app.backend.websocket import push_event

async def dispatcher_loop():
    while True:
        try:
            await _dispatch_pending()
            await _check_timeouts()
        except Exception as e:
            log.error(f"Dispatcher error: {e}")
        await asyncio.sleep(1)

async def _dispatch_pending():
    pending = await task_store.get_by_status("pending")
    running = await task_store.get_by_status("running")

    # Concurrency limit: max N tasks running simultaneously
    max_concurrent = settings.max_concurrent_tasks  # default: 3
    if len(running) >= max_concurrent:
        return

    for task in pending[:max_concurrent - len(running)]:
        await task_store.update(task.id, status="running", assigned_agent="master")
        await write_task_md(task)
        await push_event("task_update", {"task_id": task.id, "status": "running"})

async def _check_timeouts():
    running = await task_store.get_by_status("running")
    now = datetime.utcnow()
    for task in running:
        age = (now - task.updated_at).total_seconds()
        if age > settings.task_timeout:
            await task_store.update(task.id, status="timeout")
            await push_event("task_update", {"task_id": task.id, "status": "timeout"})
```

### Starting the dispatcher with the app

```python
# app/backend/main.py

@app.on_event("startup")
async def startup():
    init_schema()
    asyncio.create_task(dispatcher_loop())  # runs forever alongside FastAPI
```

---

## Agent TASK.MD format (dispatcher writes this)

```markdown
# TASK

status: pending
task_id: task_abc123
assigned_by: dispatcher
assigned_at: 2026-04-13T22:00:00Z

## Prompt

Build a user authentication module with JWT tokens and bcrypt password hashing.
Include login, logout, and token refresh endpoints.
```

The AgentRunner (watchdog) sees this file change and wakes the master agent.

---

## How the dispatcher reads results

When master completes, it calls `notify_parent("user")`.
The `notify_parent` tool writes to the notification queue.
The dispatcher (or a separate notification listener) reads the queue
and updates the task store.

```
notify_parent("user")
    → NotificationQueue.push({ from: "master", to: "user", result: "...", task_id: "..." })
    → Dispatcher reads queue on next tick
    → task_store.update(task_id, status="done", result=result)
    → push_event("task_complete", { task_id, result })
```

This closes the loop. The notification chain that already exists
is the mechanism — the missing piece is the final consumer.

---

## Concurrency model

```
┌─────────────────────────────────────────────────────┐
│                   DISPATCHER                        │
│                                                     │
│  Slot 1: task_abc → master → planning → builder    │
│  Slot 2: task_def → master → [building in parallel]│
│  Slot 3: task_ghi → master → [queued]              │
│                                                     │
│  Pending queue: task_jkl, task_mno, task_pqr...    │
└─────────────────────────────────────────────────────┘
```

- Max N tasks run simultaneously (configurable, default 3)
- Each task gets its own master invocation (isolated TASK.MD write)
- Tasks queue automatically — no user action needed
- Doctor monitors all running tasks for stalls and timeouts

---

## AgentRunner integration

The AgentRunner is already implemented (watchdog-based TASK.MD watcher).
The dispatcher writes to TASK.MD. The runner wakes up and executes.

No changes needed to the runner — the dispatcher is a new layer
*above* the runner, not a replacement.

```
Dispatcher layer:    task store ↔ TASK.MD bridge
Runner layer:        TASK.MD watcher → agent execution
Agent layer:         LLM + tools
```

---

## Process model

Everything runs in one Python process:

```
uvicorn (FastAPI)
├── HTTP handlers (routes)
├── WebSocket manager
├── APScheduler (cron ticks)
├── asyncio task: dispatcher_loop()
├── asyncio task: notification_listener()
└── asyncio task: indexer_tick()
```

The AgentRunner runs as a subprocess per agent (already implemented).
The dispatcher triggers the runner by writing TASK.MD — the runner
self-starts via watchdog.

No separate worker processes needed at MVP scale.
If scale becomes an issue: move dispatcher to Celery + Redis. Not now.

---

## Restart resilience

On startup:

```python
@app.on_event("startup")
async def startup():
    init_schema()

    # Recover in-flight tasks from before restart
    stuck = await task_store.get_by_status("running")
    for task in stuck:
        # Check if agent is actually still running
        if not await agent_runner.is_running("master"):
            await task_store.update(task.id, status="pending")
            # Dispatcher will re-dispatch on next tick

    asyncio.create_task(dispatcher_loop())
```

Tasks that were `running` when the server crashed are reset to `pending`
and re-dispatched. No task is silently lost.
