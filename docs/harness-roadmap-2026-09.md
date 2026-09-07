# YAPOC Harness Roadmap — Q4 2026

**Written:** 2026-09-07 · **Supersedes for reliability scope:** the "Prioritized roadmap" section of
`app/projects/yapoc_ultimate_agentic_harness_report.md`. The older feature roadmap in
`docs/roadmap.md` (10 capability features) remains valid and is not replaced by this document.

**Basis:** direct inspection of `data/yapoc.db` (1,523 agent tasks, 1,175 queue tasks),
`app/backend/routers/metrics.py`, `app/agents/base/`, `app/utils/`, `data/signal_ledger.json`,
and the per-agent `CONFIG.yaml` / `agent-settings.json` bindings.

---

## 1. Where the report is right, and where the data disagrees

The harness report is directionally correct — the bottleneck is the control loop, not more agents.
But three of its five reliability claims do not survive contact with the task database, and the
largest actual failure class is not mentioned in the report at all. Ranking the work off the
report's narrative would put effort in roughly the wrong order.

### Ground truth: every failed task, all time

`data/yapoc.db`, `tasks` table — 74 errors out of 1,523 tasks (**4.9% failure rate**):

| Failure class | Count | % of failures | Report's treatment |
|---|---:|---:|---|
| **Task timed out** | 30 | 41% | not mentioned |
| **Provider / adapter config errors** | 19 | 26% | not mentioned |
| **Turn-limit exhaustion** | 19 | 26% | named as *the* bottleneck |
| Malformed LLM output (bad tool JSON, truncation) | 5 | 7% | not mentioned |
| Empty error text | 1 | 1% | — |

Turn-limit exhaustion is real but it is **one quarter** of the problem, not the headline. And it is
not a planning-agent problem: it splits `builder` 8 (at `max_turns: 30`), `planning` 6 (at 45),
`model_manager` 5 (at 15). Re-routing work away from planning fixes at most a third of that
quarter.

The 19 provider/config errors are the cheapest fix in the entire backlog and are invisible in the
report. They are literal misconfigurations:

- `400 INVALID_ARGUMENT … can only set only one of thinking budget and thinking level` (Gemini) — 5x
- `The supported API model names are deepseek-v4-pro or deepseek-v4-flash, but you passed…` — 2x
- `All 4 adapters in the fallback chain failed to start streaming tools` (Gemini last) — 10x
- `Your credit balance is too low` — 1x

Ten of those are a *whole fallback chain* collapsing, which means a bad adapter config does not
degrade — it takes the task down.

### Claim-by-claim

| Report claim | Verdict | What is actually there |
|---|---|---|
| "`metrics.py` has no `status='error'` handling; task failures can be invisible" | **Partly true** | `/observability` *does* read the `tasks` table (`metrics.py:470-506`) for the recent-tasks feed. But `agents_with_errors` and `recent_error_count` (`metrics.py:444-447`) derive only from `HEALTH.MD`. The dashboard *counters* lie; the task feed does not. |
| "This undermines the user-required alert after two consecutive failures" | **False** | `app/utils/agent_failure_tracker.py` is wired into `app/agents/base/__init__.py:824-840`, fires once at threshold 2, and persists to `data/agent_failures.json` (currently all agents at 0). The alert works. The dashboard counter is the defect. |
| "Planning hit the 45-turn ceiling on four consecutive tasks" | **True but unrepresentative** | 6 planning turn-limit failures all time, out of 253 planning tasks. Builder has more (8). |
| "Typed layered memory remains an active goal" | **Half-built, not greenfield** | `memory_entries` already has `tier` and `provenance` columns (`db.py:77-90`). `tier` works (hot/cold, 7 rows archived). `provenance` is written for **0 of 2,480 rows** — the column is dead. |
| "Evaluator findings are not reliably converted into fixes — a governance gap" | **Overstated** | `app/utils/signal_ledger.py` + `data/signal_ledger.json` track 34 signals with 31 resolved / 3 open and only 1 signal open ≥3 rounds. The loop exists and works. It is *stale*: ledger max round 93 vs `REPORT.MD` round 103. |
| "README says no tests despite test files existing" | **True, and worse** | 27 test files exist (`tests/` 14, `app/backend/tests/` 13, `artifacts/playwright/` 5). `README.md:191` and `CLAUDE.md` both say "No tests yet". The only CI workflow is `.github/workflows/installer.yml` — **nothing runs any test, ever.** |
| README architecture placeholder | **True** | `README.md:9-15`, awaiting `docs/architecture.mmd`. |

