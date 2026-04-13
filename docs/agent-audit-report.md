# YAPOC Agent Audit Report

Generated: 2026-04-10
Scope: all agents under `app/agents/` — role clarity, tool sizing, model fit,
safety envelope, and cost posture.

---

## 1. Executive summary

YAPOC has seven implemented agents organized in a two-tier hierarchy
(Master → Planning → Builder/Keeper/Cron, with Doctor and Model Manager
running on APScheduler). The architecture is sound. The concerns found are
mostly about **ergonomics, cost, and role overlap** rather than correctness:

| Severity | Count | Highlights |
|---|---|---|
| Critical | 0 | — |
| High | 3 | Master's bloated tool set, Doctor's hard OpenAI dependency, missing fallback execution |
| Medium | 5 | Planning/Builder role drift, Keeper idle, Cron stub, self-opt disabled, no per-agent usage tracking (fixed by this change) |
| Low | 4 | PROMPT redundancy, inconsistent tool tables, ephemeral agents untested at scale, doc/code drift |

The top three things to fix next, ranked by impact:

1. **Trim Master's tool surface** (currently ~22 tools) or split its prompt
   into "front-door router" vs. "executor" modes — the router rarely needs
   `file_delete` or `shell_exec` one keystroke away.
2. **Make Doctor provider-agnostic** — it hard-wires `openai/gpt-4o-mini`,
   which silently breaks any deployment without an OpenAI key. The
   `agent-settings.json` added in this commit gives us a clean place to
   configure fallbacks; Doctor should honor them.
3. **Wire up fallback execution** — the new `agent-settings.json` encodes
   primary + fallback models, but `BaseAgent._load_config()` still only reads
   `CONFIG.md`. The fallback chain is documentation-only until adapters can
   retry through it on error.

---

## 2. Per-agent audit

Each section covers: **Role**, **Model fit**, **Tools**, **Issues**,
**Recommendations**.

### 2.1 Master Agent

- **Role**: Single entry point for CLI/HTTP. Decides what to handle directly
  vs. delegate to Planning.
- **Model**: `anthropic/claude-sonnet-4-6` @ 0.3. Reasonable — frontier-lite,
  1M context. Expensive for trivial pings.
- **Tools (22)**: server_restart, process_restart, shell_exec, file_list,
  file_read, file_write, file_edit, file_delete, memory_append, notes_read,
  notes_write, health_log, web_search, spawn_agent, ping_agent, kill_agent,
  wait_for_agent, check_task_status, read_task_result, read_agent_logs,
  create_agent, delete_agent.

**Issues**

- **H-1 Tool bloat.** Master has the full set, which means every user message
  burns tokens on the whole tool catalog in the system prompt (tool defs are
  cached, but they still inflate every uncached turn). It also encourages the
  model to "do it itself" instead of delegating, degrading the hierarchy.
- **M-1 Role drift with Builder.** The prompt says "execute simple tasks
  directly… single file operations." In practice this overlaps with Builder
  and fragments responsibility: the same change could be done by Master or by
  `spawn_agent("builder")`, and the rule of when to escalate ("5+ tools") is
  vague.
- **L-1 Doc redundancy.** The PROMPT restates the restart disambiguation
  table in both the Tools and Behavior sections — 20+ extra tokens per turn.

**Recommendations**

- Split into "router" and "executor" tool groups. Give Master only
  `spawn_agent`, `wait_for_agent`, `ping_agent`, `check_task_status`,
  `read_task_result`, `read_agent_logs`, `web_search`, `memory_append`,
  `notes_read/write`, `server_restart`, `process_restart` by default.
  Gate the file/shell tools behind an explicit "direct execution" mode the
  user opts into per-session.
- Clarify the delegation rule: "If the task needs >2 file writes OR touches
  code in `app/`, always delegate to Planning." The current "5 tool calls"
  heuristic is something a model can game both directions.
- Consider downgrading to Haiku 4.5 for the **first** turn of each session (a
  cheap router turn) and only escalating to Sonnet when the task is non-trivial.

### 2.2 Planning Agent

- **Role**: Decomposition + orchestration. Receives goals from Master, breaks
  them down, delegates to Builder/Keeper.
