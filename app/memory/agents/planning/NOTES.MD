
## 8-Feature Hermes Gap Batch Plan
# 2026-09-01 — 8-Feature Hermes gap batch — Implementation Plan

Ordered decomposition (dependency: 3 → 1,2,4,5,6 → 7 → 8).

FEATURE 3 (LAY FIRST — foundation): Structured result contract.
- New helper app/agents/base/result.py: schema {status, summary, files[], artifacts[]} + coercion of free-text → {status, summary} when not JSON (backward compat).
- Used by delegation tools (1) and child budget (2).

FEATURE 1: delegate_task runtime tool (ANY agent can fan out mid-turn).
- Add tool in app/utils/tools/delegation.py next to SpawnAgentTool/WaitForAgentTool.
- Reuse existing peer-delegation check (_parse_delegation_targets, _UNRESTRICTED_SPAWNERS), checkpoint, concurrency cap.
- Returns structured result routed into calling agent's context (depends on F3 return shape). Enforce allowed_tools whitelist.

FEATURE 2: Child-side token budget.
- parent sets per-child token/$ cap in spawn/delegate call; enforced in app/agents/base/runner.py run loop + BaseAgent (app/agents/base/__init__.py).
- child hard-stops + returns partial results when cap exhausted. Integrates with cost_governor.is_autonomous_budget_exhausted so it cannot exceed global daily budget.

FEATURE 4: Time-based memory decay.
- settings memory_decay_days (exists: memory_max_age_days=7). Archive old MEMORY.md entries to cold store (data/memory_archive/ or librarian). Trigger: cron tick/startup/librarian sweep. Preserve embedded index or re-index lazily.

FEATURE 5: Survivable session context (CONVERSATION.md).
- Freeze per-session working context to CONVERSATION.md at session complete/restart; restore on reload. Beyond RESUME.md agent-state recovery.

FEATURE 6: Negative knowledge store.
- New section in shared KNOWLEDGE.md (or data/negative_knowledge.md), entries {approach, why_rejected, date, replaced_by}. Wire librarian to route failed/abandoned approaches. Seed with rejected approaches (lmstudio for some agents, dead claude-haiku model).

FEATURE 7: Budget-aware autonomous mode (PARTLY EXISTS).
- cost_governor.py already has is_autonomous_budget_exhausted(), get_autonomous_spend_today(). dispatcher._check_goals already gate. Extend main.py _cron_tick + goals runner + doctor to coordinate against ONE daily budget (not per-job). Add settings.daily_autonomous_budget_usd.

FEATURE 8: Escalation ladder on repeated failure.
- Track consecutive_failures per cron job in cron state (data/cron_runs.json or new data/cron_failures.json). On threshold (settings) → disable job + page user (Telegram/UI). Health-alert: 'agent fails twice in a row' (user already wants this).

KEY FILES:
- app/utils/tools/delegation.py — F1, F2 (cap in call), F3 return
- app/agents/base/result.py — F3 (NEW)
- app/agents/base/runner.py — F2
- app/agents/base/__init__.py (BaseAgent) — F2
- app/config/settings.py — F2,F4,F7,F8 config keys
- app/config/agent-settings.json — add delegate_task to agent tool lists
- app/utils/cost_governor.py — F7
- app/backend/main.py _cron_tick — F8 (track failures), F7 (budget gate)
- app/utils/goal_proposer.py — F7
- shared KNOWLEDGE.md — F6
- librarian agent — F6 wiring, F4 sweep
- data/memory_archive/ — F4 cold store
- CONVERSATION.md — F5

Backend must restart after each feature group's code mutation (server_restart via builder).


## Features B+D (UI observability)
2026-09-01 — Features B+D sequential re-delegation: Task A (backend nudge) now CONFIRMED landed. agents.py has perform_nudge helper + /{name}/nudge route; websocket.py has agent_action branch. Task B (AgentCard nudge button + nudgeAgent client fn) had been lost in parallel collision — need to confirm whether it has since been re-delegated and landed. Remaining: verify Task B frontend, then Feature A (if any) complete.
