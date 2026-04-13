# Streaming — Real-Time Agent Observation

The Claude Code experience: you watch the agent think.
Not just "task started... task done." You see every reasoning step,
every tool call, every intermediate result as it happens.

This is what separates a control panel from a conversation.

---

## Why this matters

Fire-and-forget is one mode. But when you're present, you want the Claude Code
experience: thinking blocks appearing, tool calls streaming, reasoning visible.
Trust comes from seeing the work happen, not just the result.

The UI already has the components: `ThinkingBlock.tsx`, `ToolCallBlock.tsx`,
`MessageBubble.tsx`, `AgentLogDrawer.tsx`. They need a protocol to feed them.

---

## Two event layers

YAPOC needs two distinct event streams over the same WebSocket:

### Task-level events (Dashboard, Agents tab)

Coarse state transitions. Updated every few seconds or on state change.

```
task_created   → new card in kanban
task_update    → card moves between columns
task_complete  → card in Done + result stored
task_error     → card in Error + error visible
agent_status   → agent card shows running/idle/error
health_event   → health indicator changes
```

These are sufficient for the Dashboard and Agents tab.
They work regardless of whether the user is watching.

### Turn-level events (Chat tab)

Fine-grained streaming during active execution. Updated in real-time.
These only flow when a WebSocket client is subscribed to a specific session.

```
turn_start       → agent begins a new reasoning turn
thinking_delta   → streaming thinking text (partial)
thinking_done    → thinking block complete
tool_call        → agent invoked a tool (name, input)
tool_result      → tool returned (output, duration)
message_delta    → streaming response text (partial)
message_done     → response complete
approval_needed  → CONFIRM-tier tool waiting for user decision
cost_update      → token usage for this turn
```

### Subscription model

```
Client connects to WebSocket
  → receives task-level events automatically (always)
  → sends: { type: "subscribe", session_id: "abc" }
  → now also receives turn-level events for that session
  → sends: { type: "unsubscribe", session_id: "abc" }
  → stops receiving turn-level events
```

The Chat tab subscribes when the user is viewing a session.
The Dashboard never subscribes — it only needs task-level events.

---

## How turn events flow from agents to UI

```
Agent (subprocess)
    │
    │  LLM streams response
    │
    ▼
BaseAgent._stream_turn()
    │
    │  writes to session event log (append-only file or pipe)
    │
    ▼
Backend event relay (reads from agent output)
    │
    │  formats as WebSocket event
    │
    ▼
WebSocket push to subscribed clients
    │
    ▼
Chat tab renders:
  ThinkingBlock ← thinking_delta events
  ToolCallBlock ← tool_call + tool_result events
  MessageBubble ← message_delta events
  ApprovalDialog ← approval_needed events
```

### Agent-side changes

The agent subprocess needs to emit structured events to a channel the backend can read.
Options:

1. **Stdout protocol** — agent writes JSON lines to stdout, backend reads them.
   Simple, works with existing subprocess model.

2. **Unix socket** — agent opens a domain socket, backend connects.
   Better isolation, but more plumbing.

3. **Shared file** — agent appends to `data/sessions/{session_id}/events.jsonl`,
   backend watches with inotify/polling.
   Works with existing file-based architecture.

**Recommendation:** Option 1 (stdout JSON lines) for MVP. It's what Claude Code does
internally. The runner already captures agent output — augment it with structured events.

### Event format

```json
{"type": "thinking_delta", "session_id": "abc", "turn": 3, "text": "I need to check if the file exists..."}
{"type": "tool_call", "session_id": "abc", "turn": 3, "tool": "file_read", "input": {"path": "/app/auth.py"}}
{"type": "tool_result", "session_id": "abc", "turn": 3, "tool": "file_read", "output": "...", "duration_ms": 45}
{"type": "message_delta", "session_id": "abc", "turn": 3, "text": "The auth module has three endpoints..."}
{"type": "approval_needed", "session_id": "abc", "turn": 3, "tool": "shell_exec", "input": {"command": "pytest"}, "request_id": "req_123"}
```

---

## Interactive approval over WebSocket

When a CONFIRM-tier tool needs approval and the user is watching:

```
Agent → approval_needed event → WebSocket → Chat tab → ApprovalDialog

User clicks Approve:
  → Client sends: { type: "approval_response", request_id: "req_123", approved: true }
  → Backend relays to agent subprocess (via stdin or signal file)
  → Agent continues execution

User clicks Deny:
  → Client sends: { type: "approval_response", request_id: "req_123", approved: false }
  → Agent receives denial, adjusts approach

Timeout (user not present, 30 seconds):
  → see safety.md for autonomous approval policy
```

This is the Claude Code permission model, adapted for WebSocket.

---

## When no one is watching

If no client is subscribed to the session, turn-level events are still written
to the session event log. They are not pushed over WebSocket (no one to push to).

When the user opens the Chat tab and selects the session later:
1. Client sends `subscribe` with session_id
2. Backend sends recent event history (last N events from the log)
3. Client renders the full conversation up to this point
4. Live events stream from this point forward

The user can "rewind" and see what happened while they were away.
This is the playback feature — like opening a Claude Code session transcript.

---

## Performance constraints

- Thinking deltas should be batched (every 100ms, not every character)
- Tool results over 10KB should be truncated in the event, full result in session log
- Turn-level events are ephemeral — they live in the session log, not in the task store
- Task-level events are persistent — they live in the task store (SQLite)
- WebSocket backpressure: if a client falls behind, skip thinking deltas (keep tool_call and message events)