- **Model**: `anthropic/claude-sonnet-4-6` @ 0.3. Good fit — planning benefits
  from frontier reasoning.
- **Tools**: spawn_agent, ping_agent, kill_agent, wait_for_agent,
  check_task_status, read_task_result, file_read, file_list, memory_append,
  notes_read, notes_write, health_log.

**Issues**

- **M-2 No `read_agent_logs`.** Master has it but Planning doesn't, so when
  a sub-agent fails Planning can only see TASK.MD's Result/Error sections,
  not the OUTPUT.MD stream. This causes Planning to retry blindly or
  mis-classify transient failures.
- **M-3 Hard-coded "max 3 concurrent sub-agents" rule.** The limit lives only
  in the prompt, not in code. A model under pressure can ignore it.
- **L-2 Output format is non-machine-readable.** The Markdown template is
  nice for humans but Master has to re-parse it to act. Either keep it human
  and don't re-parse, or emit JSON and parse explicitly.

**Recommendations**

- Add `read_agent_logs` to Planning's tool list so it can diagnose failures.
- Enforce the concurrency cap in `SpawnAgentTool` (count live STATUS.json
  entries with state=running before spawning).
- Consider dropping `kill_agent` — Planning should not be killing peers;
  escalate to Master.

### 2.3 Builder Agent

- **Role**: File/agent creation and code changes.
- **Model**: `anthropic/claude-sonnet-4-6` @ 0.2. Temperature 0.2 is the
  right call for precise edits.
- **Tools**: file_read, file_write, file_edit, file_delete, file_list,
  shell_exec, create_agent, delete_agent, memory_append, notes_read,
  notes_write, health_log.

**Issues**

- **M-4 No web_search.** Builder regularly needs to look up library APIs and
  currently has to ask Master, wasting a round-trip and blowing context.
- **L-3 Protected-directory rule is prompt-only.** "Never modify
  master/planning/builder/keeper/cron/doctor" is enforced by the model, not
  by the tools. A bad plan from Planning can trivially breach this. The
  Keeper sandbox pattern (declarative allowed_paths in CONFIG.md) should
  apply to Builder too.
- **L-4 `max_turns=40` is optimistic.** Most real tasks finish in <10 turns;
  when something runs to 40 it is almost always in a loop. Tighten to 25 and
  rely on the task-timeout escape hatch for legitimate long tasks.

**Recommendations**

- Add `web_search` to Builder's CONFIG.md.
- Add a `sandbox.forbidden` block mirroring Master's, enforced by `file_*`
  tools.
- Lower `max_turns` to 25.

### 2.4 Keeper Agent

- **Role**: Sole guardian of .env, settings.py, pyproject.toml.
- **Model**: `anthropic/claude-haiku-4-5-20251001` @ 0.2. Appropriate — cheap
  and precise, config edits don't need Sonnet.
- **Tools**: file_read, file_write, file_edit, shell_exec, memory_append,
  notes_read, notes_write, health_log.

**Issues**

- **M-5 Effectively idle.** Nothing currently spawns Keeper. Master and
  Builder are both told "ask Keeper for config changes" but the delegation
  chain is never actually exercised, and there's no integration test forcing
  it. Expect it to bitrot.
- **H-2 Dangerous shell_exec with no sandbox on commands.** The prompt says
  "only use `poetry add`/`remove`/`install`" but this is model-enforced. A
  prompt injection asking Keeper to `shell_exec "curl ... | sh"` is not
  blocked by anything.
- **L-5 No `file_list` tool.** Keeper can't discover `.env.example` or other
  config files without being told explicitly — fragile.

**Recommendations**

- Wire Keeper into the actual dependency-install flow (Builder should
  `spawn_agent("keeper", ...)` whenever a task needs a new package).
- Either replace `shell_exec` with a narrowly-scoped `poetry_exec` tool or
  add a `shell_command_allowlist: [poetry ...]` to CONFIG.md enforced by
  `ShellExecTool`.
- Add `file_list` to the tool list.

### 2.5 Cron Agent

- **Role**: Recurring task scheduler (stub).
- **Model**: `anthropic/claude-haiku-4-5-20251001` @ 0.2.
- **Tools**: delegation + memory/notes/file_read/file_list/health_log.

