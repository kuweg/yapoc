# Stale Task Watchdog

The stale task watchdog automatically detects tasks that have been running longer than expected.

## Configuration

- **`stale_task_threshold_seconds`** (default: `600`): Tasks running longer than this many seconds are considered stale. Set this in `app/config/agent-settings.json`.

## API

- `GET /api/tasks/stale` — Returns a list of currently stale tasks.

Response format:
```json
[
  {
    "task_id": "abc-123",
    "agent_name": "builder",
    "elapsed_seconds": 750.5,
    "status": "running"
  }
]
```

## Dashboard

The **Stale Tasks** tab in the dashboard shows all currently stale tasks, auto-refreshing every 30 seconds.

## Automation

A cron job runs every 10 minutes to scan for stale tasks and append findings to the doctor agent's health log.

## Doctor Agent Integration

The doctor agent's `_check_stale_tasks()` method reads `stale_task_threshold_seconds` from `app/config/agent-settings.json` to determine the staleness threshold.
