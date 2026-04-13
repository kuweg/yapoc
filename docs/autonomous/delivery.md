# Result Delivery

How results get back to the user. Two layers: task events (coarse, for Dashboard)
and turn events (fine-grained, for Chat). Both over the same WebSocket.

---

## The delivery chain

```
Agent emits turn events (stdout JSON lines)
           │
           ├── written to session event log (always)
           │
           └── if subscriber on this session:
               pushed via WebSocket → Chat tab renders live
                        │
Agent calls notify_parent("user")
           │
           ▼
  Notification listener
           │
           ▼
  Task Store updated: status=done, result=...
           │
           ├── WebSocket push → task_complete event → all connected clients
           │       │
           │       ├── Dashboard: kanban card → Done
           │       ├── Agents tab: master → idle
           │       └── Chat tab: final response message
           │
           └── Channel reply (if applicable)
                   │
                   ├── Telegram: send result to source_chat_id
                   └── Webhook: POST callback_url with result
```

---

## WebSocket event protocol

### Connection lifecycle

```
Client connects to GET /ws
  → Backend accepts
  → Backend sends state_sync: { tasks: [...recent...], agents: [...statuses...] }
  → Client is now receiving task-level events

Client sends: { type: "subscribe", session_id: "abc" }
  → Client now also receives turn-level events for session "abc"
  → Backend sends session history: recent events from session log

Client sends: { type: "unsubscribe", session_id: "abc" }
  → Stops receiving turn-level events for that session

Client disconnects
  → Removed from client registry
  → No effect on task execution
```

### Task-level events (all clients receive these)

| Event | When | Payload |
|---|---|---|
| `state_sync` | On connect | `{ tasks: [...], agents: [...] }` |
| `task_created` | New task in store | `{ task_id, prompt, status, source }` |
| `task_update` | Status change | `{ task_id, status, reason? }` |
| `task_complete` | Agent done | `{ task_id, result, duration_seconds }` |
| `task_error` | Agent failed | `{ task_id, error }` |
| `task_paused` | Waiting for approval | `{ task_id, approval_id, tool, input }` |
| `agent_status` | Agent state change | `{ agent_name, status, current_task }` |
| `health_event` | Doctor finding | `{ agent_name, severity, message }` |
| `approval_resolved` | Queued approval handled | `{ approval_id, decision }` |

### Turn-level events (only subscribed clients)

| Event | When | Payload |
|---|---|---|
| `session_history` | On subscribe | `{ session_id, events: [...recent...] }` |
| `turn_start` | Agent begins turn | `{ session_id, agent, turn }` |
| `thinking_delta` | Streaming thinking | `{ session_id, turn, text }` |
| `thinking_done` | Thinking complete | `{ session_id, turn }` |
| `tool_call` | Tool invoked | `{ session_id, turn, tool, input }` |
| `tool_result` | Tool returned | `{ session_id, turn, tool, output, duration_ms }` |
| `message_delta` | Streaming response | `{ session_id, turn, text }` |
| `message_done` | Response complete | `{ session_id, turn }` |
| `approval_needed` | CONFIRM tool prompt | `{ session_id, turn, tool, input, request_id }` |
| `cost_update` | Turn usage | `{ session_id, turn, tokens_in, tokens_out, cost }` |
| `agent_delegated` | Spawned sub-agent | `{ session_id, parent, child, task_summary }` |

---

## State sync on reconnect

The UI can always reconstruct full state from two sources:

1. **Task state:** `GET /api/tasks?limit=50` — all recent tasks with status + result
2. **Session state:** `GET /api/sessions/{id}/events?limit=100` — recent turn events

On page load:
1. Fetch tasks → populate Dashboard + session list
2. On Chat tab: select session → fetch session events → render conversation
3. Establish WebSocket → receive deltas from here forward

Even if events were missed during disconnection, the UI is correct after sync.

---

## Channel reply

### Telegram

When `source == "telegram"`:

```python
if task.source == "telegram" and task.source_chat_id:
    result_text = task.result
    if len(result_text) > 4000:
        result_text = result_text[:3900] + "\n\n... [full result in Mission Control]"
    await telegram_client.send_message(
        chat_id=task.source_chat_id,
        text=result_text
    )
```

For long-running tasks: send interim updates every 5 minutes:
"Still working... (Planning phase complete, Builder executing)"

### Webhook callback

When `source == "webhook"` and `callback_url` is set:

```python
if task.source == "webhook" and task.callback_url:
    await httpx.post(task.callback_url, json={
        "task_id": task.id,
        "status": task.status,
        "result": task.result
    })
```

### Approval via Telegram

Queued approvals can be resolved from Telegram:

```
Bot: "Builder wants to run: poetry add pyjwt [approval_id: abc123]"
     "Reply /approve abc123 or /deny abc123"

User: /approve abc123

Bot → POST /approval { id: "abc123", decision: "approved" }
→ agent receives approval → continues execution
→ bot: "Approved. Builder continuing."
```

---

## When no one is listening

Results persist in the task store. They never vanish.

When the user opens Mission Control later:
1. `GET /api/tasks` → completed tasks show results
2. Dashboard shows cards in Done column
3. Select a task → open in Chat view → full execution history loads from session log

The system does not need anyone listening to complete work.
**The result waits for the user, not the other way around.**

---

## Notification listener

The component that reads `notify_parent("user")` and closes the loop.

```python
# app/backend/notification_listener.py

async def notification_listener_loop():
    while True:
        try:
            notifications = notification_queue.consume_for_user()
            for notification in notifications:
                task_id = notification.get("task_id")
                result = notification.get("result")
                error = notification.get("error")

                if task_id:
                    status = "error" if error else "done"
                    await task_store.update(task_id, status=status,
                                           result=result, error=error)

                    event = "task_error" if error else "task_complete"
                    await push_event(event, {
                        "task_id": task_id,
                        "result": result,
                        "error": error
                    })

                    # Channel reply
                    task = await task_store.get(task_id)
                    await deliver_to_source(task)

        except Exception as e:
            log.error(f"Notification listener error: {e}")
        await asyncio.sleep(0.5)
```

This loop starts alongside the dispatcher on app startup.
