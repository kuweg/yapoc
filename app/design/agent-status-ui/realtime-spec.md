# YAPOC Agent-Status UI — Real-Time Update Mechanism & Integration Spec

**Version:** 1.0  
**Date:** 2026-04-10  
**Architecture context:** YAPOC is file-based; agents write state to disk files under `app/agents/{name}/`

---

## 1. Data Source — Recommended Approach

### 1.1 Options Considered

| Approach | Pros | Cons | Fit for YAPOC |
|----------|------|------|---------------|
| **HTTP Polling** | Simple, stateless, works with any backend | Higher latency, more requests | ✅ Good fit |
| **WebSocket** | True push, low latency | Requires persistent connection management, more complex server | ⚠️ Overkill for file-based state |
| **Server-Sent Events (SSE)** | Push from server, simple protocol, auto-reconnect | One-directional only | ✅ Good fit for event log |
| **File watching (inotify/FSEvents)** | Instant updates | Browser cannot watch files directly | ❌ Server-side only |

### 1.2 Recommended Architecture: Hybrid Polling + SSE

**Use HTTP polling for agent state** (status, health, task) and **SSE for the live event log feed**.

**Rationale:**
- YAPOC's state lives in files on disk. The backend already reads these files to serve `/api/agents`. Polling is a natural fit — it's stateless, easy to implement, and resilient to connection drops.
- Agent state changes are not sub-second events. A 2-second polling interval provides near-real-time UX without hammering the filesystem.
- The event log (HEALTH.MD entries, task completions) benefits from SSE because it's a stream of discrete events, not a polled snapshot.
- The existing frontend already uses `fetch` for `/api/agents` — polling extends this pattern naturally.

**Architecture diagram:**

```
Browser                          Backend (FastAPI)              Filesystem
  │                                    │                             │
  │  GET /api/agents (every 2s)        │                             │
  ├───────────────────────────────────>│  read STATUS.json (all)     │
  │                                    ├────────────────────────────>│
  │                                    │<────────────────────────────┤
  │<───────────────────────────────────┤  AgentStatus[] JSON         │
  │                                    │                             │
  │  GET /api/agents/:name (every 5s)  │                             │
  ├───────────────────────────────────>│  read TASK.MD + HEALTH.MD   │
  │                                    ├────────────────────────────>│
  │                                    │<────────────────────────────┤
  │<───────────────────────────────────┤  AgentDetail JSON           │
  │                                    │                             │
  │  GET /api/events (SSE stream)      │                             │
  ├───────────────────────────────────>│  watch HEALTH.MD files      │
  │  ←─── event: agent_event ─────────┤  (inotify / polling)        │
  │  ←─── event: agent_event ─────────┤                             │
  │  ←─── event: agent_event ─────────┤                             │
```

---

## 2. Update Frequency

Different data types have different staleness tolerances:

| Data Type | Source File | Recommended Interval | Rationale |
|-----------|------------|---------------------|-----------|
| **Agent status list** | `STATUS.json` (all agents) | **2 seconds** | Status changes (running→done) need near-instant visibility |
| **Agent detail / task** | `TASK.MD` frontmatter | **5 seconds** | Task text rarely changes mid-run; 5s is sufficient |
| **Health log** | `HEALTH.MD` | **10 seconds** | Health entries are written infrequently; 10s is fine |
| **Memory (last entry)** | `MEMORY.MD` | **30 seconds** | Memory is a log; last entry changes slowly |
| **System summary** (sidebar) | Derived from agent list | **2 seconds** | Recomputed from the agent list poll; no extra request |
| **Event log** | SSE stream | **Push (real-time)** | Events should appear immediately |

### 2.1 Polling Implementation Notes

