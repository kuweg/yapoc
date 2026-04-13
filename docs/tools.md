# Agent Tools

Every agent interacts with the system through a defined set of **tools**. Tools are Python callables registered in `app/utils/tools/__init__.py`. An agent's LLM output can request tool calls; the runner executes them and feeds results back into the conversation.

---

## Tool Interface

```python
class BaseTool(ABC):
    name: str
    description: str
    input_schema: dict[str, Any]
    risk_tier: RiskTier = RiskTier.AUTO  # AUTO (safe) or CONFIRM (needs approval)

    async def execute(self, **params) -> str:
        """Run the tool and return a text result."""
        ...
```

All tools live in `app/utils/tools/` and are registered per-agent by the runner based on the agent's `CONFIG.md`.

---

## Tool Registry (20 tools)

```python
TOOL_REGISTRY = {
    # Server / Process
    "server_restart": ServerRestartTool,       # Restart uvicorn backend
    "process_restart": ProcessRestartTool,     # Restart CLI process

    # Shell
    "shell_exec": ShellExecTool,               # Execute shell command

    # File operations
    "file_read": FileReadTool,                 # Read a file
    "file_write": FileWriteTool,               # Create/overwrite a file (CONFIRM)
    "file_edit": FileEditTool,                 # Surgical string replacement (CONFIRM)
    "file_delete": FileDeleteTool,             # Delete a file (CONFIRM)
    "file_list": FileListTool,                 # List directory contents

    # Memory (scoped to agent_dir)
    "memory_append": MemoryAppendTool,         # Append to MEMORY.MD
    "notes_read": NotesReadTool,               # Read NOTES.MD
    "notes_write": NotesWriteTool,             # Replace NOTES.MD content
    "health_log": HealthLogTool,               # Append to HEALTH.MD

    # Web
    "web_search": WebSearchTool,               # Search the web

    # Delegation
    "spawn_agent": SpawnAgentTool,             # Start agent subprocess with task
    "ping_agent": PingAgentTool,               # Check agent liveness (PID + status)
    "kill_agent": KillAgentTool,               # Send SIGTERM to agent
    "check_task_status": CheckTaskStatusTool,  # Read TASK.MD status field
    "read_task_result": ReadTaskResultTool,    # Read TASK.MD Result section
    "read_agent_logs": ReadAgentLogsTool,      # Read agent's OUTPUT.MD

    # Agent management
    "create_agent": CreateAgentTool,           # Create new agent directory (CONFIRM)
    "delete_agent": DeleteAgentTool,           # Remove agent directory (CONFIRM)
}
```

---

## Tool Details

### Server Tools (`app/utils/tools/server.py`)

| Tool | Risk | Description | Parameters |
|------|------|-------------|------------|
| `server_restart` | CONFIRM | Restart the YAPOC backend server (uvicorn) | _(none)_ |
| `process_restart` | CONFIRM | Restart the CLI process (reload code/imports) | _(none)_ |

### Shell Tool (`app/utils/tools/shell.py`)

| Tool | Risk | Description | Parameters |
|------|------|-------------|------------|
| `shell_exec` | CONFIRM | Execute a shell command | `command: str, timeout: int = 30` |

### File Tools (`app/utils/tools/file.py`)

| Tool | Risk | Description | Parameters |
|------|------|-------------|------------|
| `file_read` | AUTO | Read a file relative to project root | `path: str` |
| `file_write` | CONFIRM | Write/overwrite a file (atomic write, sandbox check) | `path: str, content: str, create_dirs: bool = true` |
| `file_edit` | CONFIRM | Replace a unique string in a file | `path: str, old_string: str, new_string: str, replace_all: bool = false` |
| `file_delete` | CONFIRM | Delete a file (sandbox check, refuses base agent dirs) | `path: str` |
| `file_list` | AUTO | List files in a directory | `path: str` |

### Memory Tools (`app/utils/tools/memory.py`)

| Tool | Risk | Description | Parameters |
|------|------|-------------|------------|
| `memory_append` | AUTO | Append timestamped entry to own MEMORY.MD | `entry: str` |
| `notes_read` | AUTO | Read own NOTES.MD | _(none)_ |
| `notes_write` | AUTO | Replace own NOTES.MD content | `content: str` |
| `health_log` | AUTO | Append error entry to own HEALTH.MD | `error: str` |