### Two gaps neither document names

1. **Failed work is discarded whole.** On timeout (`runner.py:456-475`) and on turn exhaustion
   (`base/__init__.py:2096`) the task is marked `error` and every turn of work is thrown away.
   No partial-result salvage, no continuation. Failed tasks average **179s** of runtime vs 47s for
   successful ones — the failures are the *expensive* ones, and 100% of that spend is written off.
   This single behavior sits behind 49 of 74 failures (66%).
2. **Cost is not attributed to tasks.** `task_queue.cost_usd` exists (`db.py:106`) and is `0.0` for
   all 1,175 rows — nothing writes it. Cost lives only as per-agent lifetime totals in `USAGE.json`
   (builder alone: $81.74). Every cost target in the report ("cost per completed task", "turn-limit
   waste by task class") is therefore greenfield, not a reporting tweak.

---

## 2. Roadmap

Four phases. Phase 0 is a week of cheap, high-yield fixes that the report's 30-day plan buries or
misses entirely. Ordering rule throughout: **stop the bleeding, then measure it, then get smarter.**

### Phase 0 — Stop the cheap failures (week 1, ~2 days of work)

Addresses 26% of all failures for near-zero design cost. Do this before anything else.

| # | Item | Where | Why |
|---|---|---|---|
| 0.1 | Fix the Gemini `thinking budget`/`thinking level` conflict | `app/utils/adapters/` (google) | 5 hard failures + contributes to the 10 chain collapses |
| 0.2 | Validate model IDs at config-load, not at call time | `app/utils/agent_settings.py` | 2 failures from a model name that could never have worked; a startup assertion catches the whole class |
| 0.3 | Make fallback chains actually degrade | `app/agents/base/__init__.py` | 10x "all 4 adapters failed" means one bad config kills every fallback. Chain must skip an adapter that fails to *start* streaming, and log which. |
| 0.4 | Adapter smoke check on boot | new, `app/utils/adapters/health.py` exists as a seed | One cheap request per configured adapter at startup; refuse to bind an agent to a dead adapter |

**Exit:** provider/config errors → 0 in a 7-day window. Verify with the same query used above.

### Phase 1 — Make failure survivable and visible (weeks 2-4)

The report's P0s, reordered by measured impact.

| # | Item | Where | Detail |
|---|---|---|---|
| 1.1 | **Partial-result salvage** (P0) | `runner.py:456-475`, `base/__init__.py:2096` | On timeout and turn exhaustion, write what the agent produced to `RESULT.MD`, record `status='partial'`, and attach the turn count + last tool call. Stop discarding 179s of work. |
| 1.2 | **Continuation on turn exhaustion** (P0) | `base/__init__.py:1455` loop | At `max_turns`, compact the transcript and re-enqueue as a continuation task with a budget counter, up to N continuations. Turns become a *pacing* limit, not a *kill* limit. |
| 1.3 | **Unify failure accounting** (P0) | `metrics.py:444-447` | `agents_with_errors` / `recent_error_count` must union `HEALTH.MD` lines with `tasks.status='error'` and `task_queue.status IN ('error','timeout')`, deduplicated by `task_id`. Add a reconciliation test asserting dashboard counts == DB counts. |
| 1.4 | **Per-task cost attribution** (P1) | `db.py:106`, dispatcher | Populate `task_queue.cost_usd` from the usage tracker at task finalization. Prerequisite for every cost metric in this roadmap. |
| 1.5 | **Right-size timeouts from data** (P1) | `agent-settings.json` | 30 timeouts is the largest class. p95 successful-task duration by agent is knowable from `tasks`; set each `task_timeout` from it rather than the current mix of 600/900/`<default>`. Pair with 1.1 so an overrun degrades instead of failing. |
| 1.6 | **Task-class routing** (P1) | master prompt + a classifier | Still worth doing — but as a cost/latency optimization (planning is 253 tasks of overhead), not as the fix for turn exhaustion, which 1.2 addresses at the root. |

**Exit criteria:**
- No terminal failure discards work: 100% of `error`/`timeout` tasks carry a partial result or an explicit "nothing produced".
- Dashboard/DB error-count reconciliation test green in CI.
- Turn-limit *failures* → 0 (turn-limit *continuations* are fine and tracked).
- Timeout failures cut ≥50%.

### Phase 2 — Make it measurable (weeks 5-8)

| # | Item | Detail |
|---|---|---|
| 2.1 | **Test posture, resolved** (P0) | 27 test files exist and nothing runs them. Add `.github/workflows/tests.yml` running `poetry run pytest tests/ app/backend/tests/`. Fix or delete what fails. Then correct `README.md:191` and `CLAUDE.md` — the "no tests yet" line is now actively misleading. |
| 2.2 | **Reliability scorecard** (P0) | One endpoint + UI tab off the now-truthful data: completion rate, failure mix by class (the table in §1), continuations used, mean cost per completed task, p95 duration, mean time to detect. Built on 1.3 + 1.4. |
| 2.3 | **Finish provenance** (P0) | The `provenance` column is written for 0 of 2,480 rows. Populate it at every `insert_memory` call site in `app/utils/indexer.py` with `{source_file, agent, task_id, indexed_at}`. Cheap; unblocks all memory lifecycle work. |
| 2.4 | **Retrieval benchmark** (P1) | Fixed set of ~40 queries with known-good answers drawn from real `MEMORY.MD` history. Measure recall@k before/after decay and consolidation. Without this, memory changes are unfalsifiable. |
| 2.5 | **Verification gates** (P1) | Every modifying task attaches: changed files, check command run, result, checkpoint ref. Enforce in the runner, surface in the UI. |
| 2.6 | **Security regression suite** (P1) | `security_policy.py` is 401 lines of heuristics with zero tests. Adversarial fixtures: path traversal, absolute paths, destructive shell, core-agent deletion, tool authorization bypass. |

### Phase 3 — Make it smarter (weeks 9-13)

Deliberately last. Adaptive orchestration on top of untruthful telemetry optimizes against noise.

| # | Item | Detail |
|---|---|---|
| 3.1 | **Typed memory layers** (P0) | Now cheap: `tier` and `provenance` exist and (post-2.3) are populated. Extend `tier` from hot/cold to working / episodic / project / preference / archival, with retention and promotion rules per layer. Gate on the 2.4 benchmark. |
| 3.2 | **Refresh the evaluator ledger** (P1) | The loop works but runs ~10 rounds behind (ledger 93 vs report 103). Make `update_ledger` fire on every evaluator round, and surface the 3 open signals in the UI. |
| 3.3 | **Scenario suite** (P1) | Representative coding / research / config / recovery / adversarial tasks in isolated fixtures, run on a schedule via `cron`. |
| 3.4 | **Policy-driven routing** (P2) | Select agent/model/depth from historical success + cost by task class. Requires 1.4 and 2.2 to exist first. |
| 3.5 | **Architecture doc** (P2) | Fill `README.md:9-15`; author `docs/architecture.mmd`. |
| 3.6 | **Release gates** (P2) | Block promotion on reliability/security/cost regression against the 2.2 scorecard. |

---

## 3. Targets

Each is checkable with a query against `data/yapoc.db` or a CI job — no target here depends on
subjective review.

| Metric | Today (measured) | 30 days | 90 days |
|---|---|---|---|
| Overall task failure rate | 4.9% (74/1523) | ≤3% | ≤2% |
| Provider/config failures | 19 all-time | 0 in trailing 7d | 0 in trailing 30d |
| Turn-limit *failures* | 19 | 0 (converted to continuations) | 0 |
| Timeout failures | 30 | ≤15 | ≤5 |
| Work discarded on failure | 100% | 0% | 0% |
| Dashboard/DB error reconciliation | not tested | test green in CI | test green in CI |
| Tasks with attributed cost | 0 / 1175 | 100% of new tasks | 100% |
| Memory rows with provenance | 7 / 2480 | — | 100% of new rows |
| Tests executed in CI | 0 of 27 files | 27 files running | + scenario suite |
| Evaluator ledger staleness | 10 rounds | ≤1 round | ≤1 round |

---

## 4. Risks

- **Continuation (1.2) can mask a genuinely stuck agent.** Bound it: max N continuations, and the
  existing stuck-loop detector still applies. A task that burns its continuation budget is a
  louder failure than a turn-limit error, not a quieter one.
- **Partial results (1.1) can be mistaken for success.** `status='partial'` must be its own status —
  never folded into `done` — and must not reset the consecutive-failure counter.
- **Turning on CI (2.1) will surface a wall of red.** Expect it. Triage into fix / delete / quarantine
  in one pass; do not let a half-green suite become permanent background noise.
- **Timeout tuning (1.5) trades failures for cost.** Longer timeouts mean longer expensive failures.
  Only safe once 1.1 and 1.4 land, so overruns are salvaged and priced.
- **The evaluator observes the same data it is judged on.** Keep the scenario suite (3.3) fixtures
  hidden from the evaluator's signal inputs.
