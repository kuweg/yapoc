# Agent Process Execution System

## Overview

Sub-agents (planning, builder, keeper, cron, doctor) run as **separate OS processes**, each managed by an `AgentRunner`. The Master Agent remains in-process with the CLI. This design isolates agent failures, enables parallel execution, and supports idle auto-termination.

## Architecture

```
CLI shell (interactive)
  └── MasterAgent (in-process)
        ├── spawn_agent("planning", task="...")
        │     └── subprocess: python -m app.agents.base.runner_entry --agent planning
        │           ├── STATUS.json {state: spawning → idle → running → idle → terminated}
        │           ├── watches TASK.MD for status: pending
        │           ├── runs BaseAgent.run_stream_with_tools()
        │           └── idle timeout → self-terminates
        ├── ping_agent("planning") → reads STATUS.json
        └── kill_agent("planning") → SIGTERM via PID from STATUS.json
```

## STATUS.json

Each agent process maintains a `STATUS.json` file in its agent directory. Written atomically (tmp file + rename) by the runner process.

```json
{
  "state": "running",
  "pid": 12345,
  "task_summary": "Decomposing user request into subtasks",
  "started_at": "2026-03-13T10:00:00Z",
  "updated_at": "2026-03-13T10:01:23Z",
  "idle_since": null
}
```

### States

| State | Meaning |
|-------|---------|
| `spawning` | Process started, initializing |
| `idle` | Waiting for a task (watching TASK.MD) |
| `running` | Executing a task |
| `terminated` | Process has exited |

Transitions: `spawning` → `idle` ↔ `running` → `terminated`

## TASK.MD Frontmatter

Tasks use YAML frontmatter for structured metadata:

```markdown
---
status: pending
assigned_by: master
assigned_at: 2026-03-13T10:00:00Z
completed_at:
---

## Task
<description>

## Context
<optional>

## Result
<filled on completion>

## Error
<filled on error>
```

### Status values

| Status | Set by | Meaning |
|--------|--------|---------|
| `pending` | Master (via spawn_agent) | Task awaiting pickup |
| `running` | AgentRunner | Task in progress |
| `done` | AgentRunner | Task completed successfully |
| `error` | AgentRunner | Task failed |

## AgentRunner (`app/agents/base/runner.py`)

The process wrapper for sub-agents.

### Responsibilities

1. **STATUS.json management** — atomic writes at every state transition
2. **TASK.MD watching** — via `watchdog` filesystem events + poll fallback
3. **Task execution** — picks up `status: pending` tasks, calls `run_stream_with_tools(manage_task_file=False)`
4. **Idle timeout** — after `agent_idle_timeout` seconds of no tasks, flushes state and exits
5. **Signal handling** — SIGTERM/SIGINT trigger graceful shutdown

### Configuration

Three settings in `app/config/settings.py`:

| Setting | Default | Purpose |
|---------|---------|---------|
| `agent_idle_timeout` | 300 | Seconds before idle self-termination |
| `agent_spawn_timeout` | 15 | Seconds to wait for spawn confirmation |
| `runner_poll_interval` | 30 | TASK.MD poll fallback interval |

## Delegation Tools

Five tools available to the Master Agent:

| Tool | Purpose |
|------|---------|
| `spawn_agent` | Write TASK.MD + spawn subprocess (or re-task idle agent) |
| `ping_agent` | Read STATUS.json + verify PID alive |
| `kill_agent` | SIGTERM via PID from STATUS.json |
| `check_task_status` | Read TASK.MD frontmatter status |
| `read_task_result` | Read `## Result` section from TASK.MD |

### spawn_agent flow

1. Check STATUS.json — if running/idle and PID alive, just write new TASK.MD
2. Write TASK.MD with `status: pending` frontmatter
3. If no living process, spawn `python -m app.agents.base.runner_entry --agent <name>` (detached)
4. Poll STATUS.json up to `agent_spawn_timeout` for state != `spawning`
5. Return status string

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/agents/{name}/status` | Read STATUS.json with PID liveness check |
| `POST` | `/agents/{name}/spawn` | Spawn agent subprocess |
| `POST` | `/agents/{name}/kill` | SIGTERM agent subprocess |

## Stale PID Detection

When reading STATUS.json, `os.kill(pid, 0)` verifies the process is alive. If the PID is not alive but state is not `terminated`, the status is reported as `terminated` (stale).

## Entry Points

- **Python module**: `python -m app.agents.base.runner_entry --agent <name>`
- **Script**: `yapoc-agent --agent <name>` (registered in `pyproject.toml`)
