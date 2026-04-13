# Global Task Completion Notification System

## Overview

This document describes the design for a backend service that tracks parent→child agent spawn relationships and notifies parent agents when their child agents complete. The system is implemented entirely in the backend, works for all agent types, uses cheap non-LLM polling, and persists state across restarts.

### Goals

- Track every `spawn_agent` call as a parent→child relationship
- Poll all active agent `TASK.MD` files every 30s (non-LLM, pure file I/O)
- When a child completes, inject a notification into the parent's next LLM turn
- Support arbitrary chains: `master → planning → builder`
- Survive process restarts via JSON persistence
- Zero LLM cost for monitoring

---

## Architecture Overview

Three cooperating backend components:

```
┌─────────────────────────────────────────────────────────────┐
│                    Backend Services                          │
│                                                             │
│  ┌──────────────────┐   ┌──────────────────────────────┐   │
│  │  SpawnRegistry   │   │    NotificationPoller        │   │
│  │                  │◄──│  (asyncio background task)   │   │
│  │  data/           │   │  polls TASK.MD every 30s     │   │
│  │  spawn_registry  │   └──────────────┬───────────────┘   │
│  │  .json           │                  │                    │
│  └──────────────────┘                  ▼                    │
│                         ┌──────────────────────────────┐   │
│                         │    NotificationQueue         │   │
│                         │                              │   │
│                         │  data/                       │   │
│                         │  notification_queue.json     │   │
│                         └──────────────┬───────────────┘   │
└──────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
                          Agent LLM Turn (agent_runner.py)
                          drain() → inject system message
```

### Components

| Component | File | Responsibility |
|---|---|---|
| `SpawnRegistry` | `backend/services/spawn_registry.py` | Persist spawn relationships, track status |
| `NotificationPoller` | `backend/services/notification_poller.py` | Background asyncio task, polls TASK.MD files |
| `NotificationQueue` | `backend/services/notification_queue.py` | Per-agent queue of pending notifications |
| Agent Runner hook | `backend/services/agent_runner.py` | Drain queue and inject system message before LLM call |

---

## Data Models

```python
from dataclasses import dataclass, field
from typing import Optional
import uuid
from datetime import datetime, timezone

@dataclass
class SpawnRecord:
    id: str                          # uuid4
    parent_agent: str                # e.g. "master", "planning"
    child_agent: str                 # e.g. "builder", "keeper"
    spawned_at: str                  # ISO8601 UTC
    status: str                      # "pending" | "completed" | "error" | "stale"
    completed_at: Optional[str] = None
    result_summary: Optional[str] = None   # first 500 chars of ## Result section
    notified: bool = False

    @staticmethod
    def new(parent_agent: str, child_agent: str) -> "SpawnRecord":
        return SpawnRecord(
            id=str(uuid.uuid4()),
            parent_agent=parent_agent,
            child_agent=child_agent,
            spawned_at=datetime.now(timezone.utc).isoformat(),
            status="pending",
        )

@dataclass
class Notification:
    id: str                          # uuid4
    spawn_record_id: str
    parent_agent: str
    child_agent: str
    status: str                      # "completed" | "error"
    result_summary: Optional[str]
    created_at: str                  # ISO8601 UTC
    delivered: bool = False

    @staticmethod
    def from_record(record: SpawnRecord) -> "Notification":
        return Notification(
            id=str(uuid.uuid4()),
            spawn_record_id=record.id,
            parent_agent=record.parent_agent,
            child_agent=record.child_agent,
            status=record.status,
            result_summary=record.result_summary,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
```

---

## SpawnRegistry

**File:** `backend/services/spawn_registry.py`  
**Persistence:** `data/spawn_registry.json`

### Responsibilities

- Record every `spawn_agent` tool call as a `SpawnRecord`
- Provide the poller with all active (pending) records
- Mark records as completed/error when the poller detects a status change
- Mark records as notified once the notification has been delivered

### API

