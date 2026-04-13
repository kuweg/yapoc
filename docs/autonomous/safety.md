# Safety — Autonomous Guardrails

When the system runs 24/7 without a human watching, safety is not optional.
This document defines the boundaries.

---

## The core tension

Claude Code solves safety by asking the user. Every CONFIRM-tier tool gets
a prompt: "Allow shell_exec: pytest?" The user is always there.

OpenClaw solves safety with sandboxing. Non-main sessions run in Docker.
Tool allowlists per session type. The system is always constrained.

YAPOC needs both patterns because it operates in both modes:
- **Interactive:** user is present → ask for approval (Claude Code model)
- **Autonomous:** user is absent → apply policy (OpenClaw model)

---

## Tool risk tiers (existing)

```
RiskTier.AUTO     — always safe to execute (file_read, file_list, notes_read)
RiskTier.CONFIRM  — needs approval (shell_exec, file_delete, file_write to sensitive paths)
```

This tier system already exists. What's missing is the policy engine
that decides what to do with CONFIRM-tier tools when no one is watching.

---

## Approval policy by mode

### Interactive mode (user watching via WebSocket)

```
CONFIRM-tier tool requested
  → push approval_needed event to Chat tab
  → ApprovalDialog shown to user
  → User approves or denies
  → Agent continues or adjusts

Timeout: 60 seconds → tool denied, agent adjusts approach
```

This is the Claude Code model. No change needed.

### Autonomous mode (no WebSocket subscriber)

```
CONFIRM-tier tool requested
  → check autonomous approval policy for this tool + agent + context

Policy options:
  1. auto_approve     → execute immediately (trusted context)
  2. queue            → add to approval queue, agent pauses on this step
  3. deny             → deny the tool, agent must find alternative
  4. escalate         → notify user via Telegram / push notification
```

---

## Autonomous approval policy

Defined per-agent in CONFIG.md:

```yaml
# app/agents/builder/CONFIG.md

autonomous_policy:
  shell_exec:
    # Auto-approve commands matching these patterns
    auto_approve:
      - "poetry run pytest*"
      - "poetry show*"
      - "python -c *"
      - "ls *"
      - "cat *"
      - "wc *"
    # Deny commands matching these patterns (never auto-approve)
    deny:
      - "rm -rf *"
      - "sudo *"
      - "curl * | bash"
      - "pip install *"
    # Everything else: queue for user approval
    default: queue

  file_write:
    auto_approve:
      - "app/projects/*"
      - "app/agents/*/MEMORY.MD"
      - "app/agents/*/NOTES.MD"
      - "app/agents/*/HEALTH.MD"
    deny:
      - ".env*"
      - "*/credentials*"
      - "app/config/settings.py"
    default: queue

  file_delete:
    auto_approve:
      - "app/projects/tmp/*"
      - "/tmp/*"
    default: deny
```

### Policy for Doctor (tighter)

```yaml
# app/agents/doctor/CONFIG.md

autonomous_policy:
  shell_exec:
    auto_approve:
      - "ps aux*"
      - "poetry run pytest*"
    default: deny

  kill_agent:
    auto_approve: [builder, keeper, cron]
    deny: [master, doctor]

  spawn_agent:
    auto_approve: true
    max_per_run: 3

  file_write:
    auto_approve:
      - "app/agents/*/HEALTH.MD"
      - "app/agents/*/HEALTH_SUMMARY.MD"
    default: deny
```

---

## Approval queue

When a CONFIRM-tier tool is queued (neither auto-approved nor denied),
it enters the approval queue:

```json
{
  "id": "approval_abc123",
  "agent": "builder",
  "tool": "shell_exec",
  "input": {"command": "poetry add pyjwt"},
  "task_id": "task_def456",
  "created_at": "2026-04-13T03:22:00Z",
  "status": "pending"
}
```