**Issues**

- **M-6 Stub status.** There is a PROMPT and CONFIG but no end-to-end
  invocation path. `apscheduler` is a dependency but the cron CLI commands
  are listed as stubs. The schedule format lives only in the prompt, not in
  code.
- **M-7 Schedule format is free-text in NOTES.MD.** A model regenerating
  NOTES.MD can easily corrupt the schedule. A structured JSON/YAML file
  separate from NOTES.MD would be safer.
- **L-6 Max 10 jobs rule only in prompt.**

**Recommendations**

- Move the schedule out of NOTES.MD into `app/agents/cron/schedule.json` and
  have a tool (`cron_add_job`, `cron_remove_job`, `cron_list_jobs`) that
  validates and writes to it. NOTES.MD should be reserved for agent learnings.
- Implement the cron CLI commands the README lists as stubs, or remove them.
- Share a single source of truth for the schedule between Cron Agent and the
  APScheduler wiring in `app/backend/main.py` so they can't drift.

### 2.6 Doctor Agent

- **Role**: Autonomous health monitor, runs on schedule.
- **Model**: `openai/gpt-4o-mini` @ 0.2. **Problem** — hard OpenAI dependency.
- **Tools**: file_read, file_list, read_agent_logs, memory_append, notes_read,
  notes_write, health_log, *(newly added)* heal_agent_settings,
  show_agent_settings.

**Issues**

- **H-3 Hard OpenAI dependency.** `CONFIG.md` pins `adapter: openai`. In an
  Anthropic-only deployment the LLM-triggered Doctor tasks silently fail
  (APScheduler swallows exceptions). `run_health_check()` still works because
  it's pure Python, but the LLM mode is dead.
- **M-8 No ability to heal / self-recover.** Until this audit change, Doctor
  could only report problems, not fix them. With the new
  `heal_agent_settings` tool Doctor can now recover a corrupt
  `agent-settings.json`, but broader recovery (stuck agents, wedged file
  locks, etc.) is still out of scope.
- **L-7 Programmatic and LLM modes share nothing.** They re-scan the same
  files independently. The programmatic mode could write a structured
  summary that the LLM mode reads, instead of each path re-doing the work.

**Recommendations**

- **Now (this change):** Doctor gains `heal_agent_settings` and
  `show_agent_settings` tools so it can recover the settings file on its own.
- **Next:** Change Doctor to read its primary/fallback models from
  `agent-settings.json` instead of `CONFIG.md`, so fallbacks (anthropic/haiku,
  google/flash) take over automatically when OpenAI is unavailable.
- **Later:** Add a `restart_agent` tool (CONFIRM-tier) so Doctor can ask to
  restart a wedged agent, with human approval.

### 2.7 Model Manager Agent

- **Role**: Cross-agent config auditor and optimizer.
- **Model**: `anthropic/claude-haiku-4-5-20251001` @ 0.2. Cheap is right.
- **Tools**: file_read, file_list, check_model_availability, list_models,
  update_agent_config, memory_append, notes_read, notes_write, health_log.

**Issues**

- **L-8 Doc claims Sonnet, code uses Haiku.** `app/agents/CLAUDE.md` says the
  Model Manager runs on `anthropic/claude-haiku-4-5`. The PROMPT says nothing
  about this, and Master's PROMPT lists it as "cost optimization". Consistent
  — it's fine on Haiku — but the top-level `CLAUDE.md` project doc implies
  otherwise. Pick one source of truth.
- **M-9 No integration with agent-settings.json.** Until this audit change
  the model catalog and the per-agent assignments lived in two places
  (`CONFIG.md` per agent, `MODEL_REGISTRY` in code). Now there are three —
  add `agent-settings.json`. The Model Manager should own reading/writing
  the JSON, otherwise we'll get drift.

**Recommendations**

- Give Model Manager a new tool `update_agent_settings_entry` that edits
  `agent-settings-base.json` directly (not the active file), so its updates
  survive restart.
- Kill the duplication: either `CONFIG.md` OR `agent-settings.json` should be
  authoritative, not both. Recommend keeping `CONFIG.md` for
  tool/runner/sandbox policy and moving **only** `adapter`/`model`/`fallbacks`
  into `agent-settings.json`.