```python
class SpawnRegistry:
    def __init__(self, path: str = "data/spawn_registry.json"):
        self._path = Path(path)
        self._lock = asyncio.Lock()
        self._records: Dict[str, SpawnRecord] = {}

    async def load(self) -> None:
        """Load records from disk on startup."""

    async def register_spawn(self, parent_agent: str, child_agent: str) -> SpawnRecord:
        """Called by spawn_agent tool handler. Creates and persists a SpawnRecord."""

    async def mark_completed(
        self,
        child_agent: str,
        status: str,           # "completed" or "error"
        result_summary: Optional[str] = None
    ) -> Optional[SpawnRecord]:
        """Called by poller when TASK.MD status changes to done/error."""

    async def get_active_children(self) -> List[SpawnRecord]:
        """Returns all SpawnRecords with status='pending' for polling."""

    async def get_unnotified_for_parent(self, parent_agent: str) -> List[SpawnRecord]:
        """Returns completed/error records for parent that haven't been notified yet."""

    async def mark_notified(self, record_id: str) -> None:
        """Marks a record as notified=True after notification is delivered."""

    async def mark_stale(self, record_id: str) -> None:
        """Marks records older than STALE_TIMEOUT_HOURS as stale."""

    async def _save(self) -> None:
        """Atomic write: write to .tmp then os.replace()."""
```

### Persistence Format

```json
{
  "records": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "parent_agent": "master",
      "child_agent": "planning",
      "spawned_at": "2026-04-10T14:00:00Z",
      "status": "completed",
      "completed_at": "2026-04-10T14:05:00Z",
      "result_summary": "Decomposed task into 3 subtasks and delegated to builder...",
      "notified": false
    }
  ]
}
```

### Atomic Write Pattern

```python
async def _save(self) -> None:
    tmp = self._path.with_suffix(".tmp")
    data = {"records": [asdict(r) for r in self._records.values()]}
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, self._path)
```

---

## NotificationPoller

**File:** `backend/services/notification_poller.py`  
**Type:** Background `asyncio` task (started at app startup via `lifespan`)

### Poll Loop

```python
class NotificationPoller:
    def __init__(
        self,
        registry: SpawnRegistry,
        queue: NotificationQueue,
        poll_interval: int = 30,
        project_root: Path = Path("."),
    ):
        self._registry = registry
        self._queue = queue
        self._interval = poll_interval
        self._root = project_root

    async def start(self) -> None:
        """Entry point — runs forever until cancelled."""
        while True:
            try:
                await self._poll_once()
            except Exception as e:
                logger.warning(f"Poller error: {e}")
            await asyncio.sleep(self._interval)

    async def _poll_once(self) -> None:
        active = await self._registry.get_active_children()
        for record in active:
            await self._check_record(record)

    async def _check_record(self, record: SpawnRecord) -> None:
        task_md_path = self._root / "agents" / record.child_agent / "TASK.MD"
        try:
            content = task_md_path.read_text()
        except FileNotFoundError:
            logger.debug(f"TASK.MD not found for {record.child_agent}, skipping")
            return

        status = self._parse_status(content)
        if status in ("done", "error"):
            result_summary = self._extract_result(content)
            normalized = "completed" if status == "done" else "error"
            updated = await self._registry.mark_completed(
                record.child_agent, normalized, result_summary
            )
            if updated:
                notification = Notification.from_record(updated)
                await self._queue.enqueue(notification)
```

### TASK.MD Parsing (No External Dependencies)

```python
def _parse_status(self, content: str) -> Optional[str]:
    """Extract status from YAML frontmatter between --- delimiters."""
    import re
    match = re.search(r"^---\s*\n(.*?)\n---", content, re.DOTALL | re.MULTILINE)
    if not match:
        return None
    for line in match.group(1).splitlines():
        if line.startswith("status:"):
            return line.split(":", 1)[1].strip()
    return None

def _extract_result(self, content: str, max_chars: int = 500) -> Optional[str]:
    """Extract text from ## Result section."""
    import re
    match = re.search(r"^## Result\s*\n(.*?)(?=^##|\Z)", content, re.DOTALL | re.MULTILINE)
    if not match:
        return None
    text = match.group(1).strip()
    return text[:max_chars] if text else None
```

### Startup Integration

```python
# backend/main.py (or app.py)
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    registry = SpawnRegistry()
    await registry.load()
    queue = NotificationQueue()
    await queue.load()
    poller = NotificationPoller(registry, queue)
    task = asyncio.create_task(poller.start())
    app.state.registry = registry
    app.state.notification_queue = queue
    yield
    # Shutdown
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
```

