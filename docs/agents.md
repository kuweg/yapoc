# Agents

## Base Agents

Base agents are fixed, system-level agents that form the core of YAPOC. They cannot be deleted or created by other agents.

---

## Hierarchy & Delegation

```
User
 └── Master Agent
      ├── Planning Agent
      │    ├── Builder Agent
      │    ├── Keeper Agent
      │    └── Cron Agent
      └── Doctor Agent  (autonomous, runs on its own cron)
```

### Delegation Rules

| From | To | Method |
|------|----|--------|
| User | Master | API / CLI |
| Master | Planning | `spawn_agent` tool |
| Master | Any agent | `spawn_agent` tool (for simple tasks, Master can delegate directly) |
| Planning | Builder, Keeper, Cron | `spawn_agent` tool |
| Doctor | (none) | Doctor only reads/writes HEALTH.MD files, never delegates |

**Key constraint:** Every task chain originates from Master. No agent can self-initiate work except Doctor (which runs on a cron schedule).

**Delegation tools:** `spawn_agent` (start agent with task), `ping_agent` (check liveness), `kill_agent` (SIGTERM), `check_task_status` (read TASK.MD status), `read_task_result` (read Result section), `read_agent_logs` (read OUTPUT.MD).

### Task Flow (typical)

```
User ──POST /task──▶ Master
                       │
                       │ spawn_agent("planning", task=..., context=...)
                       ▼
                    Planning
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
       Builder      Keeper        Cron
       (creates     (updates      (schedules
        agent)       config)       task)
          │            │            │
          ▼            ▼            ▼
       status:done  status:done  status:done
          │            │            │
          └────────────┼────────────┘
                       ▼
                  Planning reads results via
                  read_task_result(), writes summary
                       │
                       ▼
                  Master reads Planning result via
                  read_task_result(), returns to user
```

---

## Agent Descriptions

### Master Agent _(implemented)_

**Role:** Single entry point for all user interaction.

**Responsibilities:**
- Receive tasks from user (API/CLI)
- Execute simple tasks directly using available tools
- Delegate complex tasks to Planning Agent (or directly to Builder for simple file ops)
- Return results to user
- Log important actions to memory

**Tools:** `server_restart`, `process_restart`, `shell_exec`, `file_read`, `file_write`, `file_edit`, `file_delete`, `file_list`, `web_search`, `memory_append`, `notes_read`, `notes_write`, `health_log`, `spawn_agent`, `ping_agent`, `kill_agent`, `check_task_status`, `read_task_result`, `read_agent_logs`, `create_agent`, `delete_agent`

**Delegation:** Master handles simple tasks directly. For multi-step tasks, it delegates to Planning via `spawn_agent("planning", task=..., context=...)`, polls with `check_task_status`, and reads results with `read_task_result`.

---

### Planning Agent _(implemented)_

**Role:** Break tasks into executable steps and distribute to the right agents.

**Responsibilities:**
- Receive a high-level task from Master
- Decompose into subtasks
- Delegate subtasks to Builder/Keeper/Cron via `spawn_agent`
- Poll for completion with `check_task_status` (every 10-15s)
- Aggregate results and write summary back

**Tools:** `spawn_agent`, `ping_agent`, `kill_agent`, `check_task_status`, `read_task_result`, `file_read`, `file_list`, `memory_append`, `notes_read`, `notes_write`, `health_log`

**Config:** Sonnet model, 30 max turns, 600s timeout. Max 3 concurrent sub-agents.

---

### Builder Agent _(implemented)_

**Role:** Create, edit, and delete non-base agents. Modify project files.

**Responsibilities:**
- Create new agent directories with full file scaffolding via `create_agent` tool
- Edit agent prompts, configs, and project files via `file_write`/`file_edit`
- Delete non-base agents via `delete_agent` tool
- Verify changes with `file_read` after writing

**Tools:** `file_read`, `file_write`, `file_edit`, `file_delete`, `file_list`, `shell_exec`, `create_agent`, `delete_agent`, `memory_append`, `notes_read`, `notes_write`, `health_log`

**Config:** Sonnet model, temperature 0.2, 40 max turns, 600s timeout.

**Cannot:** Modify base agent directories (master, planning, builder, keeper, cron, doctor, base).

---

### Keeper Agent _(stub)_

**Role:** Manage project-level settings and configuration.

**Responsibilities (planned):**
- Edit `.env`, `pyproject.toml`, and other root config files
- Update adapter/model defaults
- Manage environment variables

**Tools (planned):** `file_read`, `file_write`, `shell_exec` (config files only), memory tools

**Cannot:** Modify agent directories or create/delete agents.

---

### Cron Agent _(stub)_

**Role:** Schedule and manage timed/recurring tasks.

**Responsibilities (planned):**
- Create cron-style scheduled tasks via APScheduler
- Cancel or modify existing schedules
- When a cron fires, write the task to the target agent's TASK.MD

**Tools (planned):** `schedule_task`, `cancel_task`, `list_scheduled`, memory tools

---

### Doctor Agent _(implemented)_

**Role:** Autonomous system health monitor.

**Responsibilities:**
- Runs on its own cron schedule (default: every 5 minutes, configurable via `doctor_interval_minutes`)
- Reads all agents' HEALTH.MD files (now enriched with full tracebacks)
- Reads CRASH.MD and SERVER_CRASH.MD for structured crash reports
- Reads OUTPUT.MD and SERVER_OUTPUT.MD for subprocess output
- Produces a rolling HEALTH_SUMMARY.MD report in its own directory
- Logs each health check run to its own MEMORY.MD

**Tools:** `file_read`, `file_list`, `read_agent_logs`, `memory_append`, `notes_read`, `notes_write`, `health_log`

**Config:** Uses `claude-haiku-4-5-20251001` with low temperature (0.2) for cost-effective monitoring.

**API:** `GET /health/summary` returns the latest HEALTH_SUMMARY.MD content.

**Special:** Only agent that runs autonomously without a task from Master. Triggered by APScheduler cron in FastAPI lifespan.

---

## Agent State Files

Each agent has up to 9 files in its directory:

| File | Purpose | Written by |
|------|---------|------------|
| `PROMPT.MD` | Agent identity, role, constraints, personality | Developer (or Builder for non-base agents) |
| `TASK.MD` | Current task with status, description, result | Planning Agent (assigns) / Self (updates status, writes result) |
| `MEMORY.MD` | Short log of completed actions and decisions | Self (append-only, summarized periodically) |
| `NOTES.MD` | Persistent knowledge — user info, domain facts, patterns | Self |
| `HEALTH.MD` | Error log with full tracebacks | Self (logs errors) / Doctor (reads) |
| `CONFIG.md` | Agent configuration — adapter, model, tools, runner settings | Keeper Agent or developer |
| `OUTPUT.MD` | Captured subprocess stdout/stderr | Capture harness (spawn) |
| `CRASH.MD` | Structured crash reports (exit code, traceback) | Capture harness / runner_entry.py |
| `HEALTH_SUMMARY.MD` | Rolling health report (doctor/ only) | Doctor agent |

Master agent also has `SERVER_OUTPUT.MD` and `SERVER_CRASH.MD` for uvicorn process output.

See `overall_system_design.md` for TASK.MD schema and `agent_runner.md` for how files are loaded into context.
