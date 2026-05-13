# app/utils/tools — Tool System

## Registry
`TOOL_REGISTRY: dict[str, type[BaseTool]]` in `__init__.py`. 40 tools total.

**Always use `build_tools(names, agent_dir)` — never instantiate tools directly.** Some tools require `agent_dir` at construction:
```python
_AGENT_DIR_TOOLS = {"memory_append", "notes_read", "notes_write", "notes_append", "health_log", "update_config"}
```

## Risk tiers
```python
class RiskTier(Enum):
    AUTO    # executes without confirmation
    CONFIRM # routes through the approval system (see below)
```

Override `get_risk_tier(params) -> RiskTier` for dynamic tiers (e.g., `CreateAgentTool` returns `AUTO` for temporary agents).

### Approval flow (CONFIRM-tier tools)
1. **CLI / `/task/stream`**: an interactive `approval_gate` blocks until the user clicks Approve/Deny in the UI or replies y/n at the REPL.
2. **Autonomous (subprocess agents)**: no gate, so the per-agent `autonomous_policy:<tool>` block in `CONFIG.md` decides:
   - `auto_approve` pattern match → execute immediately
   - `deny` pattern match → block with a denial message
   - `queue` (or fall-through default) → write a row to the `approval_queue` SQLite table, push an `approval_needed` WebSocket event, and **block** waiting for the user's decision. The wait timeout is `settings.approval_wait_timeout_seconds` (default 300s). On approve → execute. On deny → block. On timeout → block with a timeout message (the LLM is free to try a different approach).
3. **UI surface**: `BackgroundApprovalBanner` shows pending approvals. It listens to the `approval_needed` WebSocket event AND polls `/approvals` every 3s as a fallback (the subprocess's WS push from `queue_approval()` is a no-op because subprocesses don't hold WS connections).

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

### `shell_exec` — `RiskTier.CONFIRM`
Runs in `/bin/sh -c` with `start_new_session=True`. Timeout hard-capped at `settings.max_shell_timeout` (120s); kills entire process group on timeout. Output truncated at 10,000 chars. In the CLI, the interactive approval gate prompts before each run. In autonomous (subprocess / HTTP) execution, the agent's `autonomous_policy.shell_exec` block in CONFIG.md decides via `auto_approve` / `deny` / `queue` patterns. Optional `sandbox.shell_allowlist` further restricts commands by binary name.

### `file_edit`
`old_string` must appear **exactly once** in the file. Atomic write via `mkstemp + os.replace`.

### `file_delete` — protected names
Refuses to delete: `.env`, `.git`, `.gitignore`, `PROMPT.MD`, `TASK.MD`, `MEMORY.MD`, `NOTES.MD`, `HEALTH.MD`, `CONFIG.md`.

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
4. Add tool name to relevant agents' `CONFIG.md` tools list