---

## NotificationQueue

**File:** `backend/services/notification_queue.py`  
**Persistence:** `data/notification_queue.json`

### API

```python
class NotificationQueue:
    def __init__(self, path: str = "data/notification_queue.json"):
        self._path = Path(path)
        self._lock = asyncio.Lock()
        self._queues: Dict[str, List[Notification]] = {}

    async def load(self) -> None:
        """Load from disk on startup."""

    async def enqueue(self, notification: Notification) -> None:
        """Add notification to parent agent's queue and persist."""

    async def drain(self, agent_name: str) -> List[Notification]:
        """Remove and return all pending notifications for agent. Persists after drain."""

    async def peek(self, agent_name: str) -> List[Notification]:
        """Non-destructive read of pending notifications."""

    async def _save(self) -> None:
        """Atomic write to disk."""
```

### Persistence Format

```json
{
  "queues": {
    "master": [
      {
        "id": "abc123",
        "spawn_record_id": "550e8400-...",
        "parent_agent": "master",
        "child_agent": "planning",
        "status": "completed",
        "result_summary": "Decomposed task into 3 subtasks...",
        "created_at": "2026-04-10T14:05:00Z",
        "delivered": false
      }
    ]
  }
}
```

---

## Injection into Agent Turns

**Integration point:** `backend/services/agent_runner.py` (wherever the LLM messages array is assembled before calling the model API)

### Injection Logic

```python
async def build_messages_for_turn(
    agent_name: str,
    conversation_history: List[dict],
    notification_queue: NotificationQueue,
    registry: SpawnRegistry,
) -> List[dict]:
    messages = list(conversation_history)

    # Drain pending notifications
    notifications = await notification_queue.drain(agent_name)
    if notifications:
        # Mark as notified in registry
        for n in notifications:
            await registry.mark_notified(n.spawn_record_id)

        # Build system notification message
        lines = ["[SYSTEM NOTIFICATION] The following child agents have completed:"]
        for n in notifications:
            summary = n.result_summary or "(no result)"
            lines.append(f"- {n.child_agent} ({n.status}): \"{summary}\"")
        notification_text = "\n".join(lines)

        # Inject as system message at start of messages array
        messages.insert(0, {"role": "system", "content": notification_text})

    return messages
```

### Injected Message Example

```
[SYSTEM NOTIFICATION] The following child agents have completed:
- builder (completed): "Successfully created docs/design/global-task-notification-system.md (342 lines)"
- keeper (error): "Failed to write config: permission denied on /etc/app.conf"
```

---

## Integration with spawn_agent Tool

The `spawn_agent` tool handler must call `registry.register_spawn()` on every invocation:

```python
# In the spawn_agent tool implementation
async def handle_spawn_agent(
    agent_name: str,
    task: str,
    context: str,
    calling_agent: str,          # the agent that invoked spawn_agent
    registry: SpawnRegistry,
    **kwargs
) -> str:
    # ... existing spawn logic ...

    # Register the spawn relationship
    record = await registry.register_spawn(
        parent_agent=calling_agent,
        child_agent=agent_name,
    )

    return f"Agent '{agent_name}' spawned (spawn_id: {record.id})"
```

The `calling_agent` context must be threaded through from the agent runner so the registry knows which parent is spawning.

---

## Sequence Diagram

```
Master Agent                 Planning Agent              Backend Services
     │                            │                           │
     │──spawn_agent("planning")──►│                           │
     │                            │    register_spawn(        │
     │                            │      "master","planning") │
     │                            │                           │
     │                            │  [planning works...]      │
     │                            │                           │
     │                            │    [poller tick: 30s]     │
     │                            │    read agents/planning/  │
     │                            │    TASK.MD → status=done  │
     │                            │    mark_completed()       │
     │                            │    enqueue(Notification{  │
     │                            │      parent="master"})    │
     │                            │                           │
     │  [master next LLM turn]    │                           │
     │◄──drain("master")──────────┼───────────────────────────│
     │  [system msg injected]     │                           │
     │  "planning completed: ..." │                           │
     │                            │                           │
```

---

## File Structure

