# Health Monitoring & Crash Tracking

## Overview

YAPOC captures all subprocess output (server and agents) to markdown files, writes structured crash reports, enriches HEALTH.MD with full tracebacks, and runs a Doctor agent that monitors everything on a cron schedule.

## New Files in Agent Schema

| File | Purpose | Written by |
|------|---------|------------|
| `OUTPUT.MD` | Captured stdout/stderr from agent subprocess | Capture harness (spawn) |
| `CRASH.MD` | Structured crash reports (exit code, traceback, context) | Capture harness / runner_entry.py |
| `SERVER_OUTPUT.MD` | Uvicorn stdout/stderr (master/ only) | Server start code |
| `SERVER_CRASH.MD` | Server crash reports (master/ only) | Exit watcher thread |
| `HEALTH_SUMMARY.MD` | Rolling system health report (doctor/ only) | Doctor agent |

## CRASH.MD Format

```markdown
## Crash [PID 12345] at 2026-03-13 14:25:44
- entity: planning
- exit_code: 1
- restart_count: 2

### Traceback
\```
Traceback (most recent call last):
  File "app/agents/base/runner_entry.py", line 35, in main
    ...
\```
---
```

## Output Capture

### Server Output
- `yapoc start` and `server_restart` tool both redirect uvicorn stdout/stderr to `master/SERVER_OUTPUT.MD`
- A daemon thread (`server_exit_watcher`) monitors the process and writes crash reports on non-zero exit

### Agent Output
- `spawn_agent` tool and `/agents/{name}/spawn` endpoint redirect agent subprocess output to `{agent}/OUTPUT.MD`
- A daemon thread (`agent_exit_watcher`) monitors the process and writes crash reports on non-zero exit

### Top-Level Crash Handler
- `runner_entry.py` wraps `asyncio.run()` in try/except and writes full tracebacks to CRASH.MD before exiting

## HEALTH.MD Enrichment

All exception handlers in BaseAgent (`run()`, `run_stream()`, `run_stream_with_tools()`) now include `traceback.format_exc()` in HEALTH.MD entries.

## Log Rotation

`rotate_output_log()` in `app/utils/crash.py` truncates the oldest half of an OUTPUT.MD when it exceeds `log_max_size_kb` (default: 512 KB).

## Doctor Agent

### Role
Autonomous health monitor that runs on a cron schedule (default: every 5 minutes). Scans all agents' HEALTH.MD, CRASH.MD, OUTPUT.MD, and server logs.

### Output
Writes `HEALTH_SUMMARY.MD` in its own directory with:
- Per-agent status (OK / issues)
- Error counts and last few error lines
- Crash counts

### API
`GET /health/summary` — returns the latest HEALTH_SUMMARY.MD content.

### Configuration
- `doctor_interval_minutes` in settings (default: 5)
- Uses `claude-haiku-4-5-20251001` model, low temperature (0.2)
- Tools: `file_read`, `file_list`, `read_agent_logs`, memory tools

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `log_max_size_kb` | 512 | OUTPUT.MD size cap before rotation |
| `doctor_interval_minutes` | 5 | Doctor cron frequency |