- Use `setInterval` with `clearInterval` on component unmount (or React Query's `refetchInterval`)
- Stagger initial fetches to avoid thundering herd: add `Math.random() * 500ms` jitter to each interval start
- On tab visibility change (`document.visibilityState`): pause polling when tab is hidden, resume when visible
- On connection error: implement exponential backoff (2s → 4s → 8s → 16s → max 60s)

---

## 3. Data Model

### 3.1 AgentStatus — Core Object (from `/api/agents`)

```typescript
/**
 * Lightweight status object returned for all agents in the list view.
 * Sourced from: app/agents/{name}/STATUS.json
 */
export interface AgentStatus {
  // Identity
  name: string;                    // e.g. "builder", "planning"
  
  // Process state (from STATUS.json)
  state: 'running' | 'idle' | 'done' | 'error';
  pid: number | null;              // null when not running
  started_at: string | null;       // ISO 8601 UTC, e.g. "2026-04-10T11:00:47Z"
  updated_at: string | null;       // ISO 8601 UTC — last STATUS.json write
  idle_since: string | null;       // ISO 8601 UTC — when agent went idle
  task_summary: string | null;     // First 120 chars of current task
  
  // Health (derived from HEALTH.MD)
  health: 'ok' | 'warning' | 'critical';
  health_error_count: number;      // Count of ERROR/CRITICAL entries in HEALTH.MD
  
  // Configuration (from CONFIG.md or agent.py)
  model: string;                   // e.g. "claude-sonnet-4-6"
  adapter: string;                 // e.g. "anthropic", "openai", "google"
  
  // Memory
  memory_entries: number;          // Count of entries in MEMORY.MD
  last_memory_entry: string | null; // Last line of MEMORY.MD (truncated to 100 chars)
}
```

### 3.2 AgentDetail — Full Object (from `/api/agents/:name`)

```typescript
/**
 * Full detail object for a single agent, shown in the detail panel.
 * Sourced from: STATUS.json + TASK.MD + HEALTH.MD + MEMORY.MD
 */
export interface AgentDetail extends AgentStatus {
  // Full task (from TASK.MD)
  task: TaskDetail | null;
  
  // Health history (from HEALTH.MD)
  health_log: HealthLogEntry[];    // Last 20 entries
  
  // Memory (from MEMORY.MD)
  memory_log: string[];            // Last 5 entries (full text)
  
  // Computed
  uptime_seconds: number | null;   // Computed from started_at
}

export interface TaskDetail {
  // TASK.MD frontmatter
  status: string;                  // e.g. "running", "done"
  assigned_by: string;             // e.g. "master"
  assigned_at: string;             // ISO 8601 UTC
  completed_at: string | null;     // ISO 8601 UTC or null
  
  // TASK.MD body
  task_text: string;               // Full ## Task section content
  result_text: string | null;      // ## Result section content
  error_text: string | null;       // ## Error section content
}

export interface HealthLogEntry {
  timestamp: string;               // e.g. "2026-04-10 13:01"
  level: 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL' | 'AUDIT';
  message: string;
  context: string | null;
}
```

### 3.3 AgentEvent — SSE Event Object

```typescript
/**
 * Real-time event pushed via SSE from /api/events
 */
export interface AgentEvent {
  id: string;                      // Unique event ID (UUID)
  timestamp: string;               // ISO 8601 UTC
  agent_name: string;              // Which agent generated this event
  event_type: AgentEventType;
  message: string;                 // Human-readable description
  level: 'info' | 'warning' | 'error';
  metadata?: Record<string, unknown>; // Optional extra data
}

export type AgentEventType =
  | 'status_changed'    // Agent state transition (e.g. idle → running)
  | 'task_assigned'     // New task written to TASK.MD
  | 'task_completed'    // Task marked done
  | 'task_failed'       // Task marked error
  | 'health_warning'    // New WARNING entry in HEALTH.MD
  | 'health_critical'   // New CRITICAL entry in HEALTH.MD
  | 'agent_spawned'     // Agent process started
  | 'agent_killed'      // Agent process terminated
  | 'memory_updated';   // New entry in MEMORY.MD
```

### 3.4 JSON Schema (for backend validation)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AgentStatus",
  "type": "object",
  "required": ["name", "state", "health", "model", "adapter"],
  "properties": {
    "name": { "type": "string" },
    "state": { "type": "string", "enum": ["running", "idle", "done", "error"] },
    "pid": { "type": ["integer", "null"] },
    "started_at": { "type": ["string", "null"], "format": "date-time" },
    "updated_at": { "type": ["string", "null"], "format": "date-time" },
    "idle_since": { "type": ["string", "null"], "format": "date-time" },
    "task_summary": { "type": ["string", "null"], "maxLength": 120 },
    "health": { "type": "string", "enum": ["ok", "warning", "critical"] },
    "health_error_count": { "type": "integer", "minimum": 0 },
    "model": { "type": "string" },
    "adapter": { "type": "string" },
    "memory_entries": { "type": "integer", "minimum": 0 },
    "last_memory_entry": { "type": ["string", "null"], "maxLength": 100 }
  }
}
```

---

## 4. Integration Points with YAPOC File System

### 4.1 Reading `app/agents/{name}/STATUS.json`

**File format (actual):**
```json
{
  "state": "running",
  "pid": 53743,
  "task_summary": "Create the directory app/design/agent-status-ui/...",
  "started_at": "2026-04-10T11:00:47Z",
  "updated_at": "2026-04-10T11:04:14Z",
  "idle_since": null
}
```

**Backend parsing logic:**
```python
import json
from pathlib import Path

