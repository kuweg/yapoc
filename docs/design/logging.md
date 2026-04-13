# Structured Agent Activity Logging

## Overview

When running `poetry run yapoc backend`, the server process inherits the terminal's stdout/stderr — but previously, only uvicorn's own startup and HTTP access lines appeared. There was no visibility into agent activity: which agent was responding, what turn it was on, which tools it called, how many tokens it used, or when it errored.

This document describes the structured logging system added to YAPOC. It instruments the single chokepoint where all agent activity flows — `BaseAgent.run_stream_with_tools()` — so every agent (master in-process, all subprocess agents) emits structured log lines automatically, without modifying individual agent implementations.

### Goals

- Show turn-by-turn activity: agent name, turn number, model, estimated context size
- Show tool calls with input preview and execution time
- Show per-turn token usage and estimated cost
- Show context compaction events
- Show task completion summaries
- Show exceptions with full tracebacks
- Support human-readable and JSON-Lines output formats
- Be configurable via settings/env vars without code changes
- Zero overhead when `LOG_AGENT_ACTIVITY=false`

---

## Architecture

```
poetry run yapoc backend
    │
    └── subprocess.Popen([uvicorn, app.backend.main:app])
            stdout/stderr inherited → terminal
            │
            └── FastAPI lifespan()
                    │
                    ├── setup_logging()   ← configures root logger
                    │       │
                    │       ├── StreamHandler(stderr)  → terminal
                    │       └── RotatingFileHandler    → LOG_FILE (optional)
                    │
                    └── [requests arrive]
                            │
                            └── BaseAgent.run_stream_with_tools()
                                    │
                                    ├── _log.info("Turn %d start ...")
                                    ├── _log.info("Tool %s | input=...")
                                    ├── _log.info("Tool %s done | elapsed=...")
                                    ├── _log.info("Usage turn=%d | ...")
                                    ├── _log.info("Compact auto | ...")
                                    ├── _log.info("Task done | ...")
                                    └── _log.error("Exception %s | ...")

Subprocess agents (planning, builder, etc.):
    runner_entry.py → setup_logging() → StreamHandler(stderr)
    (stderr is captured to app/agents/<name>/OUTPUT.MD by SpawnAgentTool)
```

---

## Settings

| Field | Env Var | Default | Description |
|---|---|---|---|
| `log_level` | `LOG_LEVEL` | `"INFO"` | Python log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `log_file` | `LOG_FILE` | `""` | Absolute/relative path to log file; empty = stderr only. Rotates at 10 MB, keeps 3 backups. |
| `log_json` | `LOG_JSON` | `false` | `true` → JSON-Lines output; `false` → human-readable |
| `log_agent_activity` | `LOG_AGENT_ACTIVITY` | `true` | Master switch. `false` silences all agent log lines. |

All settings can be set in `.env` or as environment variables. They take effect at process startup.

---

## Log Events Reference

| Event (`event` field) | Level | Trigger | Key fields |
|---|---|---|---|
| `turn_start` | INFO | Start of each LLM turn | `agent`, `turn`, `model`, `in_tokens` (estimated) |
| `tool_start` | INFO | Model decides to call a tool | `agent`, `turn`, `model`, `tool`, `tool_input` (truncated 200 chars) |
| `tool_done` | INFO / WARN | Tool execution completes | `agent`, `turn`, `model`, `tool`, `elapsed_s`, `ok` |
| `usage_stats` | INFO | LLM turn completes (real token counts) | `agent`, `turn`, `model`, `in_tokens`, `out_tokens`, `cache_r`, `cache_w`, `tps`, `cost_usd` |
| `compact` | INFO | Auto-compaction triggered | `agent`, `turn`, `tokens_before`, `tokens_after` |
| `task_done` | INFO | Full task completes | `agent`, `turn`, `response_chars` |
| `exception` | ERROR | Unhandled exception or timeout | `agent`, `exc_type`, `exc_msg` + full traceback |

Level is `WARN` for `tool_done` when `is_error=True` (tool ran but returned an error), `ERROR` for unhandled exceptions.

---

## Human-Readable Format

```
{timestamp} [{LEVEL}] [{agent:<10}] {message}
```

Annotated example — master spawns planning, planning runs 2 turns:

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)

# Master receives "build me a CLI tool" task
2026-04-12 14:03:07 [INFO ] [master    ] Turn 0 start | model=claude-sonnet-4-6 est_tokens=4210
2026-04-12 14:03:09 [INFO ] [master    ] Tool file_read | input={'path': 'app/agents/planning/NOTES.MD', 'truncate': ...}
2026-04-12 14:03:09 [INFO ] [master    ] Tool file_read done | elapsed=0.041s ok
2026-04-12 14:03:10 [INFO ] [master    ] Tool spawn_agent | input={'agent_name': 'planning', 'task': 'Decompose the task...'}
2026-04-12 14:03:11 [INFO ] [master    ] Tool spawn_agent done | elapsed=1.204s ok
2026-04-12 14:03:11 [INFO ] [master    ] Usage turn=0 | in=1832 out=284 cache_r=941 cache_w=0 tps=43.2 cost=$0.000812
2026-04-12 14:03:11 [INFO ] [master    ] Task done | turns=1 response_chars=412

