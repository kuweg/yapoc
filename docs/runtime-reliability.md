# Runtime reliability and task progress

Master checks delegated work for at most `MASTER_WAIT_TIMEOUT` seconds (default
2), then releases the conversation. The child retains its original execution
budget. A durable notification schedules the follow-up in the same conversation.
The runtime ends the waiting turn deterministically, avoiding repeated model
calls to wait on the same child. `0` restores the previous uncapped wait policy.

Conversation, Tasks and Observability show shared task progress: queued, running,
waiting, interrupted, blocked, failed, completed or cancelled. The queue's raw
`status` still describes one execution turn; the `progress` object also tracks
its delegated work and follow-up delivery. Completing a handoff turn does not
mean the original work is complete. Progress includes last activity, child names,
recovery count and the next action. HTTP and websocket responses use the same
projection. Result cards refresh their progress from the shared task feed.

## Diagnostics

Open **Observability → Runtime diagnostics → Run diagnostics**. It checks project
visibility, DNS, PyPI HTTPS, fetch dependency imports, the managed Python/Poetry
environment and backend task storage. The execution probes use `execute_code`
and `shell_exec`, including their normal OS boundary. Reports contain fixed safe
messages, never raw process errors or credentials. Public connectivity checks
run only on request; no scheduled probes are introduced.

`GET /health/runtime` reports the last check plus process start time and whether
backend or worker code needs a restart. `POST /health/runtime/check` runs probes.
Browser routes use the normal `/api` prefix. A network-disabled configuration
correctly reports failed DNS/HTTPS checks; it does not prevent backend startup.

## Restart recovery

Restart with `poetry run yapoc restart`. Managed launches allow three seconds
for open connections to drain before entering shutdown; the CLI allows fifteen
seconds for graceful termination before escalation. Recovery retains the queue ID, session,
original request, durable tool events and transcript checkpoint. It records a
bounded recovery history, clears stale execution timestamps, and instructs the
agent to inspect unknown tool outcomes before repeating side effects.

`RESTART_RECOVERY_LIMIT` defaults to 3 automatic recoveries per task. Further
restarts leave the task blocked for review instead of creating an endless retry
loop. A surviving child process also blocks recovery to avoid duplicate work.
Interrupted/failed/blocked tasks expose **Resume from checkpoint**, backed by
`POST /tasks/{id}/recover`. Review retained output before using this action.
Recovery is not a transactional guarantee for external side effects; agents
must reconcile an action whose result was not durably recorded.

## Validation

```sh
poetry run pytest tests/ app/backend/tests/ -q
pnpm --dir app/frontend build
poetry run python scripts/check_runtime_browser.py --dist app/frontend/dist
```

The automated backend tests mock public connectivity. The browser check uses
fixtures and tests desktop/mobile presentation and explicit diagnostic requests.
