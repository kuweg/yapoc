# YAPOC — Yet Another OpenClaw

An autonomous multi-agent system where a small hierarchy of LLM-driven agents collaborate over a shared file system to plan, build, and operate software. The end goal is a Master agent capable enough to finish the rest of the system itself.

Currently 11 agents (master, planning, builder, keeper, doctor, model_manager, cron, evaluator, librarian, researcher, security) cooperate through markdown files, a SQLite task queue, and a Redis message bus.

---

## Quick start

```bash
# Prereqs: Python 3.12, Poetry, Node 20+ with pnpm, Redis running on :6379

# 1. Backend
poetry install
cp .env.example .env                     # then fill in at least one API key
poetry run yapoc start                   # uvicorn on :8000

# 2. Frontend (optional — there's also a CLI REPL)
cd app/frontend && pnpm install && pnpm dev   # vite on :5173

# 3. Talk to the master agent
poetry run yapoc                         # interactive REPL
# or open http://localhost:5173
```

The CLI REPL supports tab-completion, `@file` mentions, `!bash` mode, `/diff`, `/copy`, `/export`, and live cost tracking. Run `/help` inside the REPL to see the full set.

---

## Architecture

```
User
 └─ CLI (Typer/Rich) ─────┐
 └─ Web UI (React/Vite) ──┤── FastAPI backend ── Master agent
 └─ Telegram bot ─────────┘                       │
                                                  ├── Planning   (decomposes complex tasks)
                                                  ├── Builder    (code edits, shell)
                                                  ├── Keeper     (config, .env, settings)
                                                  ├── Researcher (web + investigation)
                                                  ├── Evaluator  (review, quality gate)
                                                  ├── Librarian  (memory consolidation)
                                                  ├── Doctor     (cron: health monitor)
                                                  ├── Model Mgr  (cron: model availability)
                                                  ├── Cron       (scheduled tasks)
                                                  └── Security   (tool-call gatekeeper, LLM L2)
```

Each agent lives in `app/agents/<name>/` and owns a small set of markdown files:

| File | Role |
|------|------|
| `PROMPT.MD` | System prompt — agent identity (committed) |
| `CONFIG.yaml` | adapter, model, tools, sandbox (committed) |
| `TASK.MD` | Current task + frontmatter status (runtime) |
| `MEMORY.MD` | Append-only run log (runtime) |
| `NOTES.MD` | Persistent knowledge (runtime) |
| `HEALTH.MD` | Error log written by self / doctor (runtime) |
| `LEARNINGS.MD` | Auto-injected lessons (runtime) |
| `STATUS.json` | Live runner state (runtime) |

Runtime files are gitignored — only the code-like files (`PROMPT.MD`, `CONFIG.yaml`, `agent.py`) are committed.

Config resolution: `app/config/agent-settings.json` → `CONFIG.yaml` → `app/config/settings.py` defaults.

---

## Key concepts

**Centralized settings.** Every config value lives in `app/config/settings.py` (pydantic-settings). Application code reads from `from app.config import settings`; nothing reads `os.environ` directly.

**Security gate.** Risky tool calls (`file_delete`, `shell_exec`, `kill_agent`, etc.) go through a two-layer gate before execution: a synchronous hardcoded ruleset (`app/utils/tools/security_policy.py`) for absolute denies/allows, and an LLM classifier (the `security` agent) for the ambiguous middle. Edits to critical config files are *not* blocked — only deletions are. Every decision is logged to `app/agents/security/AUDIT.MD`.

**Sessions.** Browser tabs and CLI shells each get a session id. `/api/task/stream` and the WebSocket relay are session-scoped so multiple users / shells don't crosstalk.

**Cost governance.** Per-task, per-agent, and daily-autonomous budgets are configurable in `.env` (defaults: $2 / $0 / $10). Streaming turns abort at the cap and write a clear `[BUDGET EXCEEDED]` message to `HEALTH.MD`.

**Git autocheckpoint.** Each sub-agent task spawn snapshots HEAD, runs a smoke check on terminal status, and commits or rolls back. Lets the system self-modify without bricking.

**Stuck-loop detection.** The streaming layer watches for 3+ consecutive copies of a short substring in the model output and aborts the turn cleanly — small models occasionally fall into "Let me check X:Let me check X:..." spirals.

---

## CLI

```
yapoc start | stop | restart   # backend lifecycle
yapoc status | ping            # backend health
yapoc                          # interactive REPL
yapoc chat "hello"             # one-shot message
yapoc agents list | status     # agent inventory
yapoc models list | info       # LLM model picker
yapoc report                   # write the morning report manually
yapoc evaluator-tick           # kick the evaluator once
```

---

## Frontend

`app/frontend/` is a Vite + React app served on port 5173 in dev mode. Vite proxies `/api/*` and `/ws` to the backend on port 8000. Key features:
- Real-time streaming of master + sub-agent activity
- Session list with rename, export, and morning-report view
- Voice mode (TTS + STT via OpenAI or local engines)
- Memory tab with hybrid (FTS5 + embedding) search
- Cost tracker per session

---

## Configuration

Copy `.env.example` to `.env` and fill in the keys you actually need. With zero keys the system still boots — you just can't reach a cloud LLM.

Provider keys it knows about: Anthropic, OpenAI, Google Gemini, DeepSeek, OpenRouter, LM Studio (local), Ollama (local).

Per-agent model bindings live in `app/config/agent-settings.json`. Edit there to swap a single agent's model without touching `.env`.

---

## Project rules

- **Poetry only.** Never `pip install`. Always `poetry add` / `poetry install` / `poetry remove`.
- **Centralized settings.** Never `os.environ.get(...)`; import `settings`.
- **Docs in `docs/` are authoritative** — when behavior contradicts documentation, the docs are right and the code needs a fix.
- **No tests yet.** MVP phase; tests are not part of the default flow.

See `CLAUDE.md` for the working agreement used when running Claude Code in this repo, and `app/agents/*/CLAUDE.md` for per-subsystem briefings.

---

## Layout

```
app/
├── config/        # settings.py (single source of truth)
├── agents/        # one dir per agent
│   ├── base/      # BaseAgent + AgentRunner subprocess machinery
│   ├── master/    # Entry point
│   ├── planning/  # Task decomposer
│   ├── builder/   # File / code edits
│   ├── keeper/    # Config manager
│   ├── doctor/    # Health monitor (cron)
│   ├── model_manager/
│   ├── evaluator/
│   ├── librarian/
│   ├── researcher/
│   ├── cron/
│   └── security/  # Tool-call gatekeeper
├── backend/       # FastAPI app, routers, dispatcher, message bus
├── cli/           # Typer + Rich REPL
├── utils/
│   ├── adapters/  # LLM adapter registry (8 providers)
│   ├── tools/     # 40-tool registry agents can invoke
│   └── db.py      # SQLite task_queue + memory index
└── frontend/      # React/Vite dashboard
```

---

## Status

Implemented: all 11 agents, FastAPI backend, Typer CLI + Rich REPL, React frontend, 8 LLM adapters with cross-provider failover, 40-tool registry, watchdog-based runner, SQLite + Redis IPC, session persistence, context auto-compaction, cost tracking + budgets, security gate, git autocheckpoint, stuck-loop detector, voice (TTS/STT), Telegram bot, webhook ingest.

Not implemented: persistent Telegram auth across restarts, formal test suite, dark-mode UI, multi-user RBAC.
