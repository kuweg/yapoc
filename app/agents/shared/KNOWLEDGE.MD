# Shared Knowledge Base

## Entry: convention
- **Source:** master
- **Time:** 2026-04-13 19:41
- **Content:** YAPOC uses Poetry for dependency management

## Entry: discovery
- **Source:** master
- **Time:** 2026-04-13 19:58
- **Content:** formatter.py provides date formatting utilities at app/projects/utils/formatter.py

[2026-04-13 20:32] category: discovery | source: test-learnings (promoted)
### Rule: Always validate inputs
- context: File operations
- action: Check path exists before read
- confidence: high

## Entry: decision
- **Source:** model_manager
- **Time:** 2026-04-13 20:52
- **Content:** Model optimization implementation completed 2026-04-13: cron downgraded to claude-3-haiku-20240307 (75% cost reduction), keeper & doctor migrated from lmstudio to cloud Haiku, master updated to sonnet-4-6 for catalog compliance. Total estimated savings: 72% (~$0.22/session). All changes reversible.

## Entry: decision
- **Source:** model_manager
- **Time:** 2026-04-13 20:57
- **Content:** Model optimization implementation completed 2026-04-13 21:45: master (sonnet-4-5→4-6, catalog compliance), cron (haiku-4-5→3-haiku, 75% cost reduction), keeper & doctor (haiku-4-5→3-haiku, cost reduction). Total estimated savings: 72% (~$0.22/session, $287.52/year). All changes in app/config/agent-settings.json, fully reversible.

## Entry: decision
- **Source:** keeper
- **Time:** 2026-04-13 21:30
- **Content:** Cron agent's `delegation_targets` list updated 2026-04-13 to include 'doctor' agent, alongside 'builder' and 'keeper'. This allows the cron agent to delegate tasks to the doctor agent when needed.

## Entry: decision
- **Source:** master
- **Time:** 2026-04-13 21:31
- **Content:** Cron agent's delegation_targets now includes: builder, keeper, doctor, and master. Updated 2026-04-13.
