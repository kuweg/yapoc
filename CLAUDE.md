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
