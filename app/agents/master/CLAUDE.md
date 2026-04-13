# app/agents/master — Master Agent

The entry point for all user interactions. CLI and HTTP API both talk exclusively to this agent.

## Singleton
```python
from app.agents.master.agent import master_agent
```
Imported by `app/backend/routers/tasks.py` and `app/cli/main.py`.

## Key methods
```python
handle_task(task, history) -> str                                        # blocking
handle_task_stream(task, history, approval_gate) -> AsyncIterator[StreamEvent]  # streaming
```
Both write TASK.MD then call through to `BaseAgent.run_stream_with_tools`.

## Tool set (18 tools)
Reads, delegation, memory, web, and direct server/process restart tools.
File mutations must still go through a sub-agent, but reads and restarts are done directly.

Tools:
- **Reads**: `file_read`, `file_list`, `show_agent_settings`
- **Delegation**: `spawn_agent`, `ping_agent`, `kill_agent`, `wait_for_agent`, `wait_for_agents`, `check_task_status`, `read_task_result`, `read_agent_logs`
- **Restarts**: `server_restart`, `process_restart`
- **Utility**: `web_search`, `memory_append`, `notes_read`, `notes_write`, `health_log`

## CONFIG.md
```yaml
adapter: anthropic
model: claude-sonnet-4-6
temperature: 0.3
max_turns: 20
task_timeout: 300
```

## How history flows
`handle_task_stream(task, history, approval_gate)`:
1. Writes `task` to TASK.MD
2. Calls `run_stream_with_tools(history, ...)` where `history` already has the user message as last entry
3. `run_stream_with_tools` detects non-empty history → uses it directly, doesn't re-read TASK.MD as user message

## Gotchas
- Config is reloaded on every turn (not cached) — editing CONFIG.md takes effect immediately on the next turn
- The singleton is shared across all concurrent requests; it is not thread-safe for parallel `/task` calls