Memory tools receive `agent_dir` at construction time and are scoped to the owning agent's directory.

### Web Tool (`app/utils/tools/web.py`)

| Tool | Risk | Description | Parameters |
|------|------|-------------|------------|
| `web_search` | AUTO | Search the web for information | `query: str` |

### Delegation Tools (`app/utils/tools/delegation.py`)

| Tool | Risk | Description | Parameters |
|------|------|-------------|------------|
| `spawn_agent` | AUTO | Start an agent subprocess with a task | `agent_name: str, task: str, context: str = ""` |
| `ping_agent` | AUTO | Check agent liveness (PID + STATUS.json) | `agent_name: str` |
| `kill_agent` | AUTO | Send SIGTERM to an agent process | `agent_name: str` |
| `check_task_status` | AUTO | Read TASK.MD status field | `agent_name: str` |
| `read_task_result` | AUTO | Read the Result section from TASK.MD | `agent_name: str` |

### Agent Log Tool (`app/utils/tools/logs.py`)

| Tool | Risk | Description | Parameters |
|------|------|-------------|------------|
| `read_agent_logs` | AUTO | Read an agent's OUTPUT.MD | `agent_name: str` |

### Agent Management Tools (`app/utils/tools/agent_mgmt.py`)

| Tool | Risk | Description | Parameters |
|------|------|-------------|------------|
| `create_agent` | CONFIRM | Create a new agent directory with full scaffold | `name: str, prompt: str, model: str = "claude-sonnet-4-6", adapter: str = "anthropic", tools: list[str]` |
| `delete_agent` | CONFIRM | Remove a non-base agent directory | `name: str` |

**`create_agent` details:**
- Validates name: `^[a-z][a-z0-9_-]+$`
- Refuses protected names: master, planning, builder, keeper, cron, doctor, base
- Refuses if directory already exists
- Creates: PROMPT.MD, CONFIG.md, agent.py, `__init__.py`, TASK.MD, MEMORY.MD, NOTES.MD, HEALTH.MD

**`delete_agent` details:**
- Refuses protected agent names
- Checks STATUS.json — refuses if agent is running
- Uses `shutil.rmtree()` to remove directory

---

## Tool Assignment per Agent

| Agent | Tools |
|-------|-------|
| **Master** | `server_restart`, `process_restart`, `shell_exec`, `file_read`, `file_write`, `file_edit`, `file_delete`, `file_list`, `web_search`, `memory_append`, `notes_read`, `notes_write`, `health_log`, `spawn_agent`, `ping_agent`, `kill_agent`, `check_task_status`, `read_task_result`, `read_agent_logs`, `create_agent`, `delete_agent` |
| **Planning** | `spawn_agent`, `ping_agent`, `kill_agent`, `check_task_status`, `read_task_result`, `file_read`, `file_list`, `memory_append`, `notes_read`, `notes_write`, `health_log` |
| **Builder** | `file_read`, `file_write`, `file_edit`, `file_delete`, `file_list`, `shell_exec`, `create_agent`, `delete_agent`, `memory_append`, `notes_read`, `notes_write`, `health_log` |
| **Doctor** | `file_read`, `file_list`, `read_agent_logs`, `memory_append`, `notes_read`, `notes_write`, `health_log` |
| **Keeper** | _(stub — not yet assigned)_ |
| **Cron** | _(stub — not yet assigned)_ |

---

## Adding a New Tool

1. Create a class in `app/utils/tools/` (new file or existing)
2. Subclass `BaseTool`, set `name`, `description`, `input_schema` class attributes, implement `execute`
3. Set `risk_tier` to `RiskTier.AUTO` (safe) or `RiskTier.CONFIRM` (needs approval)
4. Register in `app/utils/tools/__init__.py` `TOOL_REGISTRY`
5. If the tool needs `agent_dir`, add its name to `_AGENT_DIR_TOOLS`
6. Assign to agents in their `CONFIG.md` under `tools:` list

---

## Security

- `shell_exec` runs with a timeout to prevent hanging.
- `server_restart` writes resume state before destructive action.
- Memory tools are scoped to the owning agent's directory.
- File tools use sandbox checks (no `..` escapes, stays within project root).
- File writes use atomic write (write to temp file + rename).
- `create_agent` / `delete_agent` refuse protected agent names.
- Tool calls are logged to the agent's MEMORY.MD for audit.
