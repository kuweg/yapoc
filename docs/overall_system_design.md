# YAPOC — Yet Another OpenClaw: System Design

## Overview

YAPOC is an autonomous multi-agent system where a hierarchy of specialized AI agents collaborate to plan, build, and self-manage tasks. Agents communicate through markdown files on disk, operate independently, and can modify the system itself — including creating new agents, editing configurations, and scheduling work.

**Goal (MVP):** Build a working Master Agent that can accept tasks, delegate to base agents, and complete the rest of the system.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Language | Python 3.12+ |
| Backend | FastAPI |
| LLM | Anthropic Claude (via `anthropic` SDK) |
| Task scheduling | APScheduler |
| File I/O | aiofiles (async) |
| File watching | watchdog |
| Logging | loguru |
| Config | python-dotenv |

---

## Architecture

### Communication Model

Agents are **file-isolated**: each agent lives in its own directory and communicates exclusively through its markdown files. Delegation between agents uses `spawn_agent` (starts a subprocess) + `check_task_status` / `read_task_result` (polls TASK.MD). The AgentRunner (`app/agents/base/runner.py`) manages subprocess lifecycle via watchdog-based TASK.MD watching and STATUS.json.

```
agents/
  master/
    PROMPT.MD          # Agent identity, role, constraints
    TASK.MD            # Current task from parent or user
    MEMORY.MD          # Short-term log of key events
    NOTES.MD           # Long-term knowledge (user info, patterns)
    HEALTH.MD          # Error log for self-improvement (includes tracebacks)
    CONFIG.md          # Agent configuration (adapter, model, tools, runner settings)
    SERVER_OUTPUT.MD   # Captured uvicorn stdout/stderr
    SERVER_CRASH.MD    # Server crash reports
  planning/
    PROMPT.MD, TASK.MD, MEMORY.MD, NOTES.MD, HEALTH.MD, CONFIG.md
    OUTPUT.MD          # Captured subprocess stdout/stderr
    CRASH.MD           # Crash reports (exit code, traceback)
  builder/
    ...
  keeper/
    ...
  cron/
    ...
  doctor/
    ...
    HEALTH_SUMMARY.MD  # Rolling system health report (doctor only)
```

### Agent Hierarchy

```
User
 └── Master Agent          ← only entry point for user interaction
      ├── Planning Agent   ← breaks tasks into steps, writes TASK.MD for others
      │    ├── Builder Agent   ← creates/edits/deletes non-base agents
      │    ├── Keeper Agent    ← edits project settings and config
      │    └── Cron Agent      ← schedules timed/recurring tasks
      └── Doctor Agent    ← runs on its own cron, monitors all HEALTH.MD files
```

### Agent Lifecycle

1. A task arrives at Master Agent (via API or CLI).
2. Master delegates to Planning Agent.
3. Planning Agent writes a structured plan to target agents' `TASK.MD`.
4. Target agents execute and write results/errors to `MEMORY.MD` / `HEALTH.MD` / `NOTES.MD`
5. Doctor Agent periodically reads all `HEALTH.MD` files and summarizes / resolves recurring errors.

---

## MVP Scope

For the MVP, the focus is on getting the **Master Agent** operational end-to-end:

### Implemented

- [x] Agent directory structure and file schema
- [x] Centralized settings (pydantic-settings)
- [x] LLM adapters: Anthropic, OpenAI, Ollama
- [x] BaseAgent class with async file I/O, config loading, streaming
- [x] Master Agent: accepts tasks via CLI and FastAPI endpoint
- [x] Multi-turn tool-use loop in BaseAgent
- [x] Tools: `server_restart`, `shell_exec`, `file_read`, `file_list`, memory tools
- [x] FastAPI backend with health, task, agent endpoints
- [x] Typer CLI with interactive shell, slash commands, model picker
- [x] Rich TUI with Live display, spinners, streaming

### In Progress / Planned