---

## 3. Cross-cutting issues

### 3.1 No per-agent usage tracking (fixed in this PR)

Until now, token/cost metrics were only tracked at the CLI session level,
so you could see "Master+children burned $0.50 this session" but not
"Planning was 80% of it." This made cost regressions hard to attribute.

**Fix in this PR:** `BaseAgent.run_stream_with_tools` now persists a rolling
`USAGE.json` in each agent's directory. See §4.

### 3.2 Fallback chain is documentation-only

`agent-settings-base.json` declares fallbacks but nothing executes them.
`BaseAgent._load_config()` still only reads `CONFIG.md`. When an API errors
out mid-turn, the agent just fails.

**Recommendation:** Add a `FallbackAdapter` that wraps the primary, catches
provider errors (`httpx.HTTPStatusError`, `anthropic.APIError`, timeouts),
and retries with each fallback in order. Load the list from
`agent_settings.resolve_agent(agent_name)`. Out of scope for this PR but
should be the next step.

### 3.3 Risk tiering is binary (AUTO vs CONFIRM)

The tool system has only two tiers, so everything non-trivial requires human
approval. In practice users either:
- Approve mindlessly (`yes` to everything → security theater), or
- Hit fatigue and set `safety_mode=auto_approve` (→ no protection at all)

**Recommendation:** Introduce a third tier `SCOPED_AUTO` — "auto if the
target is inside the agent's sandbox; confirm otherwise." This matches how
Builder's protected-directory rule is intended to work.

### 3.4 Agent spawn fan-out is unbounded in code

Master/Planning can spawn arbitrarily many agents. The "max 3 concurrent"
rule lives only in prompts. Under prompt injection or model confusion, a
runaway spawn storm is possible.

**Recommendation:** Enforce a hard cap in `SpawnAgentTool` based on live
STATUS.json counts. Respect a new `settings.max_concurrent_agents` (default
5) with override per-agent in CONFIG.md.

### 3.5 PROMPT redundancy

Every agent's PROMPT re-lists its tools in a table. The tool table is
already sent to the model as part of the tool definitions — the table in
PROMPT is duplicated context. On Sonnet this is ~200 tokens per turn per
agent, ~1.4 k tokens system-wide. Not huge but free to fix.

**Recommendation:** Drop the "Tools Available" table from every PROMPT. If
the rationale is "documentation for humans reading the file", move it to a
comment block the context builder strips out.

### 3.6 Self-optimization is off by default

`allow_self_optimization: bool = False`. The plumbing exists (Master's
`update_config` path, audit logs in HEALTH.MD with `SELF_OPT:` prefix), but
no one uses it because the env flag is a documented footgun.

**Recommendation:** Either commit to it (enable by default + aggressive
rollback on HEALTH.MD errors) or rip out the dead code. Current state is
confusing — the prompt tells Master to self-optimize, but the kill switch is
default-off, so all that guidance is wasted context.

---

## 4. Improvements delivered in this PR

To make this audit actionable rather than a wishlist, the following items
are shipped alongside it:

1. **Google Gemini and LM Studio adapters** — `ADAPTER_REGISTRY` now includes
   `google` (OpenAI-compat endpoint) and `lmstudio` (local OpenAI-compat
   server). Model catalogs in `app/utils/adapters/models/google.py` and
   `.../lmstudio.py`.
2. **Env alias handling** — `GOOGLE_API_KEY` and `GEMINI_API_KEY` are both
   accepted via `pydantic.AliasChoices` on `settings.google_api_key`.
3. **`agent-settings-base.json`** — declarative per-agent primary + fallback
   models. Fallback count honors `DEFAULT_N_FALLBACKS_MODELS` from `.env`.
4. **Secure key lifecycle** — `app/utils/agent_settings.py` fills keys on
   start and wipes them on exit. `scripts/yapoc-lifecycle.sh` wraps yapoc
   with trap handlers for EXIT / INT / TERM / HUP / QUIT so keys are cleared
   on clean exit, Ctrl+C, SIGTERM, crash, or terminal close.
5. **`heal` path** — `scripts/heal.sh` and `heal_agent_settings` tool let
   the Doctor (or a human) rebuild `agent-settings.json` from the base,
   including a `--wipe` mode for panic recovery.