```
backend/
  services/
    spawn_registry.py         # SpawnRecord persistence + CRUD
    notification_poller.py    # Background asyncio polling task
    notification_queue.py     # Per-agent notification queue
  agent_runner.py             # (existing) — add drain() call before LLM turns
  main.py                     # (existing) — add lifespan startup/shutdown

data/
  spawn_registry.json         # Persisted spawn relationships (auto-created)
  notification_queue.json     # Persisted undelivered notifications (auto-created)

docs/
  design/
    global-task-notification-system.md   # This document
```

---

## Configuration

| Environment Variable | Default | Range | Description |
|---|---|---|---|
| `NOTIFICATION_POLL_INTERVAL` | `30` | 30–60 | Seconds between poll cycles |
| `NOTIFICATION_MAX_RESULT_CHARS` | `500` | — | Max chars of result to include in notification |
| `SPAWN_REGISTRY_PATH` | `data/spawn_registry.json` | — | Registry persistence file path |
| `NOTIFICATION_QUEUE_PATH` | `data/notification_queue.json` | — | Queue persistence file path |
| `SPAWN_STALE_TIMEOUT_HOURS` | `24` | — | Hours before pending record is marked stale |

---

## Persistence & Restart Recovery

### Startup Sequence

1. Load `data/spawn_registry.json` → restore all `SpawnRecord` objects
2. Load `data/notification_queue.json` → restore all pending `Notification` objects
3. Identify all records with `status="pending"` → immediately poll their TASK.MD files (catch-up pass)
4. Start `NotificationPoller` background task

### Atomic Write Pattern

All writes use a write-to-temp-then-rename pattern to prevent corruption:

```python
async def _save(self) -> None:
    async with self._lock:
        tmp = self._path.with_suffix(".tmp")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(self._to_dict(), indent=2))
        os.replace(tmp, self._path)   # atomic on POSIX systems
```

---

## Edge Cases & Error Handling

| Scenario | Handling |
|---|---|
| Child agent TASK.MD missing | Log debug warning, skip record, retry next poll cycle |
| Child agent never completes | After `SPAWN_STALE_TIMEOUT_HOURS`, mark record as `stale` (not error) |
| Parent agent never runs again | Notifications persist in queue indefinitely (no TTL) |
| Multiple children complete | All notifications batched into one system message per turn |
| Nested chains (master→planning→builder) | Each link tracked independently; planning notified about builder, master about planning |
| Duplicate spawn registration | Dedup by `(child_agent, spawned_at)` within a 1-second window |
| TASK.MD frontmatter parse error | Log warning, skip record, retry next cycle |
| Concurrent poll + drain race | `asyncio.Lock` on all registry and queue mutations |
| data/ directory missing | Auto-created by `_save()` via `mkdir(parents=True, exist_ok=True)` |

---

## Implementation Notes

1. **No blocking I/O**: All file reads in the poller use `asyncio.to_thread(path.read_text)` to avoid blocking the event loop
2. **No YAML dependency**: Frontmatter parsed with a single `re.search()` call — no PyYAML required
3. **No LLM calls**: The entire notification system is pure Python file I/O + asyncio
4. **Idempotent polling**: `mark_completed()` is a no-op if the record is already completed
5. **Thread safety**: All shared state protected by `asyncio.Lock` (single-process asyncio model)
6. **Graceful shutdown**: Poller task is cancelled on app shutdown; in-flight notifications are already persisted

---

## Testing Strategy

### Unit Tests

```python
# tests/test_spawn_registry.py
async def test_register_and_complete():
    registry = SpawnRegistry(path=":memory:")  # or tmp file
    record = await registry.register_spawn("master", "builder")
    assert record.status == "pending"
    updated = await registry.mark_completed("builder", "completed", "done!")
    assert updated.status == "completed"
    assert updated.result_summary == "done!"

# tests/test_notification_poller.py
async def test_poll_detects_completion(tmp_path):
    # Write a TASK.MD with status=done
    task_md = tmp_path / "agents" / "builder" / "TASK.MD"
    task_md.parent.mkdir(parents=True)
    task_md.write_text("---\nstatus: done\n---\n## Result\nFile created.\n")
    # Run one poll cycle and verify notification enqueued
    ...
```

### Integration Test

Spawn a real builder agent, wait for completion, verify notification appears in master's queue.

---

*Document version: 1.0 — Created 2026-04-10*
