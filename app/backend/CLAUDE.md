# app/backend — FastAPI Backend

## Entry point: `main.py`
FastAPI app with APScheduler lifespan. Start with:
```bash
poetry run yapoc start   # wraps: uvicorn app.backend.main:app
```

## Routes

### `/task` (tasks.py)
| Method | Path | Notes |
|---|---|---|
| `POST` | `/task` | Blocking, returns `TaskResponse` |
| `POST` | `/task/stream` | SSE stream, event types: `text`, `tool_start`, `tool_done`, `usage_stats` |

**Important**: all tools execute automatically — there is no approval gate.

### `/agents` (agents.py)
| Method | Path | Notes |
|---|---|---|
| `GET` | `/agents` | List all agent statuses |
| `GET` | `/agents/{name}/memory` | Raw MEMORY.MD content |
| `GET` | `/agents/{name}/health` | Raw HEALTH.MD content |
| `GET` | `/agents/{name}/status` | STATUS.json + PID liveness check |
| `POST` | `/agents/{name}/spawn` | Starts subprocess via `Popen` |
| `POST` | `/agents/{name}/kill` | Sends SIGTERM to PID in STATUS.json |
| `POST` | `/agents/{name}/restart` | Clears TASK.MD + HEALTH.MD — does NOT kill subprocess |

### `/health` (health.py)
| Method | Path | Returns |
|---|---|---|
| `GET` | `/health` | `{status, uptime}` |
| `GET` | `/ping` | UTC timestamp |
| `GET` | `/health/summary` | Contents of `doctor/HEALTH_SUMMARY.MD` |

## Cross-process IPC services
Subprocess agents (`planning`, `builder`, `keeper`, `cron`, `doctor`, `model_manager`) can't push WebSocket events directly — they hold no client connections. Three services close that gap by polling/watching shared state from the *server* process:

| Service | Watches | Forwards to |
|---|---|---|
| `notification_poller` | each agent's TASK.MD frontmatter `## Result` / `## Error` | `notification_queue` → master notification watcher |
| `session_event_relay` | `data/sessions/*/events.jsonl` (watchdog inotify) | `ws_manager.push_session_event` per line |

Without `session_event_relay`, sub-agent thinking/tool/text deltas write to JSONL on disk but never reach the UI — only master's events flow through. The relay seeds offsets to EOF on startup so it never replays old backlog.

## APScheduler background jobs
Registered at startup in `main.py` lifespan:
- **Doctor**: every `settings.doctor_interval_minutes` (5 min) — `doctor_agent.run_health_check()`
- **Cron agent**: every `settings.cron_interval_minutes` (10 min) — spawns cron subprocess if not running
- **Model Manager**: every `settings.model_manager_interval_hours` (24h) — `model_manager_agent.run_model_audit()`

Initial fire-and-forget: 5s / 10s / 15s after startup via `loop.call_later`.

## AgentService (services/__init__.py)
Data access layer used by routers.

- `get_all_statuses()` — iterates `AGENTS_DIR`, instantiates `BaseAgent` per dir, merges with STATUS.json. Status logic: `"error"` if health_errors > 0, `"busy"` if has_task, else `"idle"`.
- `restart_agent(name)` — writes `""` to TASK.MD and HEALTH.MD only. Does NOT kill the running subprocess.

## AgentStatus model
```python
class AgentStatus(BaseModel):
    name: str; status: str; model: str; has_task: bool
    memory_entries: int; health_errors: int
    process_state: str = ""; pid: int | None = None; task_summary: str = ""
```

## Gotchas
- `restart_agent` clears files but leaves subprocess running — the agent continues with empty state
- `_read_status_json` + `_pid_alive` helpers are duplicated between `services/__init__.py` and `routers/agents.py`
- All singletons (`master_agent`, `doctor_agent`, `model_manager_agent`) are imported at module level — they share state across requests
