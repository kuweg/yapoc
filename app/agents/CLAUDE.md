# app/agents — Agent Overview

## Agent hierarchy
```
Master  →  Planning  →  Builder / Keeper / Cron  (spawned as subprocesses)
        →  Doctor                                 (APScheduler, pure Python)
        →  ModelManager                           (APScheduler, pure Python)
        →  <ephemeral>                            (temporary, auto-deleted)
```

## File schema (every agent directory)
| File | Purpose | Written by |
|---|---|---|
| `PROMPT.MD` | System prompt — agent identity | Developer / Builder |
| `TASK.MD` | Current task + frontmatter status | Assigner (writes) / Runner (updates) |
| `MEMORY.MD` | Append-only: `[datetime] task: ... \| response: ...` | Self |
| `NOTES.MD` | Persistent knowledge / config fallback | Self |
| `HEALTH.MD` | Error log: `[datetime] ERROR: ...` | Self / Doctor |
| `CONFIG.md` | YAML: adapter, model, temperature, tools, runner | Developer / Keeper |
| `STATUS.json` | Live runner state (spawning/idle/running/terminated) | AgentRunner |
| `CRASH.MD` | Crash reports from subprocess exits | AgentRunner / crash.py |

## Config resolution order
`CONFIG.md` YAML → `NOTES.MD [config]` block → `settings` defaults

## Implemented agents
| Agent | Type | Adapter | Note |
|---|---|---|---|
| `master` | singleton | anthropic/sonnet-4-6 | CLI + HTTP entry point |
| `planning` | subprocess | anthropic/sonnet-4-6 | Task decomposition |
| `builder` | subprocess | anthropic/sonnet-4-6 | File/code creation |
| `doctor` | APScheduler | openai/gpt-4o-mini | Needs `OPENAI_API_KEY` |
| `model_manager` | APScheduler | anthropic/haiku-4-5 | Config auditor |
| `keeper` | stub | — | Config management |
| `cron` | stub | — | Scheduled tasks |

## TASK.MD has two formats
**Raw** (used by `BaseAgent.run*` directly):
```
<plain task text>
```

**Structured** (used by `SpawnAgentTool` + `AgentRunner`):
```yaml
---
status: pending
assigned_by: master
task_id: ...
consumed_at: ""
---

## Task
<description>

## Context
<context>

## Result

## Error
```
Never mix the two. Master/CLI use raw. Spawned subprocesses use structured.

## Adding a new agent
1. Create `app/agents/<name>/` with all 6 markdown files + `agent.py` + `__init__.py`
2. Use `CreateAgentTool` or copy from an existing thin subclass
3. Protected names (can't delete): `master, planning, builder, keeper, cron, doctor, base, model_manager`