- [x] Planning Agent: task decomposer, delegates to Builder/Keeper/Cron via `spawn_agent`
- [x] Builder Agent: file creator/editor, agent scaffolder with `create_agent`/`delete_agent` tools
- [x] Delegation tools: `spawn_agent`, `ping_agent`, `kill_agent`, `check_task_status`, `read_task_result`, `read_agent_logs`
- [x] Agent management tools: `create_agent`, `delete_agent`
- [x] AgentRunner: watchdog-based TASK.MD watcher with STATUS.json lifecycle
- [x] Context assembly: `build_system_context()` reads PROMPT+MEMORY+NOTES+HEALTH into system prompt
- [x] File write/edit/delete tools with sandbox checks and atomic writes
- [x] Context auto-compaction (auto-compact at ~85% usage, `/compact` command)
- [x] Session persistence (JSONL-based, `/sessions`, `/resume`, `/continue`)
- [x] CLI polish: cost tracking, tab completion, `@` file mentions, `!` bash mode, `/diff`, `/copy`, `/export`
- [ ] Keeper Agent: config management
- [ ] Cron Agent: APScheduler-based timed task execution
- [x] Doctor Agent: scans HEALTH.MD, CRASH.MD, OUTPUT.MD on cron schedule, produces HEALTH_SUMMARY.MD

### Out of Scope (post-MVP)

- Frontend / UI
- Inter-agent streaming
- Fine-grained per-tool permission rules (glob patterns)
- Agent versioning / rollback
- Hooks system (PreToolUse, PostToolUse lifecycle events)
- Checkpoints + rewind
- MCP server integration
- Custom skills system

---

## API (MVP)

```
POST /task          — submit a task to Master Agent
GET  /agents        — list all active agents and their status
GET  /agents/{name}/memory   — read agent MEMORY.MD
GET  /agents/{name}/health   — read agent HEALTH.MD
POST /agents/{name}/restart  — restart an agent
```

---

## File Schema

### PROMPT.MD
Agent's static identity. Defines role, personality, capabilities, and constraints. Read-only at runtime.

### TASK.MD
Current task assigned to the agent. Written by Planning Agent (or user → Master).

**Required fields:**

```markdown
---
status: pending | running | done | error
assigned_by: <agent_name>
assigned_at: <ISO timestamp>
completed_at: <ISO timestamp or empty>
---

## Task
<task description>

## Context
<optional background or references>

## Result
<filled by the executing agent on completion>

## Error
<filled on status: error — what went wrong and why>
```

**Status transitions:**
- `pending` → set by the assigner when writing the task
- `running` → set by the executing agent when it picks up the task
- `done` → set by the executing agent after writing the Result section
- `error` → set by the executing agent if execution fails

The assigning agent polls `status` via `check_task_status` tool to know when work is complete.

### MEMORY.MD
Short log of completed actions, decisions, and outcomes. Append-only, summarized periodically.

### NOTES.MD
Persistent knowledge: user preferences, domain facts, recurring patterns. Manually or agent-curated.

### HEALTH.MD
Error log: what went wrong, when, and any known fix. Doctor Agent reads this to identify and resolve systemic issues.

### CONFIG.md
Per-agent configuration. Defines adapter, model, temperature, assigned tools, and runner settings. Read by the agent runner at startup. Edited by Keeper Agent or developer.

```yaml
adapter: anthropic
model: claude-sonnet-4-6
temperature: 0.3
tools:
  - server_restart
  - shell_exec
  - file_read
  - file_list
  - memory_append
  - notes_read
  - notes_write
  - health_log
runner:
  max_turns: 20
  task_timeout: 300
```

---

## Self-Modification

The system supports controlled self-modification:
- **Builder Agent** can create/edit/delete agent directories and their files
- **Keeper Agent** can modify system config (`pyproject.toml`, `.env`, settings files)
- **Master Agent** is the only authorized initiator — no agent self-modifies without a task chain originating from Master

`watchdog` monitors the `agents/` directory for unexpected changes outside of an active task.

---

## Concurrency

### Parallel Execution

Agents run as independent async coroutines within the FastAPI process. Multiple agents can execute simultaneously — for example, Planning can assign tasks to Builder and Keeper in parallel, and both will process their TASK.MD concurrently.

### File Safety

Each agent owns its own directory and files. Since agents only write to their own files (except Planning writing TASK.MD to others), there are no write conflicts under normal operation.

For the exception case (Planning writing to another agent's TASK.MD):
- Planning must check that the target agent's TASK.MD status is `done` or empty before writing a new task. Writing to an agent with `status: running` is rejected.
- File writes use atomic write (write to temp file + rename) to prevent partial reads.

### Task Queue

If an agent receives a new task while already running one, the new task is **queued** in memory by the runner. The agent processes tasks sequentially — one at a time. The queue is bounded (default: 10). Overflow tasks are rejected with an error returned to the caller.
