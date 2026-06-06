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

## Entry: discovery
- **Source:** researcher
- **Time:** 2026-05-17 13:04
- **Content:** LiveBench research report saved at app/projects/research/livebench_report.md. LiveBench is a contamination-limited LLM benchmark with 7 categories, 23 tasks, monthly-updated questions, objective scoring (no LLM judge), accepted as ICLR 2025 Spotlight. Top model: o4 Mini High at 87.3%. Team of 18 from Abacus.AI, NYU, NVIDIA, UMD, USC.

## Entry: convention
- **Source:** master
- **Time:** 2026-05-24 14:10
- **Content:** Librarian agent is the central memory curator. Any agent can spawn librarian with a thought/observation to store. Librarian classifies and routes it to the correct store: agent_memory (episodic), learning (reusable patterns), note (working context), project_knowledge (shared KNOWLEDGE.MD), or user_profile/history. Use librarian instead of direct memory_append when the thought has broader value or unclear classification.

## Entry: decision
- **Source:** master
- **Time:** 2026-05-25 13:15
- **Content:** Librarian redesigned as Memory Curator + Summarizer with two modes: Mode A (memory curation — classifies thoughts into agent_memory/learning/note/project_knowledge/user_profile/history and routes them) and Mode B (summarization). `notify_parent` tool added to librarian tools in agent-settings.json and CONFIG.yaml. Master PROMPT.MD updated with Memory Curation Protocol. Librarian description updated in master prompt.

## Entry: discovery
- **Source:** master
- **Time:** 2026-05-18 19:42
- **Content:** Prompt audit of 9 agent prompts found rough edges in all agents. Key findings: Builder references non-existent `create_agent`/`delete_agent` tools; Cron missing peer delegation constraints; Doctor references `spawn_agent planning` but Planning may not be a delegation target; Evaluator references non-existent `get_recent_signals()`; Keeper has sandbox loophole in file access rules; Librarian hardcodes "ONE turn" assumption; Model Manager references non-existent `update_agent_config`/`check_model_availability`/`list_models`; Planning references non-existent `add_task_trace`; Researcher references non-existent `fetch_page`. Full audit at app/agents/master/NOTES.MD.

## Entry: decision
- **Source:** master
- **Time:** 2026-05-25 11:42
- **Content:** Master agent model changed from deepseek/deepseek-chat to moonshot/kimi-k2.6 in agent-settings.json. Master task_timeout set to 900s (user-approved 2026-05-23). Master CONFIG.yaml still shows deepseek-chat with task_timeout: 0 (unbounded) but agent-settings.json is authoritative at runtime. This is a significant model upgrade from the earlier sonnet-4-6/deepseek-chat era.

## Entry: discovery
- **Source:** master
- **Time:** 2026-05-25 11:42
- **Content:** Comprehensive master agent audit report exists at `docs/master-audit.md`. Covers 3 systemic problems: (1) Master going idle unexpectedly — Redis watcher drops notifications when master is running (critical bug at main.py:327-329), (2) Turn limitations — task_timeout: 300s is primary limiter, notification_max_turns documented but not implemented, (3) Queue message problems — NotifyParentTool always delivers to both Redis + notification_queue causing dual delivery race. Full fix recommendations included in the report.

## Entry: decision
- **Source:** user (memory sweep)
- **Time:** 2026-05-25 11:44
- **Content:** User specified PostgreSQL as the main database (not SQLite). All API responses must be under 200ms. Rate limiting required on all public endpoints. Redis for caching (not in-memory). Log retention: 30 days max. Daily backup at 3am. These are project-wide technical constraints.

## Entry: convention
- **Source:** user (memory sweep)
- **Time:** 2026-05-25 11:44
- **Content:** Coding convention: snake_case over camelCase. Concurrency pattern: async/await over threading. JSON formatting: compact over pretty-printed. Agent prompts must stay under 4000 tokens. Use Claude for all agents except cron.
