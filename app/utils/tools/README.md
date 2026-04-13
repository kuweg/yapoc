# YAPOC Agent Tools

This directory contains Python tool modules that agents can import to interact
with the YAPOC system programmatically.  Each tool is a standalone module with
no circular imports — they communicate with the backend via HTTP or by reading
files directly.

---

## ticket_tool.py

Programmatic ticket manipulation via the backend REST API.

### Overview

`TicketTool` provides a synchronous HTTP client for reading and mutating tickets
in the YAPOC dashboard.  It is intended for use by the Master agent and any
other agent that needs to update ticket state as part of its workflow.

### Quick start

```python
from app.utils.tools.ticket_tool import TicketTool, TicketToolError

tool = TicketTool(base_url="http://localhost:8000", agent_name="master")

# Read a ticket
ticket = tool.get_ticket("abc-123")

# Update status
tool.mark_done("abc-123")
tool.mark_in_progress("abc-123")
tool.update_status("abc-123", "blocked")

# Add a note
tool.add_note("abc-123", "Completed the refactor — all tests pass.")

# Update priority
tool.update_priority("abc-123", "high")

# Reassign
tool.update_assignee("abc-123", "builder")
```

### Constructor

```python
TicketTool(
    base_url: str = "http://localhost:8000",
    agent_name: str = "",
    timeout: float = 10.0,
)
```

| Parameter    | Description |
|--------------|-------------|
| `base_url`   | Base URL of the YAPOC backend. |
| `agent_name` | Name of the calling agent.  Used as the `author` in notes and for the permission check. |
| `timeout`    | HTTP request timeout in seconds. |

### Methods

| Method | Description |
|--------|-------------|
| `get_ticket(ticket_id)` | Fetch the current state of a ticket. Returns the raw ticket dict. |
| `mark_done(ticket_id, *, force=False)` | Mark a ticket as `done`. |
| `mark_in_progress(ticket_id, *, force=False)` | Mark a ticket as `in_progress`. |
| `update_status(ticket_id, status, *, force=False)` | Set status to `pending`, `in_progress`, `done`, or `blocked`. |
| `add_note(ticket_id, note, *, force=False)` | Append a note to the ticket's activity log. |
| `update_priority(ticket_id, priority, *, force=False)` | Set priority to `low`, `medium`, `high`, or `critical`. |
| `update_assignee(ticket_id, assignee, *, force=False)` | Reassign the ticket to a different agent. |

All mutating methods return:

```python
{
    "success": True,
    "ticket_id": str,
    "message": str,       # human-readable summary
    "data": dict | None,  # updated ticket object from the backend
}
```

### Permission model

By default, an agent may only modify tickets where `assigned_agent` matches
`agent_name` OR `assigned_agent` is `None`/empty.  This prevents agents from
accidentally modifying each other's tickets.

Pass `force=True` to bypass the check:

```python
tool.mark_done("abc-123", force=True)  # Master can close any ticket
```

### Error handling

All methods raise `TicketToolError` on failure:

```python
from app.utils.tools.ticket_tool import TicketTool, TicketToolError

tool = TicketTool(agent_name="builder")
try:
    tool.mark_done("nonexistent-id")
except TicketToolError as e:
    print(f"Failed: {e} (HTTP {e.status_code})")
```

`TicketToolError` attributes:
- `status_code: int | None` — HTTP status code (404, 422, 403, …)
- `ticket_id: str | None` — the ticket ID that caused the error

---

## Other tools

| Module | Description |
|--------|-------------|
| `agent_mgmt.py` | Create and delete dynamic agents. |
| `agent_settings_tool.py` | Read and heal agent model settings. |
| `config_update.py` | Update agent CONFIG.md settings. |
| `delegation.py` | Spawn, wait for, ping, and kill sub-agents. |
| `file.py` | Read, write, edit, delete, and list files. |
| `logs.py` | Read agent subprocess logs. |
| `memory.py` | Append to MEMORY.MD, read/write NOTES.MD, log to HEALTH.MD. |
| `model_manager.py` | Check model availability and update agent configs. |
| `search.py` | Semantic search over agent memory. |
| `server.py` | Restart the backend server or CLI process. |
| `shell.py` | Execute shell commands with sandbox enforcement. |
| `web.py` | Web search via DuckDuckGo. |
