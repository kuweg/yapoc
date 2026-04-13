# CLI Design

Built with **Typer**. Entry point: `app/cli/main.py`.
Invoked as `yapoc <command>` (configured via `pyproject.toml` scripts).

---

## Command Tree

```
yapoc
├── start                        # Start the system (backend + all agents)
├── stop                         # Stop the system gracefully
├── restart                      # Full restart
├── status                       # System-wide status overview
├── ping                         # Health check — sends ping, expects pong
│
├── agents
│   ├── list                     # Table of all agents with short info
│   ├── status [agent_name]      # Status of all agents, or one specific agent
│   ├── config <agent_name>      # Open agent's CONFIG.md in $EDITOR
│   └── model <agent_name>       # Assign a model/adapter to a specific agent
│
├── models
│   ├── list                     # Interactive provider+model picker (see below)
│   └── info                     # Show currently assigned default model
│
└── cron
    ├── list                     # List all scheduled tasks
    ├── start <task_id>          # Enable a cron task
    ├── stop <task_id>           # Disable a cron task
    └── config <task_id>         # Edit task schedule/config
```

---

## Command Details

### `yapoc start / stop / restart`

```
$ yapoc start
  Starting YAPOC...
  ✔ Backend       running on :8000
  ✔ Master        ready
  ✔ Planning      ready
  ✔ Builder       ready
  ✔ Keeper        ready
  ✔ Cron          ready  (3 tasks scheduled)
  ✔ Doctor        ready  (next run in 5m)
```

### `yapoc status`

```
$ yapoc status
  System    RUNNING
  Uptime    2h 14m
  Backend   :8000
  Agents    6/6 healthy
  Cron      3 tasks active
```

### `yapoc ping`

```
$ yapoc ping
  → pong  (12ms)
```

---

### `yapoc agents list`

```
$ yapoc agents list

  Agent      Status     Model                  Last active
  ─────────────────────────────────────────────────────────
  master     running    claude-sonnet-4-6      just now
  planning   idle       claude-sonnet-4-6      3m ago
  builder    idle       gpt-4o                 12m ago
  keeper     idle       claude-sonnet-4-6      1h ago
  cron       running    —                      just now
  doctor     idle       claude-haiku-4-5       5m ago
```

### `yapoc agents status [agent_name]`

Without argument — same as `agents list`.
With argument — detailed single-agent view:

```
$ yapoc agents status master

  Agent     master
  Status    running
  Model     claude-sonnet-4-6
  Adapter   anthropic
  Task      "Summarise today's project progress"
  Memory    14 entries
  Health    0 errors
```

### `yapoc agents config <agent_name>`

Opens the agent's `CONFIG.md` in `$EDITOR`.
After save, the runner hot-reloads the agent config without restart.

### `yapoc agents model <agent_name>`

Launches the same interactive model picker as `models list`, then writes the selection to the agent's `CONFIG.md`.

---

### `yapoc models list` — Interactive Picker

Inspired by Claude Code's model selector. Keyboard-driven, two-step:

**Step 1 — Choose provider:**
```
  Select provider
  ───────────────
  ❯ Anthropic
    OpenAI
    Ollama (local)
```

**Step 2 — Choose model (filtered by provider):**
```
  Select model  [Anthropic]
  ─────────────────────────
  ❯ claude-sonnet-4-6      (default)
    claude-opus-4-6
    claude-haiku-4-5
```

Selection is written to `.env` as the system default (`DEFAULT_ADAPTER`, `DEFAULT_MODEL`).

### `yapoc models info`

```
$ yapoc models info

  Default model
  ─────────────
  Provider   anthropic
  Model      claude-sonnet-4-6
  Set in     .env
```

---

### `yapoc cron list`

```
$ yapoc cron list

  ID          Schedule      Status     Next run     Description
  ──────────────────────────────────────────────────────────────
  doctor      */5 * * * *   active     in 3m        Run Doctor agent
  cleanup     0 3 * * *     active     in 18h       Clear old MEMORY.MD entries
  report      0 9 * * 1     paused     —             Weekly summary
```

### `yapoc cron start / stop <task_id>`

```
$ yapoc cron stop report
  ✔ Task 'report' paused.

$ yapoc cron start report
  ✔ Task 'report' scheduled. Next run: Mon 09:00
```

### `yapoc cron config <task_id>`

Opens the task's schedule and parameters in `$EDITOR` (JSON or inline TOML block).

---

## Implementation Notes

- All commands use **Typer** with `rich` for table/color output.
- Interactive pickers use **`questionary`** or Typer's built-in prompt with choices.
- Commands that talk to agents go through the **FastAPI backend** (`httpx` client in `app/cli/`).
- `start/stop/restart` manage the `uvicorn` process (subprocess or systemd unit depending on environment).
- `$EDITOR` fallback order: `$VISUAL` → `$EDITOR` → `nano`.

### Additional dependency

```toml
"rich>=13.0.0",
"questionary>=2.0.0",
```
