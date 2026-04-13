# YAPOC — Yet Another OpenClaw

Autonomous multi-agent system where a hierarchy of specialized AI agents collaborate to plan, build, and self-manage tasks via file-based communication. The goal is to build a Master Agent that can finish the rest of the system.

## Project Rules

- **Poetry only** — always use `poetry add`, `poetry install`, `poetry remove`. Never use pip directly.
- **No tests yet** — MVP phase, skip test creation unless explicitly asked.
- **Centralized settings** — all configuration lives in `app/config/settings.py` (pydantic-settings). Never read env vars with `os.environ` directly in application code; import `settings` from `app.config` instead.
- **Docs are authoritative** — design docs in `docs/` define the intended architecture. When in doubt, follow the docs.

## Architecture

```
User → CLI (Typer/Rich) → FastAPI Backend → Master Agent → Planning Agent → Builder/Keeper/Cron
                                                         → Doctor Agent (autonomous cron)
```

Agents are file-isolated: each lives in `app/agents/<name>/` and communicates through its own markdown files.

## Project Structure

```
app/
├── config/
│   └── settings.py          # Centralized Settings(BaseSettings) — single source of truth
├── agents/
│   ├── base/
│   │   ├── __init__.py       # BaseAgent class (async file I/O, config, run loop)
│   │   ├── context.py        # build_system_context() — assembles PROMPT+MEMORY+NOTES+HEALTH
│   │   ├── runner.py         # AgentRunner — watchdog-based TASK.MD watcher
│   │   └── runner_entry.py   # Subprocess entry point for spawned agents
│   ├── master/               # Entry point agent (implemented)
│   ├── planning/             # Task decomposition (implemented)
│   ├── builder/              # File/agent creation (implemented)
│   ├── keeper/               # Config management (stub)
│   ├── cron/                 # Scheduled tasks (stub)
│   └── doctor/               # Health monitor (implemented)
├── backend/
│   ├── main.py               # FastAPI app
│   ├── routers/              # health, tasks, agents
│   ├── services/             # AgentService
│   └── models/               # Pydantic request/response models
├── cli/
│   ├── main.py               # Typer CLI commands + interactive REPL (completers, @mentions, !bash, cost)
│   ├── renderer.py           # TurnRenderer — Rich Live display for streaming + cost tracking
│   └── sessions.py           # SessionStore — JSONL-based conversation persistence
├── utils/
│   ├── adapters/             # LLM adapters (anthropic, openai, ollama)
│   ├── context.py            # Token estimation + auto-compact logic
│   └── tools/                # Agent tools (20 tools — see docs/tools.md)
│       ├── __init__.py       # BaseTool, RiskTier, TOOL_REGISTRY, build_tools()
│       ├── server.py         # ServerRestartTool, ProcessRestartTool
│       ├── shell.py          # ShellExecTool
│       ├── file.py           # FileReadTool, FileWriteTool, FileEditTool, FileDeleteTool, FileListTool
│       ├── memory.py         # MemoryAppendTool, NotesReadTool, NotesWriteTool, HealthLogTool
│       ├── web.py            # WebSearchTool
│       ├── delegation.py     # SpawnAgentTool, PingAgentTool, KillAgentTool, CheckTaskStatusTool, ReadTaskResultTool
│       ├── logs.py           # ReadAgentLogsTool
│       └── agent_mgmt.py     # CreateAgentTool, DeleteAgentTool
└── projects/                 # Workspace for Builder Agent output
```

## Agent File Schema

Each agent directory contains:

| File | Purpose | Written by |
|------|---------|------------|
| `PROMPT.MD` | System prompt — agent identity and constraints | Developer / Builder |
| `TASK.MD` | Current task with status | Planning (assigns) / Self (updates) |
| `MEMORY.MD` | Append-only log: `[YYYY-MM-DD HH:MM] task: ... \| response: ...` | Self |
| `NOTES.MD` | Persistent knowledge and domain facts | Self |
| `HEALTH.MD` | Error log: `[YYYY-MM-DD HH:MM] ERROR: <message>` | Self / Doctor |
| `CONFIG.md` | YAML-like config: adapter, model, temperature, tools, runner | Keeper / Developer |

Config resolution order: `CONFIG.md` → `NOTES.MD [config]` block → `app/config/settings.py` defaults.

## Settings (`app/config/settings.py`)

Pydantic BaseSettings, auto-reads `.env`:
- `anthropic_api_key`, `openai_api_key` — API keys
- `default_adapter`, `default_model`, `default_temperature` — LLM defaults
- `host`, `port` — server bind (computed `base_url`)
- `ollama_base_url` — Ollama endpoint
- `max_turns`, `task_timeout` — runner limits
- `project_root`, `agents_dir` — path properties

Usage: `from app.config import settings`

## LLM Adapters

Registry in `app/utils/adapters/__init__.py`. Three built-in:
- `AnthropicAdapter` — `anthropic` SDK, primary
- `OpenAIAdapter` — raw `httpx` (no openai package)
- `OllamaAdapter` — raw `httpx` to local Ollama

All read credentials from `settings`, not `os.environ`.

## API Endpoints

```
GET  /health                  → {"status": "ok", "uptime": ...}
POST /task                    → {"status": "ok", "response": "..."}
GET  /agents                  → [AgentStatus, ...]
GET  /agents/{name}/memory    → {"name": "...", "content": "..."}
GET  /agents/{name}/health    → {"name": "...", "content": "..."}
POST /agents/{name}/restart   → {"status": "ok", "name": "..."}
```

## CLI Commands

```
yapoc start|stop|restart      # Server lifecycle
yapoc status|ping             # Server health
yapoc                         # Enter interactive REPL
yapoc chat [message]          # One-shot message, or interactive REPL
yapoc agents list|status      # Agent management
yapoc models list|info        # LLM model picker / current config
yapoc cron list|start|stop    # (stubs — not yet implemented)
```

## Running

```bash
poetry install                         # Install deps
poetry run yapoc start                 # Start backend
poetry run yapoc chat "hello"          # Send a message
poetry run yapoc                       # Interactive REPL
```

## Implemented Tools

Registry in `app/utils/tools/__init__.py` (20 tools):

**Server/Process:** `server_restart`, `process_restart`
**Shell:** `shell_exec`
**File:** `file_read`, `file_write`, `file_edit`, `file_delete`, `file_list`
**Memory:** `memory_append`, `notes_read`, `notes_write`, `health_log`
**Web:** `web_search`
**Delegation:** `spawn_agent`, `ping_agent`, `kill_agent`, `check_task_status`, `read_task_result`, `read_agent_logs`
**Agent Management:** `create_agent`, `delete_agent`

Tools use `RiskTier.AUTO` (safe) or `RiskTier.CONFIRM` (requires approval). Each agent's `CONFIG.md` lists its assigned tools.

## Implementation Status

**Implemented:** settings, all adapters, BaseAgent (with context assembly), MasterAgent, PlanningAgent, BuilderAgent, DoctorAgent, AgentRunner (watchdog-based), FastAPI backend, Typer CLI + Rich REPL (cost tracking, tab completion, @file mentions, !bash mode, /diff, /copy, /export), tool-use loop (20 tools), session persistence, context auto-compaction
**Stubs:** keeper, cron agents; cron CLI commands