6. **Per-agent usage tracking** — `BaseAgent.run_stream_with_tools` persists
   `USAGE.json` in each agent's directory, tracking input, output,
   cache-creation, cache-read tokens, tool-call counts, and USD cost. See
   §5 for details.
7. **LM Studio setup guide** — `docs/llmstudio-guide.md`.

---

## 5. Per-agent token counting (implementation notes)

### Before

- Real token counts came from API responses as `UsageStats` stream events.
- These were consumed by the CLI renderer for display and aggregated into
  a global `_session_*` counter in `app/cli/main.py`.
- **No per-agent accumulation** — you couldn't answer "how much has Planning
  cost me this week".
- Tool calls were not counted separately from plain turns.

### After (this PR)

Each agent directory now holds a `USAGE.json`:

```json
{
  "total_input_tokens": 12450,
  "total_output_tokens": 3210,
  "total_cache_creation_tokens": 8200,
  "total_cache_read_tokens": 14400,
  "total_tool_calls": 17,
  "total_turns": 6,
  "total_cost_usd": 0.0423,
  "by_model": {
    "claude-sonnet-4-6": {
      "input_tokens": 12450,
      "output_tokens": 3210,
      "cache_creation_tokens": 8200,
      "cache_read_tokens": 14400,
      "cost_usd": 0.0423,
      "turns": 6,
      "tool_calls": 17
    }
  },
  "last_updated": "2026-04-10T12:34:56Z"
}
```

Update points in `BaseAgent.run_stream_with_tools`:
- On every `UsageStats` event → accumulate input/output/cache tokens + cost.
- On every `ToolDone` event → increment `total_tool_calls` for the active model.
- On turn completion → increment `total_turns`.

Cost uses the same `calc_cost()` helper as the CLI renderer, reading pricing
from `ALL_PRICING` so local models (lmstudio/ollama) correctly accumulate
zero cost.

### Display

- CLI `yapoc agents status` can extend to show per-agent spend (future).
- Doctor's health check can flag agents whose cost trend exceeds a budget.
- Model Manager's audit already reads `CONFIG.md`; it can now also read
  `USAGE.json` and make informed downgrade recommendations.

---

## 6. Prioritized action list

| # | Action | Owner | Cost | Impact |
|---|---|---|---|---|
| 1 | Enforce concurrent-agent cap in `SpawnAgentTool` | Builder | S | High |
| 2 | Make Doctor read model from `agent-settings.json` | Builder | S | High |
| 3 | Add `FallbackAdapter` wrapper | Builder | M | High |
| 4 | Tighten Keeper `shell_exec` to `poetry_exec` | Builder | S | Med |
| 5 | Add `web_search` + sandbox to Builder | Keeper | S | Med |
| 6 | Replace Master's tool bloat with router/executor split | Builder | M | Med |
| 7 | Real Cron schedule file + CLI commands | Builder | M | Med |
| 8 | Introduce `SCOPED_AUTO` risk tier | Builder | M | Med |
| 9 | Drop "Tools Available" tables from PROMPT files | Keeper | S | Low |
| 10 | Decide self-optimization: commit or remove | — | S | Low |

(S = hours, M = a day or two, L = week+.)

---

## 7. Appendix — audited artifacts

**Prompts read:** master, planning, builder, keeper, cron, doctor,
model_manager (`PROMPT.MD`).

**Configs read:** same set (`CONFIG.md`) + `app/agents/CLAUDE.md` and
`app/agents/master/CLAUDE.md`, `app/agents/doctor/CLAUDE.md`.

**Code reviewed:** `app/agents/base/__init__.py` (BaseAgent, tool execution,
compaction), `app/utils/adapters/__init__.py` (registry),
`app/utils/adapters/base.py` (events), `app/utils/adapters/openrouter.py`
and `.../openai.py` (streaming pattern), `app/utils/tools/__init__.py`
(tool registry), `app/agents/doctor/agent.py` (programmatic health check),
`app/cli/renderer.py` (cost calculation).

**Out of scope:** backend API routes, session persistence, context
auto-compaction heuristics, the CLI renderer UX.
