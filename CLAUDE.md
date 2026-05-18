# YAPOC — Yet Another OpenClaw

Autonomous multi-agent system where a hierarchy of specialized AI agents collaborate to plan, build, and self-manage tasks via file-based communication. The goal is to build a Master Agent that can finish the rest of the system.

## Project Rules

- **Poetry only** — always use `poetry add`, `poetry install`, `poetry remove`. Never use pip directly.
- **No tests yet** — MVP phase, skip test creation unless explicitly asked.
- **Centralized settings** — all configuration lives in `app/config/settings.py` (pydantic-settings). Never read env vars with `os.environ` directly in application code; import `settings` from `app.config` instead.
- **Docs are authoritative** — design docs in `docs/` define the intended architecture. When in doubt, follow the docs.

## Architecture

```
User → CLI (Typer/Rich) → FastAPI Backend → Master Agent → Planning Agent → Builder / Keeper / Cron
                                                         → Doctor (autonomous health monitor)
                                                         → Model Manager (cost optimizer)
                                                         → Security (tool-call gatekeeper)
                                                         → Evaluator (code review)
                                                         → Librarian (memory consolidation)
                                                         → Researcher (web investigations)
```

Agents are file-isolated: each lives in `app/agents/<name>/` and communicates through its own markdown files.

### Agent Inventory (11 agents)

| Agent | Role | Tools | Delegates to |
|-------|------|-------|-------------|
| **master** | Orchestrator — entry point for all user interaction | file_read/write/edit/delete/list, create_agent, delete_agent | planning, builder, keeper, any dynamic agent |
| **planning** | Task decomposer — breaks complex goals into subtasks | file_read/write/edit/delete/list | builder, keeper |
| **builder** | File creator/editor, code writer, shell executor | file_read/write/edit/delete/list, shell_exec | keeper |
| **keeper** | Config & secrets guardian (.env, settings.py, agent-settings.json, pyproject.toml) | file_read/write/edit/delete/list | builder |
| **cron** | Scheduled/recurring task manager | file_read/write/edit/delete/list | builder, keeper, doctor, master |
| **doctor** | Autonomous health monitor — checks agent HEALTH.MD, detects anomalies | file_read/write/edit/delete/list | — |
| **model_manager** | Model availability checks, cross-agent config management, cost optimization | file_read/write/edit/delete/list | — |
| **evaluator** | Code review, quality assessment, proposal evaluation | file_read/write, file_list, search_memory, memory_append, notes_read/write/append, health_log, notify_parent, shared_knowledge_append, get_recent_signals | — |
| **librarian** | Memory consolidation — summarizes and archives agent memory | file_read/write/edit/delete/list | — |
| **researcher** | Web research, deep-dive investigation | web_search, fetch_page, file_read/write/list, memory_append, notes_read/write/append, search_memory, shared_knowledge_append, health_log, notify_parent, spawn_agent, wait_for_agent, check_task_status | — |
| **security** | Tool-call gatekeeper — reviews ambiguous tool calls for policy violations | (none — pure LLM classification) | — |

### Agent File Schema

Each agent directory contains:

| File | Purpose | Written by |
|------|---------|------------|
| `PROMPT.MD` | System prompt — agent identity and constraints | Developer / Builder |
| `TASK.MD` | Current task with status (frontmatter: status, assigned_by, created_at) | Planning (assigns) / Self (updates) |
| `MEMORY.MD` | Append-only log: `[YYYY-MM-DD HH:MM] task: ... \| response: ...` | Self |
| `NOTES.MD` | Persistent knowledge and domain facts | Self |
| `HEALTH.MD` | Error log: `[YYYY-MM-DD HH:MM] ERROR: <message>` | Self / Doctor |
| `CONFIG.yaml` | YAML config: adapter, model, temperature, tools, delegation_targets, sandbox | Keeper / Developer |
| `LEARNINGS.MD` | Learned rules (auto-injected into agent prompt) | Self |
| `GOALS.MD` | Autonomous backlog goals | Self / Master |
| `RESUME.MD` | Post-restart task continuity state | System (auto) |
| `OUTPUT.MD` | Subprocess stdout capture | System |
| `CRASH.MD` | Crash reports | System |

Config resolution order: `app/config/agent-settings.json` (per-agent binding, authoritative) → `CONFIG.yaml` → `NOTES.MD [config]` block → `app/config/settings.py` defaults.

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
│   └── tools/                # Agent tools (40 tools — see docs/tools.md)
│       ├── __init__.py       # BaseTool, TOOL_REGISTRY, build_tools()
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
| `CONFIG.yaml` | YAML config: adapter, model, temperature, tools, delegation_targets, sandbox | Keeper / Developer |

Config resolution order: `app/config/agent-settings.json` (per-agent binding) → `CONFIG.md` → `NOTES.MD [config]` block → `app/config/settings.py` defaults. `agent-settings.json` is the authoritative cross-provider primary; CONFIG.md is the fallback for agents not listed there.

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

Registry in `app/utils/adapters/__init__.py`. Eight built-in:
- `AnthropicAdapter` — `anthropic` SDK, primary
- `OpenAIAdapter` — raw `httpx` (Chat Completions)
- `CodexAdapter` — raw `httpx` to OpenAI Responses API (codex-mini / gpt-5.x-codex)
- `DeepSeekAdapter` — OpenAI-compatible
- `OpenRouterAdapter` — OpenAI-compatible, multi-provider
- `GoogleAdapter` — Gemini
- `OllamaAdapter` — raw `httpx` to local Ollama
- `LMStudioAdapter` — raw `httpx` to local LM Studio

All read credentials from `settings`, not `os.environ`. The `FallbackAdapter`
wraps any adapter with cross-provider retry rules defined in `agent-settings.json`.

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

Registry in `app/utils/tools/__init__.py` (40 tools):

**Server/Process:** `server_restart`, `process_restart`
**Shell:** `shell_exec`
**File:** `file_read`, `file_write`, `file_edit`, `file_delete`, `file_list`, `image_read`, `parse_csv`
**Memory / Notes / Health:** `memory_append`, `notes_read`, `notes_write`, `notes_append`, `health_log`, `learnings_append`, `agent_amnesia`, `search_memory`, `shared_knowledge_append`
**Web:** `web_search`
**Delegation:** `spawn_agent`, `ping_agent`, `kill_agent`, `check_task_status`, `read_task_result`, `wait_for_agent`, `wait_for_agents`, `notify_parent`, `read_agent_logs`
**Agent Management:** `create_agent`, `delete_agent`, `update_config`, `update_agent_config`
**Model Management:** `check_model_availability`, `list_models`, `heal_agent_settings`, `show_agent_settings`

All tools execute immediately without approval prompts. Each agent's `CONFIG.md` lists its assigned tools.

## Implementation Status

**All agents implemented:** master, planning, builder, keeper, cron, doctor, model_manager, evaluator, librarian, researcher, security

**Implemented features:** settings, all adapters (Anthropic, OpenAI, Codex, DeepSeek, OpenRouter, Google, Ollama, LMStudio), BaseAgent (with context assembly), AgentRunner (watchdog-based), FastAPI backend, Typer CLI + Rich REPL (cost tracking, tab completion, @file mentions, !bash mode, /diff, /copy, /export), tool-use loop (40+ tools), session persistence, context auto-compaction, stale-task watchdog, notification trace mode, hierarchy classification helpers, DAG execution engine, dynamic agent composition with capability modules, security gate (hardcoded rules + security agent review), peer delegation, autonomous goal-driven behavior, learning system (LEARNINGS.MD auto-injection), shared knowledge base, post-restart resume (RESUME.MD)