# Planning subprocess starts (its stderr goes to OUTPUT.MD)
2026-04-12 14:03:14 [INFO ] [planning  ] Turn 0 start | model=claude-sonnet-4-6 est_tokens=2890
2026-04-12 14:03:16 [INFO ] [planning  ] Tool file_write | input={'path': 'app/agents/builder/TASK.MD', 'content': '---\nst...'}
2026-04-12 14:03:16 [INFO ] [planning  ] Tool file_write done | elapsed=0.012s ok
2026-04-12 14:03:17 [INFO ] [planning  ] Usage turn=0 | in=2201 out=441 cache_r=0 cache_w=2201 tps=38.7 cost=$0.001320
# Planning continues to a second turn (model didn't stop_end_turn yet)
2026-04-12 14:03:17 [INFO ] [planning  ] Turn 1 start | model=claude-sonnet-4-6 est_tokens=3100
2026-04-12 14:03:18 [INFO ] [planning  ] Usage turn=1 | in=2910 out=52 cache_r=2201 cache_w=0 tps=51.0 cost=$0.000204
2026-04-12 14:03:18 [INFO ] [planning  ] Task done | turns=2 response_chars=87

# Auto-compaction triggered on a long-running agent
2026-04-12 14:08:52 [INFO ] [builder   ] Compact auto | tokens 168432→2910 (saved 98%)

# Tool error (tool ran but returned is_error=True)
2026-04-12 14:09:01 [WARN ] [builder   ] Tool shell_exec done | elapsed=5.203s ERROR

# Unhandled exception
2026-04-12 14:09:01 [ERROR] [builder   ] Exception PermissionError | [Errno 13] Permission denied: '/etc/hosts'
Traceback (most recent call last):
  File "app/agents/base/__init__.py", line 850, in run_stream_with_tools
    ...
