Plan to implement                                                                   │
│                                                                                     │
│ Agent Families Architecture — Design Analysis                                       │
│                                                                                     │
│ Context                                                                             │
│                                                                                     │
│ YAPOC currently has a flat two-level hierarchy: one global Planning agent           │
│ coordinates all sub-agents (Builder, Keeper, Cron). As the agent count grows and    │
│ tasks become cross-domain (code changes + config changes + health checks            │
│ simultaneously), the flat model creates three concrete problems: (1) token bloat at │
│  the Master level (22 tools on every turn), (2) sequential sub-agent execution      │
│ inside Planning, and (3) no isolation between dev-facing and ops-facing             │
│ knowledge/state. The question is whether grouping agents into domain families with  │
│ their own coordinators fixes these problems cost-effectively.                       │
│                                                                                     │
│ ---                                                                                 │
│ Verdict by Dimension                                                                │
│                                                                                     │
│ 1. Isolation — MARGINAL gain                                                        │
│                                                                                     │
│ Process isolation is already solid: every sub-agent is a separate OS process,       │
│ communicating exclusively through markdown files. No shared memory.                 │
│                                                                                     │
│ The gap is role isolation: Master carries 22 tools and sees the entire system. An   │
│ audit (docs/agent-audit-report.md) flags this as High severity — with 22 tools, the │
│  model can rationalize doing anything itself rather than delegating, which defeats  │
│ the hierarchy.                                                                      │
│                                                                                     │
│ Families fix this: Master would delegate to family planners and hold only ~8 tools  │
│ (delegation + web_search + memory). Each family planner has domain-scoped tools and │
│  NOTES.MD. The Builder no longer needs to know about keeper configs; the Keeper no  │
│ longer needs to know about code structure.                                          │
│                                                                                     │
│ Verdict: Isolation improves meaningfully for Master (22 → 8 tools), marginally for  │
│ sub-agents (already isolated by process boundary).                                  │
│                                                                                     │
│ ---                                                                                 │
│ 2. Token Reduction — MODEST but real                                                │
│                                                                                     │
│ Master's tool schema cost                                                           │
│                                                                                     │
│ ┌────────────────┬───────┬────────────────────────────┐                             │
│ │     Config     │ Tools │ ~Tokens (schema, uncached) │                             │
│ ├────────────────┼───────┼────────────────────────────┤                             │
│ │ Current Master │ 22    │ ~6,600                     │                             │
│ ├────────────────┼───────┼────────────────────────────┤                             │
│ │ Family Master  │ 8     │ ~2,400                     │                             │
│ ├────────────────┼───────┼────────────────────────────┤                             │
│ │ Saving         │       │ ~4,200 per session start   │                             │
│ └────────────────┴───────┴────────────────────────────┘                             │
│                                                                                     │
│ After the first call, Anthropic's prompt caching (already active in                 │
│ AnthropicAdapter) caches tool schemas at 0.1× read cost, so the per-turn saving     │
│ after warmup is small (~$0.0001). The real saving is from Master taking fewer turns │
│  — it delegates earlier instead of self-executing.                                  │
│                                                                                     │
│ The hidden cost: extra LLM layer                                                    │
│                                                                                     │
│ Every task now traverses one extra LLM call (FamilyPlanner). For a simple "edit one │
│  file" task:                                                                        │
│ - Before: Master → Planning → Builder (3 agent hops, ~3 LLM calls minimum)          │
│ - After: Master → DevPlanner → Builder (same 3 hops, similar cost if Planning       │
│ becomes DevPlanner)                                                                 │
│ - Only worse if we add a net-new FamilyPlanner agent above Planning                 │
│                                                                                     │
│ NOTES.MD / MEMORY.MD pollution                                                      │
│                                                                                     │
│ Today all domain knowledge accumulates in Planning's NOTES.MD (4000 char cap). A    │
│ DevPlanner only cares about code conventions; an OpsPlanner only cares about config │
│  patterns. Splitting NOTES.MD by domain keeps context dense and relevant, reducing  │
│ tokens while improving answer quality.                                              │
│                                                                                     │
│ Verdict: 20-30% Master token reduction per session start. Per-turn ongoing savings  │
│ are small due to caching. The bigger win is qualitative (no context pollution       │
│ across domains).                                                                    │
│                                                                                     │
│ ---                                                                                 │
│ 3. Parallel Execution — SIGNIFICANT win, but blocked by missing primitive           │
│                                                                                     │
│ This is the highest-value dimension. Consider a realistic task: "Add feature X      │
│ (code change) and update the deployment config."                                    │
│                                                                                     │
│ Current execution:                                                                  │
│ Planning → builder(feature) → wait → keeper(config) → wait                          │
│ Total: builder_time + keeper_time (sequential). If each takes 2 min, total = 4 min. │
│                                                                                     │
│ With families:                                                                      │
│ Master → DevPlanner(feature)    ──────────────────┐                                 │
│        → OpsPlanner(config)  ──────────────────┐  │                                 │
│                                                ▼  ▼                                 │
│                              wait_for_agents([dev, ops])                            │
│ Total: max(builder_time, keeper_time) = 2 min. 2× speedup on cross-domain tasks.    │
│                                                                                     │
│ This works because each FamilyPlanner is a separate OS process making independent   │
│ outgoing LLM API calls in parallel.                                                 │
│                                                                                     │
│ The critical missing primitive: wait_for_agents                                     │
│                                                                                     │
│ The current wait_for_agent only accepts a single agent name. Master (or any         │
│ planner) cannot express "wait for ALL of these before continuing" without calling   │
│ wait_for_agent sequentially, which re-serializes the work.                          │
│                                                                                     │
│ The wait_for_agents tool is prerequisite for any parallel execution gain, with or   │
│ without families. It accepts a list of agent names and polls all TASK.MD files      │
│ simultaneously, returning when all complete (or any errors).                        │
│                                                                                     │
│ Without it, families give parallel spawning but sequential fanin — no net wall-time │
│  improvement.                                                                       │
│                                                                                     │
│ What parallelism looks like at each scope                                           │
│                                                                                     │
│ ┌────────────────────┬─────────────────────────┬────────────────────────────────┐   │
│ │       Scope        │         Current         │         With families          │   │
│ ├────────────────────┼─────────────────────────┼────────────────────────────────┤   │
│ │ Tools within one   │ asyncio.gather (already │ Same                           │   │
│ │ LLM response       │  parallel)              │                                │   │
│ ├────────────────────┼─────────────────────────┼────────────────────────────────┤   │
│ │ Sub-tasks within   │ Sequential (PROMPT.MD:  │ Still sequential within each   │   │
│ │ Planning           │ spawn→wait→spawn)       │ FamilyPlanner                  │   │
│ ├────────────────────┼─────────────────────────┼────────────────────────────────┤   │
│ │ Cross-domain tasks │ Sequential (one         │ Parallel (two independent      │   │
│ │  (code + config)   │ Planning agent)         │ FamilyPlanner processes)       │   │
│ ├────────────────────┼─────────────────────────┼────────────────────────────────┤   │
│ │ Independent code   │                         │ Still sequential within        │   │
│ │ sub-tasks          │ Sequential              │ DevPlanner (unless DevPlanner  │   │
│ │                    │                         │ also parallelizes)             │   │
│ └────────────────────┴─────────────────────────┴────────────────────────────────┘   │
│                                                                                     │
│ Verdict: Families unlock cross-domain parallelism. Single-domain tasks remain       │
│ sequential.                                                                         │
│                                                                                     │
│ ---                                                                                 │
│ Architecture Design                                                                 │
│                                                                                     │
│ The natural split                                                                   │
│                                                                                     │
│ The current system already implies a natural domain split:                          │
│ - Dev domain: Builder (code/files), Tester (future), Documenter (future) — handle   │
│ by Planning today                                                                   │
│ - Ops domain: Keeper (config), Cron (scheduling) — Planning handles these too, but  │
│ Planning has no config-specific tools                                               │
│ - Monitor domain: Doctor, ModelManager — autonomous APScheduler agents, no          │
│ coordinator needed                                                                  │
│                                                                                     │
│ Planning today is the "dev planner" in disguise. It has no config/ops tools and     │
│ delegates to Keeper via spawn_agent. This suggests the refactor is mostly           │
│ organizational.                                                                     │
│                                                                                     │
│ Proposed structure                                                                  │
│                                                                                     │
│ User → Master [8 tools]                                                             │
│          ├── DevPlanner [12 tools]  ← rename current Planning                       │
│          │     ├── Builder (code, files)                                            │
│          │     └── Tester (future)                                                  │
│          ├── OpsPlanner [8 tools]   ← new agent                                     │
│          │     ├── Keeper (config, env)                                             │
│          │     └── Cron (scheduling)                                                │
│          └── Monitor [autonomous APScheduler, unchanged]                            │
│                ├── Doctor                                                           │
│                └── ModelManager                                                     │
│                                                                                     │
│ Key changes:                                                                        │
│ 1. Planning → DevPlanner: rename + tighten PROMPT.MD to dev-only scope              │
│ 2. New OpsPlanner agent: coordinator for Keeper + Cron, uses Haiku (cheaper), has   │
│ config-aware NOTES.MD                                                               │
│ 3. Master CONFIG.md: remove file_write, file_edit, file_delete, shell_exec from     │
│ default tool list; keep them under a direct_exec: true flag for emergency use       │
│ 4. Master PROMPT.MD: updated routing logic — "code/file tasks → DevPlanner,         │
│ config/schedule tasks → OpsPlanner, mixed → both in parallel"                       │
│ 5. New wait_for_agents tool in delegation.py — the critical parallel fan-in         │
│ primitive                                                                           │
│                                                                                     │
│ Master's reduced tool set (8 tools)                                                 │
│                                                                                     │
│ spawn_agent, ping_agent, kill_agent, wait_for_agents (new), check_task_status,      │
│ read_task_result, web_search, memory_append, notes_read, notes_write, health_log,   │
│ read_agent_logs                                                                     │
│ → 12 tools (was 22). The 10 removed: file_read/write/edit/delete/list, shell_exec,  │
│ server_restart, process_restart, create_agent, delete_agent                         │
│                                                                                     │
│ New tool: wait_for_agents                                                           │
│                                                                                     │
│ # app/utils/tools/delegation.py                                                     │
│ class WaitForAgentsTool(BaseTool):                                                  │
│     name = "wait_for_agents"                                                        │
│     # params: agent_names: list[str], timeout: int = 300, poll_interval: int = 10   │
│     # polls all TASK.MD frontmatter simultaneously using asyncio.gather             │
│     # returns dict of agent_name → {status, result, error}                          │
│     # fails fast (returns) if any agent reports "error" status (configurable:       │
│ fail_fast=True)                                                                     │
│                                                                                     │
│ OpsPlanner agent                                                                    │
│                                                                                     │
│ - Location: app/agents/ops_planner/                                                 │
│ - Model: claude-haiku-4-5-20251001 (cheaper than Sonnet — ops tasks are narrower in │
│  scope)                                                                             │
│ - Tools: spawn_agent, ping_agent, wait_for_agents, check_task_status,               │
│ read_task_result, file_read, file_list, memory_append, notes_read, notes_write,     │
│ health_log                                                                          │
│ - NOTES.MD: seeded with config file locations, .env key schema, cron schedule       │
│ format                                                                              │
│ - lifecycle.temporary: false (long-lived, like Planning)                            │
│                                                                                     │
│ ---                                                                                 │
│ What This Does NOT Fix                                                              │
│                                                                                     │
│ - Sequential sub-tasks within one family: DevPlanner still processes builder tasks  │
│ sequentially unless DevPlanner itself uses fan-out. A wait_for_agents + parallel    │
│ spawn_agent calls in one LLM response would help, but this is LLM-behavioral, not   │
│ code-enforced.                                                                      │
│ - Simple single-file edits still traverse 3 agent hops: No shortcut path for        │
│ trivial tasks. Could add a direct_exec mode to Master for simple tasks, but that    │
│ re-introduces tool bloat.                                                           │
│ - Fan-out spawn storm: The audit-recommended code cap on concurrent agents          │
│ (settings.max_concurrent_agents) should be enforced in SpawnAgentTool regardless.   │
│ Families don't change this.                                                         │
│                                                                                     │
│ ---                                                                                 │
│ Implementation Plan                                                                 │
│                                                                                     │
│ Phase 1 — wait_for_agents tool (highest value, standalone)                          │
│                                                                                     │
│ 1. Add WaitForAgentsTool to app/utils/tools/delegation.py                           │
│ 2. Register in TOOL_REGISTRY in app/utils/tools/__init__.py                         │
│ 3. Update app/agents/planning/CONFIG.md + PROMPT.MD to use it                       │
│ 4. Update app/agents/master/CONFIG.md to include it                                 │
│                                                                                     │
│ Phase 2 — Master tool reduction                                                     │
│                                                                                     │
│ 1. Remove file/shell/server tools from app/agents/master/CONFIG.md                  │
│ 2. Update app/agents/master/PROMPT.MD routing logic                                 │
│ 3. Update app/agents/master/CLAUDE.md                                               │
│                                                                                     │
│ Phase 3 — OpsPlanner agent                                                          │
│                                                                                     │
│ 1. Create app/agents/ops_planner/ with all 8 required files                         │
│ 2. Seed NOTES.MD with ops domain knowledge (config paths, env schema, schedule      │
│ format)                                                                             │
│ 3. Add to APScheduler excluded list (ops_planner is on-demand, not periodic)        │
│ 4. Update Master PROMPT.MD to route ops tasks to ops_planner                        │
│                                                                                     │
│ Phase 4 — Rename Planning → DevPlanner (optional)                                   │
│                                                                                     │
│ Lowest priority — Planning already behaves as a dev planner. Renaming is cosmetic   │
│ but reduces ambiguity. Requires updating all PROMPT.MD references and TOOL_REGISTRY │
│  names if planning is referenced by literal name in tool calls.                     │
│                                                                                     │
│ ---                                                                                 │
│ Files to Modify                                                                     │
│                                                                                     │
│ ┌───────────────────────────────┬─────────────────────────────────────────────────┐ │
│ │             File              │                     Change                      │ │
│ ├───────────────────────────────┼─────────────────────────────────────────────────┤ │
│ │ app/utils/tools/delegation.py │ Add WaitForAgentsTool                           │ │
│ ├───────────────────────────────┼─────────────────────────────────────────────────┤ │
│ │ app/utils/tools/__init__.py   │ Register wait_for_agents in TOOL_REGISTRY       │ │
│ ├───────────────────────────────┼─────────────────────────────────────────────────┤ │
│ │ app/agents/master/CONFIG.md   │ Remove 10 file/shell tools, add wait_for_agents │ │
│ ├───────────────────────────────┼─────────────────────────────────────────────────┤ │
│ │ app/agents/master/PROMPT.MD   │ Routing logic for Dev/Ops split                 │ │
│ ├───────────────────────────────┼─────────────────────────────────────────────────┤ │
│ │ app/agents/planning/CONFIG.md │ Add wait_for_agents                             │ │
│ ├───────────────────────────────┼─────────────────────────────────────────────────┤ │
│ │ app/agents/planning/PROMPT.MD │ Use wait_for_agents for fan-in                  │ │
│ ├───────────────────────────────┼─────────────────────────────────────────────────┤ │
│ │ app/agents/ops_planner/       │ New agent directory (8 files)                   │ │
│ ├───────────────────────────────┼─────────────────────────────────────────────────┤ │
│ │ app/utils/tools/CLAUDE.md     │ Document new tool                               │ │
│ ├───────────────────────────────┼─────────────────────────────────────────────────┤ │
│ │ app/agents/CLAUDE.md          │ Update agent table                              │ │
│ └───────────────────────────────┴─────────────────────────────────────────────────┘ │
│                                                                                     │
│ ---                                                                                 │
│ Recommendation                                                                      │
│                                                                                     │
│ Implement Phase 1 + Phase 2 now. Phase 3 (OpsPlanner) when Keeper/Cron are no       │
│ longer stubs.                                                                       │
│                                                                                     │
│ Phase 1 (wait_for_agents) is the highest-leverage single change — it enables        │
│ cross-domain parallelism and is useful immediately even without families. Phase 2   │
│ (Master tool reduction) directly addresses the High-severity audit finding. Both    │
│ phases require no new agent infrastructure.                                         │
│                                                                                     │
│ Phase 3 only pays off once Keeper and Cron are real — today both are stubs with no  │
│ integration tests. Creating OpsPlanner to coordinate stubs adds complexity without  │
│ benefit. Revisit when ops agents are production-ready.                              │
│                                                                                     │
│ Phase 4 (rename Planning) is cosmetic and can be skipped. 