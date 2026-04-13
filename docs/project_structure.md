# Project Structure

```
yapoc/
├── app/
│   ├── agents/                  # Agent definitions: code + markdown state files
│   │   ├── base/                # Shared base class / runner logic for all agents
│   │   │   ├── __init__.py      # BaseAgent class (async file I/O, config, run/stream/tool loop)
│   │   │   ├── context.py       # build_system_context() — assembles PROMPT+MEMORY+NOTES+HEALTH
│   │   │   ├── runner.py        # AgentRunner — watchdog-based TASK.MD watcher, STATUS.json lifecycle
│   │   │   └── runner_entry.py  # Subprocess entry point for spawned agents
│   │   ├── master/              # Entry point agent — accepts user tasks, delegates to planning
│   │   │   ├── agent.py
│   │   │   ├── PROMPT.MD
│   │   │   ├── TASK.MD
│   │   │   ├── MEMORY.MD
│   │   │   ├── NOTES.MD
│   │   │   ├── HEALTH.MD
│   │   │   ├── CONFIG.md
│   │   │   ├── RESUME.MD
│   │   │   ├── sessions/        # JSONL session files
│   │   │   ├── SERVER_OUTPUT.MD
│   │   │   └── SERVER_CRASH.MD
│   │   ├── planning/            # Task decomposer — breaks goals into subtasks (implemented)
│   │   │   ├── agent.py
│   │   │   ├── __init__.py
│   │   │   ├── PROMPT.MD
│   │   │   └── CONFIG.md
│   │   ├── builder/             # File creator/editor, agent scaffolder (implemented)
│   │   │   ├── agent.py
│   │   │   ├── __init__.py
│   │   │   ├── PROMPT.MD
│   │   │   └── CONFIG.md
│   │   ├── keeper/              # Config management (stub)
│   │   │   └── ...
│   │   ├── cron/                # Scheduled tasks (stub)
│   │   │   └── ...
│   │   └── doctor/              # Health monitor — autonomous cron-driven (implemented)
│   │       ├── agent.py
│   │       ├── PROMPT.MD
│   │       ├── CONFIG.md
│   │       └── HEALTH_SUMMARY.MD
│   │
│   ├── backend/                 # FastAPI app — API layer and core orchestration
│   │   ├── main.py              # App entry point, mounts routers, APScheduler lifespan
│   │   ├── routers/             # Route handlers (tasks, agents, health)
│   │   ├── services/            # Business logic (agent runner, file manager, scheduler)
│   │   └── models/              # Pydantic request/response schemas
│   │
│   ├── cli/                     # User-facing CLI interface
│   │   ├── main.py              # CLI entry point (commands, REPL, slash commands, completers)
│   │   ├── renderer.py          # TurnRenderer — Rich Live display + cost tracking
│   │   ├── sessions.py          # SessionStore — JSONL-based conversation persistence
│   │   └── __init__.py
│   │
│   ├── config/
│   │   └── settings.py          # Centralized Settings(BaseSettings) — single source of truth
│   │
│   ├── projects/                # Workspace: agents build and store their output here
│   │
│   └── utils/                   # Shared helpers (file I/O, LLM client, logging)
│       ├── __init__.py          # Re-exports PROJECT_ROOT, AGENTS_DIR
│       ├── context.py           # Token estimation + auto-compact logic
│       ├── adapters/            # LLM provider adapters (see adapters.md)
│       │   ├── __init__.py      # Adapter registry + re-exports
│       │   ├── base.py          # BaseLLMAdapter, Message, stream events, AgentConfig
│       │   ├── anthropic.py
│       │   ├── openai.py
│       │   └── ollama.py
│       └── tools/               # Agent tools (see tools.md)
│           ├── __init__.py      # BaseTool, RiskTier, TOOL_REGISTRY (20 tools), build_tools()
│           ├── server.py        # ServerRestartTool, ProcessRestartTool
│           ├── shell.py         # ShellExecTool
│           ├── file.py          # FileReadTool, FileWriteTool, FileEditTool, FileDeleteTool, FileListTool
│           ├── memory.py        # MemoryAppendTool, NotesReadTool, NotesWriteTool, HealthLogTool
│           ├── web.py           # WebSearchTool
│           ├── delegation.py    # SpawnAgentTool, PingAgentTool, KillAgentTool, CheckTaskStatusTool, ReadTaskResultTool
│           ├── logs.py          # ReadAgentLogsTool
│           └── agent_mgmt.py    # CreateAgentTool, DeleteAgentTool
│
├── docs/
├── tests/
├── .env
├── pyproject.toml
└── README.md
```

## Directory Responsibilities

| Directory | Owner | Purpose |
|---|---|---|
| `app/agents/` | All agents | Agent logic + their markdown state files |
| `app/agents/base/` | System | Shared `BaseAgent` class, runner, context assembly |
| `app/backend/` | System | FastAPI app, HTTP API, orchestration wiring |
| `app/cli/` | User | CLI commands, interactive REPL, session management |
| `app/config/` | System | Centralized pydantic-settings configuration |
| `app/projects/` | Builder Agent | Filesystem workspace for agent-generated outputs |
| `app/utils/` | System | LLM adapters, tool registry, context management |
| `tests/` | Dev | Unit + integration tests per agent and API route |
