# app/utils/tools — Tool System

## Registry
`TOOL_REGISTRY: dict[str, type[BaseTool]]` in `__init__.py`. 40 tools total.

**Always use `build_tools(names, agent_dir)` — never instantiate tools directly.** Some tools require `agent_dir` at construction:
```python
_AGENT_DIR_TOOLS = {"memory_append", "notes_read", "notes_write", "notes_append", "health_log", "update_config"}
```

## Execution model
All tools execute immediately. There is no approval gate, no risk-tier system, and no per-agent `autonomous_policy` block — the LLM is solely responsible for not invoking destructive tools without good reason. Sandboxing (`sandbox.forbidden`, `sandbox.shell_allowlist` in CONFIG.yaml) is the remaining safety boundary.

## Full tool list by file

| File | Tools |
|---|---|
| `server.py` | `server_restart`, `process_restart` |
| `shell.py` | `shell_exec` |
| `file.py` | `file_read`, `file_write`, `file_edit`, `file_delete`, `file_list` |
| `memory.py` | `memory_append`, `notes_read`, `notes_write`, `notes_append`, `health_log` |
| `web.py` | `web_search` |
| `delegation.py` | `spawn_agent`, `ping_agent`, `kill_agent`, `check_task_status`, `read_task_result`, `wait_for_agent`, `wait_for_agents`, `read_agent_logs` |
| `agent_mgmt.py` | `create_agent`, `delete_agent` |
| `model_manager.py` | `check_model_availability`, `list_models`, `update_agent_config` |
| `memory.py` | `update_config` |

## Key tool behaviors

### `shell_exec`
Runs in `/bin/sh -c` with `start_new_session=True`. Timeout hard-capped at `settings.max_shell_timeout` (120s); kills entire process group on timeout. Output truncated at 10,000 chars. Optional `sandbox.shell_allowlist` in the agent's CONFIG.yaml restricts commands by binary name.

### `file_edit`
`old_string` must appear **exactly once** in the file. Atomic write via `mkstemp + os.replace`.

### `file_delete` — protected names
Refuses to delete: `.env`, `.git`, `.gitignore`, `PROMPT.MD`, `TASK.MD`, `MEMORY.MD`, `NOTES.MD`, `HEALTH.MD`, `CONFIG.yaml`.

### `file_read`
Truncates output at 8,000 chars. All file tools enforce sandbox via `_sandbox(path)` — resolves to absolute path and checks it's inside `project_root`.

### `spawn_agent`
Writes structured TASK.MD frontmatter (`assigned_by: master`, `status: pending`), then either assigns to a running agent (watchdog picks up) or spawns subprocess. Polls STATUS.json for `agent_spawn_timeout` seconds.

### `wait_for_agent`
Polls TASK.MD every `poll_interval` seconds (default 15) up to `timeout` (default 300). Returns full `## Result` or `## Error` content. **Side effect**: if agent has `lifecycle.temporary: true`, auto-deletes the agent directory after reading result.

### `wait_for_agents`
Polls multiple agents' TASK.MD simultaneously via `asyncio.gather`. Parameters: `agent_names: list[str]`, `timeout: int = 300`, `poll_interval: int = 10`, `fail_fast: bool = True`. Returns a structured per-agent summary (status + result/error). If `fail_fast=true` (default), returns early the moment any agent reports `error`, marking remaining agents as `interrupted`. Temporary agents are auto-cleaned on `done` just like `wait_for_agent`.

### `create_agent`
Protected agent names: `master, planning, builder, keeper, cron, doctor, base, model_manager`. Name must match `^[a-z][a-z0-9_-]+$`. Creates all 8 agent files including `agent.py` and `__init__.py`.

### `delete_agent`
Refuses if agent STATUS.json shows `running` or `idle` — suggests `kill_agent` first.

## Adding a new tool
1. Create class in appropriate `tools/*.py` implementing `BaseTool`
2. Add to `TOOL_REGISTRY` in `__init__.py`
3. If it needs `agent_dir` at construction, add name to `_AGENT_DIR_TOOLS`
4. Add tool name to relevant agents' `CONFIG.yaml` tools list