What happens next depends on context:
- **If the user opens Mission Control:** queued approvals show as a notification badge.
  User approves or denies from a dedicated Approvals panel.
- **If Telegram is configured:** send a message: "Builder wants to run `poetry add pyjwt`.
  Reply /approve or /deny." (This is the OpenClaw DM-style interaction.)
- **If no channel is available:** the agent's task pauses. It resumes when the user
  returns and approves.

### Queue timeout

Items in the approval queue expire after `approval_timeout` (default: 24 hours).
Expired items are auto-denied. The agent receives a denial and adjusts.

---

## Autonomy envelope (per-agent boundaries)

Each agent has hard limits that no policy can override:

```yaml
# Universal limits
max_turns_per_task: 50          # agent cannot reason forever
max_tool_calls_per_turn: 20     # prevents infinite tool loops
max_cost_per_task: $5.00        # hard stop on API spend
task_timeout: 600               # 10 minutes default

# Per-agent sandbox
sandbox_paths:                  # agent can only write within these paths
  builder: [app/projects/, /tmp/yapoc/]
  keeper:  [app/config/, .env, pyproject.toml]
  doctor:  [app/agents/*/HEALTH.MD, app/agents/*/HEALTH_SUMMARY.MD]
  cron:    []                   # cron spawns others, doesn't write directly
```

### What agents cannot do (hard rules, not configurable)

- No agent can modify another agent's PROMPT.MD (identity is developer-controlled)
- No agent can modify `app/config/settings.py` autonomously (config changes require user)
- No agent can push to git (commit is fine, push requires explicit user action)
- Doctor cannot kill Master or itself
- No agent can escalate its own permissions (can't edit its own CONFIG.md autonomy_policy)
- No agent can modify the approval queue directly

---

## Runaway detection

The system watches for agents that consume disproportionate resources:

| Signal | Threshold | Action |
|---|---|---|
| Token cost exceeds 5x estimate | Per-task | Pause agent, alert user |
| Agent turns exceed max_turns | Per-task | Force-stop, mark as error |
| Agent spawns > 10 sub-agents | Per-task | Pause, require approval for more |
| Same tool called > 10 times in a row | Per-turn | Break loop, inject reflection prompt |
| Total daily cost exceeds budget | Global | Pause all autonomous work, user tasks only |

### Daily budget

```yaml
# app/config/settings.py

daily_autonomous_budget: 10.00  # USD — only counts autonomous tasks, not interactive
```

When the budget is hit, the system stops autonomous execution (goals, cron, doctor tasks).
Interactive tasks from the user still work — the user chose to spend.
Budget resets at midnight.

---

## Audit trail

Every autonomous action is logged:

```
[2026-04-13 03:22:00] [AUTONOMOUS] builder: shell_exec auto-approved (matched: "poetry run pytest*")
[2026-04-13 03:22:15] [AUTONOMOUS] builder: file_write auto-approved (path: app/projects/auth/login.py)
[2026-04-13 03:23:01] [AUTONOMOUS] builder: shell_exec QUEUED (command: "poetry add pyjwt")
[2026-04-13 03:25:00] [AUTONOMOUS] doctor: kill_agent auto-approved (target: builder, reason: stale task)
[2026-04-13 04:00:00] [BUDGET] daily autonomous spend: $2.34 / $10.00
```

Written to `data/autonomous_audit.log`. Rotated daily.
Visible in Mission Control's Agents tab under a dedicated audit section.

---

## Summary: who guards what

| Concern | Guardian |
|---|---|
| Tool safety (interactive) | User via approval prompt |
| Tool safety (autonomous) | Autonomous approval policy in CONFIG.md |
| Agent boundaries | Autonomy envelope (sandbox_paths, hard rules) |
| Resource limits | Runaway detection + daily budget |
| System integrity | Hard rules (no PROMPT.MD edits, no self-escalation) |
| Audit | Autonomous audit log + HEALTH.MD entries |