def read_agent_status(agent_name: str) -> dict:
    path = Path(f"app/agents/{agent_name}/STATUS.json")
    if not path.exists():
        return {"state": "idle", "pid": None, "task_summary": None, 
                "started_at": None, "updated_at": None, "idle_since": None}
    with open(path) as f:
        return json.load(f)
```

**Health derivation from STATUS.json:** The `state` field maps directly to the UI status. If `state` is missing or the file doesn't exist, treat as `"idle"`.

### 4.2 Reading `app/agents/{name}/TASK.MD`

**File format (actual):**
```markdown
---
status: running
assigned_by: master
assigned_at: 2026-04-10T11:04:14Z
completed_at: 
---
## Task
[full task text]

## Result
[result text or empty]

## Error
[error text or empty]
```

**Backend parsing logic:**
```python
import re
from pathlib import Path

def read_agent_task(agent_name: str) -> dict | None:
    path = Path(f"app/agents/{agent_name}/TASK.MD")
    if not path.exists():
        return None
    
    content = path.read_text()
    
    # Parse YAML frontmatter
    fm_match = re.match(r'^---\n(.*?)\n---\n', content, re.DOTALL)
    frontmatter = {}
    if fm_match:
        for line in fm_match.group(1).splitlines():
            if ': ' in line:
                key, _, value = line.partition(': ')
                frontmatter[key.strip()] = value.strip() or None
    
    # Parse sections
    sections = {}
    for section in ['Task', 'Result', 'Error']:
        match = re.search(rf'## {section}\n(.*?)(?=\n## |\Z)', content, re.DOTALL)
        sections[section.lower()] = match.group(1).strip() if match else None
    
    return {**frontmatter, **sections}
```

### 4.3 Reading `app/agents/{name}/HEALTH.MD`

**File format (actual):**
```
[2026-04-10 13:01] [AUDIT] APPROVED file_write: {'path': '...'}
[2026-04-10 12:55] INFO: HEALTH_CHECK_COMPLETE: ...
[2026-04-10 12:40] WARNING: Model Manager agent: INACTIVE | context: ...
```

**Backend parsing logic:**
```python
import re
from pathlib import Path

HEALTH_LINE_RE = re.compile(
    r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\] '
    r'(?:\[(\w+)\] )?'
    r'(INFO|WARNING|ERROR|CRITICAL|AUDIT)?:?\s*(.*?)(?:\s*\|\s*context:\s*(.*))?$'
)

def read_agent_health(agent_name: str, last_n: int = 20) -> list[dict]:
    path = Path(f"app/agents/{agent_name}/HEALTH.MD")
    if not path.exists():
        return []
    
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        m = HEALTH_LINE_RE.match(line)
        if m:
            entries.append({
                "timestamp": m.group(1),
                "level": m.group(2) or m.group(3) or "INFO",
                "message": m.group(4) or line,
                "context": m.group(5),
            })
    
    # Derive health status from recent entries
    return entries[-last_n:]

def derive_health_status(entries: list[dict]) -> tuple[str, int]:
    """Returns (health_status, error_count)"""
    recent = entries[-10:]  # Last 10 entries
    error_count = sum(1 for e in recent if e["level"] in ("ERROR", "CRITICAL"))
    warning_count = sum(1 for e in recent if e["level"] == "WARNING")
    
    if error_count > 0:
        return "critical", error_count
    elif warning_count > 0:
        return "warning", warning_count
    return "ok", 0