PermissionError: [Errno 13] Permission denied: '/etc/hosts'
```

---

## JSON-Lines Format

One JSON object per line. Use `event` field to filter by event type in log aggregators.

Schema:

| Field | Type | Always present | Description |
|---|---|---|---|
| `ts` | string | ✓ | ISO 8601 timestamp (second precision) |
| `level` | string | ✓ | `INFO`, `WARNING`, `ERROR` |
| `logger` | string | ✓ | Logger name (`app.agents.base`) |
| `message` | string | ✓ | Human-readable message |
| `agent` | string | agent events | Agent name (`master`, `planning`, ...) |
| `event` | string | agent events | Event type (see reference table above) |
| `turn` | int | most events | 0-based turn index |
| `model` | string | most events | Model identifier |
| `tool` | string | tool events | Tool name |
| `tool_input` | string | `tool_start` | Truncated repr of tool input (≤200 chars) |
| `elapsed_s` | float | `tool_done` | Execution time in seconds |
| `ok` | bool | `tool_done` | `false` if tool returned an error |
| `in_tokens` | int | `turn_start`, `usage_stats` | Input tokens (estimated at turn start, real at usage) |
| `out_tokens` | int | `usage_stats` | Output tokens |
| `cache_r` | int | `usage_stats` | Cache read tokens |
| `cache_w` | int | `usage_stats` | Cache creation tokens |
| `tps` | float | `usage_stats` | Tokens per second |
| `cost_usd` | float | `usage_stats` | Estimated turn cost in USD |
| `tokens_before` | int | `compact` | Tokens before compaction |
| `tokens_after` | int | `compact` | Tokens after compaction |
| `response_chars` | int | `task_done` | Total response character count |
| `exc_type` | string | `exception` | Exception class name |
| `exc_msg` | string | `exception` | Exception message |
| `exc_text` | string | `exception` | Full formatted traceback |

Example output for the same session shown above:

```json
{"ts": "2026-04-12T14:03:07Z", "level": "INFO", "logger": "app.agents.base", "agent": "master", "event": "turn_start", "turn": 0, "model": "claude-sonnet-4-6", "in_tokens": 4210, "message": "Turn 0 start | model=claude-sonnet-4-6 est_tokens=4210"}
{"ts": "2026-04-12T14:03:09Z", "level": "INFO", "logger": "app.agents.base", "agent": "master", "event": "tool_start", "turn": 0, "model": "claude-sonnet-4-6", "tool": "file_read", "tool_input": "{'path': 'app/agents/planning/NOTES.MD'...", "message": "Tool file_read | input={'path': 'app/agents/planning/NOTES.MD'..."}
{"ts": "2026-04-12T14:03:09Z", "level": "INFO", "logger": "app.agents.base", "agent": "master", "event": "tool_done", "turn": 0, "model": "claude-sonnet-4-6", "tool": "file_read", "elapsed_s": 0.041, "ok": true, "message": "Tool file_read done | elapsed=0.041s ok"}
{"ts": "2026-04-12T14:03:11Z", "level": "INFO", "logger": "app.agents.base", "agent": "master", "event": "usage_stats", "turn": 0, "model": "claude-sonnet-4-6", "in_tokens": 1832, "out_tokens": 284, "cache_r": 941, "cache_w": 0, "tps": 43.2, "cost_usd": 0.000812, "message": "Usage turn=0 | in=1832 out=284 cache_r=941 cache_w=0 tps=43.2 cost=$0.000812"}
{"ts": "2026-04-12T14:03:11Z", "level": "INFO", "logger": "app.agents.base", "agent": "master", "event": "task_done", "turn": 0, "response_chars": 412, "message": "Task done | turns=1 response_chars=412"}
{"ts": "2026-04-12T14:08:52Z", "level": "INFO", "logger": "app.agents.base", "agent": "builder", "event": "compact", "turn": 3, "tokens_before": 168432, "tokens_after": 2910, "message": "Compact auto | tokens 168432→2910 (saved 98%)"}
{"ts": "2026-04-12T14:09:01Z", "level": "WARNING", "logger": "app.agents.base", "agent": "builder", "event": "tool_done", "turn": 4, "tool": "shell_exec", "elapsed_s": 5.203, "ok": false, "message": "Tool shell_exec done | elapsed=5.203s ERROR"}
{"ts": "2026-04-12T14:09:01Z", "level": "ERROR", "logger": "app.agents.base", "agent": "builder", "event": "exception", "exc_type": "PermissionError", "exc_msg": "[Errno 13] Permission denied: '/etc/hosts'", "exc_text": "Traceback (most recent call last):\n  ...", "message": "Exception PermissionError | [Errno 13] Permission denied: '/etc/hosts'"}
```

---

## File Structure

```
app/
  config/
    settings.py                   # + log_level, log_file, log_json, log_agent_activity
  backend/
    logging_config.py             # NEW: setup_logging(), _HumanFormatter, _JsonFormatter
    main.py                       # + setup_logging() as first call in lifespan()
  agents/
    base/
      __init__.py                 # + module logger, _calc_turn_cost, 7 log call sites
      runner_entry.py             # + setup_logging() at top of main()
  cli/
    main.py                       # + --log-level option on backend command

docs/
  design/
    logging.md                    # THIS FILE
```

---

## Configuration Examples

**Default (human-readable, INFO, stderr only):**
```env
# .env — nothing needed, defaults work
```

**JSON output to file (for log aggregators):**
```env
LOG_JSON=true
LOG_FILE=logs/yapoc.log
LOG_LEVEL=INFO
```

**Verbose debugging:**
```env
LOG_LEVEL=DEBUG
```

**Disable agent activity logging:**
```env
LOG_AGENT_ACTIVITY=false
```

**Command-line override (no .env change needed):**
```bash
poetry run yapoc backend --log-level DEBUG
LOG_JSON=true poetry run yapoc backend
```

---

## Gotchas & Limitations

- **Subprocess vs server logs are not unified streams.** Master (in-process) logs go to the terminal. Subprocess agents (planning, builder, etc.) log to their own `stderr`, which `SpawnAgentTool` redirects to `app/agents/<name>/OUTPUT.MD`. To see subprocess agent logs in real time, tail that file: `tail -f app/agents/planning/OUTPUT.MD`.

- **Tool timing uses tool name as dict key.** If a model calls the same tool twice in one turn simultaneously (parallel `asyncio.gather`), the second start time overwrites the first. This is unlikely in practice — tools in the same turn typically have different names. If it happens, the elapsed time for the first call will be incorrect.

- **TextDelta is never logged.** Response text chunks are too verbose to log individually. Use `Task done | response_chars=N` to know how much text was generated. Full text is written to `RESULT.MD`.

- **`_SETUP_DONE` flag.** `setup_logging()` only runs once per process. In test environments that import multiple modules in the same process, call `from app.backend.logging_config import _SETUP_DONE; logging_config._SETUP_DONE = False` between tests if you need fresh handler state.

- **Uvicorn's own log level is also set** when using `yapoc backend --log-level`. Passing `--log-level debug` to uvicorn will cause uvicorn access logs and startup messages to appear at DEBUG verbosity too.

---

*Document version: 1.0 — Created 2026-04-12*
