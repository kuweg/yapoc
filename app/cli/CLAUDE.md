# app/cli — Typer CLI & Interactive REPL

## Files
- `main.py` — Typer app, REPL loop, server lifecycle
- `renderer.py` — `TurnRenderer` (Rich Live streaming display) + `AgentPollState`
- `sessions.py` — JSONL session persistence

## Commands
```bash
yapoc start|stop|restart       # server lifecycle (uvicorn via Popen + .yapoc.pid)
yapoc status|ping              # health check
yapoc chat [message]           # one-shot or enter REPL if no message
yapoc                          # enter REPL directly
yapoc agents list|status
yapoc models list|info
```

## REPL features
- **`!command`** — bash passthrough
- **`@file`** — inlines file contents into message (tab-completed from project root)
- **`/command`** — slash commands (tab-completed): `/help /start /stop /restart /status /ping /agents /model /sessions /continue /resume [id] /compact [focus] /cost /diff /copy /export [file] /clear /exit`
- **Sub-agent result injection**: on each turn, `_collect_agent_results()` scans all agent TASK.MD files for `assigned_by: master` + `consumed_at: ""` + `status: done/error`. Results are prepended to the user message as a system notification.
- **RESUME.MD**: populated on clean exit with pending/running tasks; injected as context on next REPL start.

## Approval gate (safety_mode in settings)
| Mode | Behavior |
|---|---|
| `"interactive"` | Prompts y/n for CONFIRM-tier tools |
| `"auto_approve"` | No gate (all tools execute) |
| `"strict"` | All CONFIRM-tier tools blocked |

Gate is only constructed in the CLI. HTTP `/task/stream` has no gate.

## Retry logic
`_send_to_agent` retries on API overload up to 4 times: waits 5s / 15s / 30s / 60s.

## TurnRenderer (renderer.py)
Rich `Live` with `transient=True` — output disappears when Live stops. `_send_to_agent` reprints the final output permanently after streaming ends.

State machine: `thinking → streaming → tool_running → thinking...`

Shows up to 12 tool groups; older collapsed as `… N earlier tools`. Shows agent panel (Rich table) when 2+ sub-agents are active.

## AgentPollState (renderer.py)
Shared thread-safe state polled every 2s. Tracks active agents from STATUS.json. 3-second grace for `terminated` agents before hiding. Used by both the renderer and the prompt_toolkit bottom toolbar.

## Cost tracking (renderer.py — calc_cost)
Anthropic cache pricing:
- Cache writes: 1.25× input rate
- Cache reads: 0.1× input rate
- Prices from `app.utils.adapters.models.ALL_PRICING`

`print_status_line()` — shows model, tokens/sec, turn cost, session cost, color-coded context bar.

## Sessions (sessions.py)
- Storage: `app/agents/master/sessions/{id}.jsonl`
- Session ID format: `YYYYMMDD-HHMMSS-{6hex}`
- Session name: first 60 chars of first user message
- REPL history: `app/agents/master/.repl_history`

## Gotchas
- Session file stores the *original* user message — not the version with injected sub-agent results
- `_send_to_agent` appends user message to history before streaming; pops it on error
- Markdown auto-detection is heuristic: checks if response starts with `#`, `-`, `*`, or contains code fences
- `_compact_history` calls `master_agent._compact_messages()` directly (bypasses tool loop)