```

### 4.4 Reading `app/agents/{name}/MEMORY.MD`

**File format (actual):**
```
[2026-04-10 13:01] task: --- status: running ... | response: I'll start by reading...
[2026-04-10 12:51] task: --- status: running ... | response: ...
```

**Backend parsing logic:**
```python
from pathlib import Path

def read_agent_memory(agent_name: str) -> tuple[int, str | None]:
    """Returns (entry_count, last_entry_truncated)"""
    path = Path(f"app/agents/{agent_name}/MEMORY.MD")
    if not path.exists():
        return 0, None
    
    lines = [l.strip() for l in path.read_text().splitlines() if l.strip()]
    count = len(lines)
    last = lines[-1][:100] if lines else None
    return count, last
```

---

## 5. Backend API Spec

All endpoints are served by the existing FastAPI backend. Base URL: `/api`

### 5.1 `GET /api/agents`

Returns the status of all known agents.

**Response:** `200 OK`
```json
[
  {
    "name": "builder",
    "state": "running",
    "pid": 53743,
    "started_at": "2026-04-10T11:00:47Z",
    "updated_at": "2026-04-10T11:04:14Z",
    "idle_since": null,
    "task_summary": "Create the directory app/design/agent-status-ui/...",
    "health": "ok",
    "health_error_count": 0,
    "model": "claude-sonnet-4-6",
    "adapter": "anthropic",
    "memory_entries": 12,
    "last_memory_entry": "[2026-04-10 13:01] Cleaned up stale health/crash log data..."
  }
]
```

**Implementation notes:**
- Scan `app/agents/` directory for subdirectories
- Read `STATUS.json`, `HEALTH.MD`, `MEMORY.MD` for each
- Read `CONFIG.md` or `agent.py` to extract model/adapter
- Return sorted by: running first, then error, then idle, then done

### 5.2 `GET /api/agents/:name`

Returns full detail for a single agent.

**Response:** `200 OK` — `AgentDetail` object (see §3.2)  
**Response:** `404 Not Found` — if agent directory does not exist

```json
{
  "name": "builder",
  "state": "running",
  "...": "...all AgentStatus fields...",
  "task": {
    "status": "running",
    "assigned_by": "master",
    "assigned_at": "2026-04-10T11:04:14Z",
    "completed_at": null,
    "task_text": "Create the directory app/design/agent-status-ui/...",
    "result_text": null,
    "error_text": null
  },
  "health_log": [
    {
      "timestamp": "2026-04-10 13:01",
      "level": "AUDIT",
      "message": "APPROVED file_write: {'path': 'app/agents/cron/HEALTH.MD', ...}",
      "context": null
    }
  ],
  "memory_log": [
    "[2026-04-10 13:01] Cleaned up stale health/crash log data across all agents..."
  ],
  "uptime_seconds": 7415
}
```

### 5.3 `GET /api/agents/:name/health`

Returns only the health log for a single agent (lightweight endpoint for polling).

**Response:** `200 OK`
```json
{
  "name": "builder",
  "health": "ok",
  "health_error_count": 0,
  "log": [
    {
      "timestamp": "2026-04-10 13:01",
      "level": "AUDIT",
      "message": "APPROVED file_write: ...",
      "context": null
    }
  ]
}
```

### 5.4 `GET /api/events` (SSE)

Server-Sent Events stream for the live event log.

**Headers:**
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

**Event format:**
```
id: 550e8400-e29b-41d4-a716-446655440000
event: agent_event
data: {"id":"550e8400...","timestamp":"2026-04-10T13:04:22Z","agent_name":"builder","event_type":"status_changed","message":"builder: running → done","level":"info"}

```

**Implementation:** Backend watches HEALTH.MD files using a polling loop (every 1s) or `watchfiles` library, emitting SSE events when new lines are detected.

### 5.5 Existing Endpoints (already implemented)

The following endpoints already exist in `app/frontend/src/api/client.ts` and should be preserved:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/agents` | List all agents (extend to return full `AgentStatus[]`) |
| `POST` | `/api/agents/:name/spawn` | Spawn an agent process |
| `POST` | `/api/agents/:name/kill` | Kill an agent process |
| `POST` | `/api/task/approve/:requestId` | Approve a tool call |
| `POST` | `/api/task` | Post a task to master |

---

## 6. Optimistic UI — Handling Stale Data & Connection Loss

### 6.1 Stale Data Detection

Mark data as stale if:
- The last successful poll was more than `2 × polling_interval` ago
- The `updated_at` field in STATUS.json hasn't changed in more than 5 minutes for a "running" agent

**Visual treatment for stale data:**
- Add a `⚠ Stale` badge next to the timestamp: `2m ago ⚠`
- Dim the entire row to 60% opacity
- Show tooltip: "Data may be outdated — last refresh failed"

### 6.2 Connection Loss

**Detection:** Three consecutive failed poll requests.

**UI behavior:**
1. Footer connection status changes: `● Connected` → `● Reconnecting` (amber pulse)
2. After 3 failures: `● Disconnected` (red dot)
3. Banner appears at top of main content: `⚠ Connection lost — retrying in 8s`
4. All agent rows dim to 50% opacity
5. Status badges show a `?` overlay to indicate uncertainty

**Recovery:** On successful reconnect:
1. Banner dismisses with fade-out
2. Full data refresh triggered immediately
3. Footer returns to `● Connected`
4. Row opacity restores

### 6.3 Agent Not Responding

If an agent has `state: "running"` but `updated_at` is more than 10 minutes old:

- Add `⚠` icon next to the status badge
- Tooltip: "Agent has not updated its status in 10+ minutes"
- Health status automatically degrades to `"warning"` in the UI (client-side override, not from file)

### 6.4 Optimistic Spawn/Kill

When the user clicks "Spawn Agent" or "Kill Agent":
1. Immediately update the UI optimistically (show `● RUNNING` or `○ IDLE`)
2. Send the API request
3. On success: next poll will confirm the real state
4. On failure: revert the optimistic update and show an error toast

---

## 7. Event Log — Live Scrolling Feed

The event log appears in the sidebar and shows a real-time stream of agent activity.

### 7.1 Display Format

```
┌─────────────────────────────────────────────────┐
│  EVENT LOG                              [Clear]  │
│  ─────────────────────────────────────────────  │
│  13:04 ● builder    task completed              │
│  13:03 ● planning   task assigned               │
│  13:02 ⚠ cron       health warning              │
│  13:01 ● keeper     went idle                   │
│  13:00 ● doctor     spawned                     │
│  12:59 ✗ cron       health error (resolved)     │
│  12:58 ● master     task assigned               │
│  ...                                            │
└─────────────────────────────────────────────────┘
```

### 7.2 Event Log Behavior

- **Max entries displayed:** 50 (older entries scroll off)
- **New entries:** Appear at the top with a brief highlight animation (200ms fade from `surface-hover` to transparent)
- **Scroll behavior:** Auto-scroll to top when new events arrive, unless the user has manually scrolled down (in which case, show a "↑ New events" badge)
- **Filtering:** Clicking an agent name in the event log filters the main table to that agent
- **Persistence:** Event log is in-memory only; clears on page refresh

### 7.3 Event Log Entry Component

```typescript
interface EventLogEntryProps {
  event: AgentEvent;
  onClick?: (agentName: string) => void;
}
```

**Rendering:**
- Timestamp: `HH:MM` format (hover for full ISO timestamp)
- Agent name: colored dot matching agent's current status color
- Message: truncated to 35 chars with tooltip for full text
- Level icon: `●` (info), `⚠` (warning), `✗` (error)

### 7.4 Fallback: Polling-Based Event Log

If SSE is not available (e.g., proxy strips `text/event-stream`), fall back to polling `/api/agents` every 2s and diffing the results to synthesize events:

```typescript
function diffAgentStates(prev: AgentStatus[], next: AgentStatus[]): AgentEvent[] {
  const events: AgentEvent[] = [];
  for (const nextAgent of next) {
    const prevAgent = prev.find(a => a.name === nextAgent.name);
    if (!prevAgent) continue;
    if (prevAgent.state !== nextAgent.state) {
      events.push({
        id: crypto.randomUUID(),
        timestamp: new Date().toISOString(),
        agent_name: nextAgent.name,
        event_type: 'status_changed',
        message: `${nextAgent.name}: ${prevAgent.state} → ${nextAgent.state}`,
        level: nextAgent.state === 'error' ? 'error' : 'info',
      });
    }
  }
  return events;
}
```
