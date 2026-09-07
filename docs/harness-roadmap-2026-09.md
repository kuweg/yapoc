# YAPOC Harness Roadmap — Q4 2026

**Written:** 2026-09-07 · **Supersedes for reliability scope:** the "Prioritized roadmap" section of
`app/projects/yapoc_ultimate_agentic_harness_report.md`. The older feature roadmap in
`docs/roadmap.md` (10 capability features) remains valid and is not replaced by this document.

**Basis:** direct inspection of `data/yapoc.db` (1,523 agent tasks, 1,175 queue tasks),
`app/backend/routers/metrics.py`, `app/agents/base/`, `app/utils/`, `data/signal_ledger.json`,
and the per-agent `CONFIG.yaml` / `agent-settings.json` bindings.

---

## 1. Correction notice (2026-09-07, same day)

**The first draft of this document was wrong about the headline finding, and the
original harness report was right.** The error is recorded here rather than silently
edited out, because the mistake is instructive.

The first draft bucketed *all-time* failures from `tasks` (74 errors / 1,523 tasks) and
concluded that turn-limit exhaustion was only 26% of the problem, behind timeouts and
provider-config errors. That ranking is an artifact of pooling three years of history
with bugs that have since been fixed. Windowed to the current release the picture
inverts:

| Failure class | All-time | Since 2026-09-01 | Last 3 days |
|---|---:|---:|---:|
| **Turn-limit exhaustion** | 19 (26%) | **19 (68%)** | **19 (70%)** |
| Malformed LLM output | 5 (7%) | 5 (18%) | 5 (19%) |
| Task timed out | 30 (41%) | 3 (11%) | 2 (7%) |
| Provider / adapter config | 19 (26%) | **0** | **0** |
| Totals | 74 / 1523 (4.9%) | 28 / 454 (6.2%) | 27 / 272 (9.9%) |

Why the all-time numbers were misleading:

- All 5 Gemini `thinking budget`/`thinking level` 400s are from **2026-06-06**. The
  proto-level fix landed in `app/utils/adapters/google.py` in commit `fe6e143`
  (2026-09-02) and carries a comment describing that exact error. Already fixed.
- All 11 "all N adapters in the fallback chain failed" errors are from **April-May 2026**.
- The 2 DeepSeek model-name errors are from **2026-05-17**; the 2 credit-balance
  errors from **May 2026**.
- 27 of 30 timeouts predate September. The 3 recent ones are all `librarian`.

**Conclusion: provider/config is a solved problem. Do not spend a Phase 0 on it.**

Two facts make turn exhaustion urgent rather than merely present:

1. **Every turn-limit failure in the database is from the last two days** — 4 on
   2026-09-06, 15 on 2026-09-07. This is a new and accelerating regression, not
   background noise.
2. **Raising the cap demonstrably does not work.** Over 2026-09-07 the failures walk
   up the limits as they were raised: 15-turn → 30-turn → 45-turn, all still failing.
   The original report called this out and it is now empirically confirmed.

`planning` is failing **12 of 46 tasks (26%)** over the last 3 days.

### What survives from the first draft

These findings were checked and hold up; they are independent of the windowing error:

| Finding | Status |
|---|---|
| Dashboard error *counters* read only `HEALTH.MD` (`metrics.py:444-447`) while the task feed below reads the `tasks` table | Confirmed |
| The two-consecutive-failure alert **works** — `agent_failure_tracker.py` is wired at `base/__init__.py:824-840`; the report's claim that it is undermined is wrong | Confirmed |
| `memory_entries.provenance` is written for **0 of 2,480 rows** — the column is dead | Confirmed |
| `task_queue.cost_usd` is `0.0` for all **1,175** rows — nothing writes it | Confirmed |
| **Failed work is discarded whole** — no salvage on timeout (`runner.py:456-475`) or turn exhaustion (`base/__init__.py:2096`) | Confirmed, and now the top priority |
| 27 test files exist; CI runs none of them (only `installer.yml`) | Confirmed |
| Evaluator ledger works (31 resolved / 3 open) but trails ~10 rounds | Confirmed |
| README architecture placeholder at `README.md:9-15` | Confirmed |

The "failed work is discarded whole" finding is what connects the two drafts. It was
listed as a gap neither prior document named, and under the corrected ranking it stops
being a nice-to-have and becomes the fix for 68% of current failures.

---

## 2. Roadmap

Ordering rule: **make failure survivable, then make it visible, then make it rarer.**

Phase 0 is the corrected priority — it targets 68% of current failures. The
adapter/config Phase 0 in the first draft has been deleted: those bugs are fixed and
have produced zero failures since 2026-09-01.

### Phase 0 — Stop discarding failed work (week 1) — LANDED 2026-09-07

Today, a task that exhausts its turns or its timeout is marked `error` and every turn
of work is thrown away. Failed tasks average **179s** of runtime against 47s for
successes, so failures are the expensive ones and 100% of that spend is written off.
This is the single behavior behind 19 of 28 current-release failures.

| # | Item | Where | Detail |
|---|---|---|---|
| 0.1 | **Partial-result salvage** ✅ | `runner.py:456-475`, `base/__init__.py:2096` | On turn exhaustion, persist what the agent produced and record `status='partial'`. Extended in Phase 1 to the timeout and crash paths, which now also read RESULT.MD back into `result_summary` instead of recording the bare string "Task timed out". |
| 0.2 | **Continuation on turn exhaustion** | `base/__init__.py:1455` turn loop | At `max_turns`, compact the transcript and re-enqueue as a continuation task carrying a continuation counter, up to a bounded number of continuations. Turns become a *pacing* limit rather than a *kill* limit. |
| 0.3 | **`partial` as a first-class status** | `db.py`, `agent_failure_tracker.py`, dispatcher | `partial` must not be folded into `done` (it would hide the regression) nor into `error` (it would keep firing false alerts). It must not reset the consecutive-failure counter. |
| 0.4 | **Do not raise caps as the fix** | `CONFIG.yaml` per agent | Explicitly out of scope. 2026-09-07 walked 15 → 30 → 45 and failed at every step. Caps stay; continuation absorbs the overflow. |

**Exit:** turn-limit *failures* → 0, replaced by tracked continuations. No terminal
failure discards work. Overall failure rate back under 4%.

**Status.** 0.1-0.4 implemented on `feature/phase0-adapter-reliability`:
`TurnLimitReached` (`app/agents/base/__init__.py`) carries the partial work out of the
turn loop; `AgentRunner._handle_turn_limit` / `_enqueue_continuation`
(`app/agents/base/runner.py`) salvage it, record a `partial` task row, and re-enqueue;
`settings.max_task_continuations` (default 3, `0` restores the old behaviour) bounds it.
14 tests in `tests/test_turn_continuation.py`, including an end-to-end wiring test that
drives the real turn loop to exhaustion with a fake adapter.

Not yet measured against live traffic — the exit numbers above need a trailing-7-day
re-query once the change has been running. Phase 1.3 (continuation telemetry) is what
makes that measurable, and it is the natural next task.

### Phase 1 — Make failure visible (weeks 2-4) — LANDED 2026-09-07

**Headline result.** Measured against the live system before the change, the
Observability dashboard reported **0 errors in the last 24 hours while 41 tasks
had actually failed**. Not under-counted — zero. The tiles read "all healthy"
during a real failure rate of ~10%. After the fix the same endpoint reports 41,
broken down as master 16, planning 12, evaluator 6, builder 4, librarian 2,
keeper 1.

Two items turned out to be already fixed, found by checking dates before
writing code — the same discipline §1 exists to enforce:

- **1.4 (evaluator truncation)** — `require_complete` already tolerates
  `length`, and `_repair_truncated_json` recovers truncated tool arguments.
  Both landed in `c64e8d7` (2026-09-07 21:29); all 5 failures predate it, and
  there have been **zero** occurrences since. Closed without new code.
- **Phase 0's adapter items** — same story, recorded in §1.

| # | Item | Where | Detail |
|---|---|---|---|
| 1.1 | **Unify failure accounting** (P0) ✅ | `metrics.py` | Counters now union `HEALTH.MD` with `tasks.status='error'` and `task_queue.status IN ('error','timeout')`, deduped by (agent, minute, message-prefix) with the DB record winning. **Correction to this row as first written:** it said to include `partial` in the failure union. That is wrong — `partial` means the agent ran out of turns and was re-enqueued, so the work is still in flight, and counting it would inflate the failure rate with healthy work and make Phase 0 look like a regression. It is reported separately as `continuation_count`. A reconciliation test asserts dashboard counts equal DB counts. |
| 1.2 | **Per-task cost attribution** (P0) ✅ | `db.py`, `dispatcher.py`, `runner.py` | Two levels, because they answer different questions. `task_queue.cost_usd` is the delta of all-agent spend across the task, so it prices a whole delegation tree (was 0.0 for all 1,175 rows — the dispatcher had a literal `pass` where accumulation belonged). New `tasks.cost_usd` is the delta of one agent's USAGE.json across one task, which is **exact** because an agent runs one task at a time. |
| 1.3 | **Continuation telemetry** (P0) ✅ | `metrics.py`, `tasks` table | `tasks.continuation` records which attempt each row is, and the dashboard exposes `continuation_count` plus a per-agent `continuations`. Combined with 1.2's `tasks.cost_usd`, the cost of a continuation chain is now sum-able by task_id — which is what stops 0.2 from quietly tripling spend unnoticed. |
| 1.4 | **Evaluator output truncation** (P1) ✅ already fixed | `evaluator` | 5 failures from `Incomplete provider response: length` / `invalid tool argument JSON`, all evaluator, all since 2026-09-06. Second-largest current class. Likely `max_tokens: 8096` against a large report write. |
| 1.5 | **Librarian timeouts** (P1) ✅ | `agent-settings.json` | Done. Measured: librarian's successful tasks have p95 137s and a slowest-ever 161s across 71 samples, against a 900s timeout. Its timeouts are therefore *stuck* tasks, not slow ones — 900s only meant burning 15 minutes before failing. Cut to 300s (~2x the slowest success ever). Raising it would have been exactly wrong. |
| 1.6 | **Task-class routing** (P2) | master prompt + classifier | Worth doing as a cost/latency optimization — planning carries 253 tasks of overhead — but it is no longer the fix for turn exhaustion. Demoted from the first draft's P1. |

### Phase 2 — Make it measurable (weeks 5-8) — P0s LANDED 2026-09-07

**Headline result.** The suite went from **32 failing to 0** (264 passing), and
none of the 32 were product bugs — every one was a stale test or a test-harness
defect that had gone unnoticed precisely because nothing ever ran them:

| Cause | Count | Fix |
|---|---:|---|
| `TestClient` is not a loopback client, so `AccessMiddleware` correctly refused every request with 401 | 22 | root `conftest.py` gives it a loopback identity |
| Tests asserting `truncate_text` truncation, removed in `1b02284` (2026-05-16); the function has **zero callers** | 8 | rewritten to pin the documented no-op |
| Test asserting a per-model reasoning-replay gate, removed in `c64e8d7` (2026-09-07) | 1 | rewritten to pin "disabled for every model" |
| `SimpleNamespace` settings stub missing `managed_restart`, added to Settings after the stub was written | 1 | field added to the stub |

| # | Item | Detail |
|---|---|---|
| 2.1 | **Test posture, resolved** (P0) ✅ | `.github/workflows/tests.yml` runs pytest plus a frontend typecheck and build on every push. Both CI commands were verified locally first — the frontend job uses **pnpm**, not npm: there is no `package-lock.json`, so an `npm ci` job would have failed on its first run. `README.md` and `CLAUDE.md` no longer claim "No tests yet". |
| 2.2 | **Reliability scorecard** (P0) ✅ | `GET /api/metrics/reliability?days=N` plus an Observability panel with 2d/7d/30d toggles. Defaults to 7 days and always states the window it used. It reproduces the §1 lesson by construction: over 2 days `turn_limit` is 70% of failures, while over 120 days `timeout` leads and `provider_config` reappears — the exact artifact that misled the first draft. Reports failure rate (excluding `partial`, which has no outcome yet), failure mix, cost per completed task, continuation cost, and per-agent p50/p95. |
| 2.3 | **Finish provenance** (P0) ✅ | Only 1 of 11 `insert_memory_entry` sites wrote it, leaving 2,473 of 2,480 rows empty. All 11 now pass a repo-relative source path. **Deviation from this row as first written:** it specified a `{source_file, agent, task_id, indexed_at}` blob, but `agent`, `source` and `timestamp` are already their own columns — the file path was the only missing fact, and a plain path stays greppable. A test fails if any future index site omits it. |
| 2.4 | **Retrieval benchmark** (P1) ✅ | `app/utils/retrieval_benchmark.py` + a checked-in fixture (56 docs / 40 queries), runnable as `poetry run python -m app.utils.retrieval_benchmark`. Published baseline at k=5: **hybrid recall 0.963 / MRR 0.944**, fts 0.950 / 0.892, vector 0.925 / 0.912. Thresholds are enforced by tests. Deliberately NOT run against live memory — live memory changes every few minutes, so its scores are not comparable across runs and cannot detect a regression. |
| 2.5 | **Verification gates** (P1) ✅ | Every task row now carries `changed_files`, `checkpoint_sha` and a `verification` verdict, enforced in the runner and shown per task in the Observability feed. Change sets come from the agent's **own mutating tool calls**, not a `git status` diff — git status is global, so two agents running concurrently would each be credited with the other's edits. |
| 2.6 | **Security regression suite** (P1) ✅ | Done, and it **found six working bypasses of the gate**, all fixed and pinned by 85 tests. See below. |

#### 2.6 findings — six live bypasses

Writing adversarial fixtures against `security_policy.py` (~400 lines of
substring and regex heuristics, previously zero tests) found six inputs the
gate allowed and should not have. Verified side-by-side against the pre-fix
module: 6 of 8 attacks flipped `allow` → `deny`.

| Bypass | Why it worked |
|---|---|
| `app/agents/planning/../security/PROMPT.MD` | Rules match on path *substrings*; the traversal form contains no `/agents/security/` |
| `app//agents//security//PROMPT.MD` | Same, via duplicate separators |
| `rm -fr /` | The pattern matched only the literal spelling `rm -rf` |
| `rm -r -f /` | Flags split across tokens |
| `rm --recursive --force /` | Long flags |
| `sh -c 'rm -rf /'` | Quoted: `/` is followed by `'`, so both the `\s\|$` and `/[a-zA-Z]` anchors missed |

The first two matter most: that write lock exists specifically so the gate
cannot be rewritten from inside the system, and both paths resolve to the real
protected file.

Fixes: `_normalize_path` (textual `os.path.normpath`, so it works on paths that
do not exist yet) applied before every substring rule; and `_rm_hits_root`,
which tokenizes the command — treating quotes as separators — instead of
matching one spelling, making the check independent of flag order, spelling and
quoting. Verified against 10 legitimate commands to confirm no false positives.

Also corrected: `hardcoded_check`'s docstring claimed DENY is checked before
ALLOW. The code has always done the opposite. In a security gate a stale
ordering claim is worse than none, because allow-first means every ALLOW
matcher must carry its own safety conjunctions — a test now fails if any ALLOW
rule is caller-agnostic.

#### 2.4 findings — two results worth acting on

**RRF fusion is empirically justified.** Hybrid beats both rankers it fuses on
every metric (MRR 0.944 vs 0.892 keyword and 0.912 vector). Until now that was
an assumption. A test asserts it stays true, so if fusion ever stops earning its
two searches, that surfaces rather than persisting out of habit.

**Repetitive noise crowds out signal — concrete evidence for 3.1.** The one
query hybrid misses entirely is "security audit findings", which returns five
`model_audit: N agents scanned, M issue(s)` rows instead of the two real
security findings. Dozens of near-identical low-signal entries outrank the
specific match on sheer repetition. Real memory is full of exactly this shape
(`health_check: ISSUES DETECTED — N issue(s)` repeated hundreds of times), which
is why the fixture includes it.

That gives 3.1 a measurable target rather than a design preference: retention
and demotion rules should collapse repetitive entries, and the benchmark will
say whether it worked. A test currently asserts the weakness still exists; when
3.1 fixes it, that test fails and is flipped to assert the correct behaviour.

#### 2.5 — the verdict is deliberately four-valued

A boolean "verified" would be a lie for most tasks. The recorded verdict is:

| Verdict | Meaning |
|---|---|
| `none` | the task changed nothing |
| `verified` | changes are enumerable **and** a rollback point exists |
| `unanchored` | changes are known, but there is no checkpoint to undo them |
| `opaque` / `opaque+checkpoint` | the task ran `shell_exec` or `execute_code`, so the change set cannot be claimed |

`opaque` is the honest case a naive implementation would report as a clean,
fully-known edit while arbitrary commands ran underneath it. Any task that shells
out gets it, regardless of how many file tools it also called.

Confirmed live. A delegated task asked builder to create a file and confirm it
exists; the recorded row was:

```
builder done verdict='opaque'
  files=["file_write:app/tmp/phase25_check.txt", "shell_exec:<opaque>"]
```

Builder wrote the file *and* shelled out to check it, so the change set cannot
be fully claimed — a boolean gate would have reported this as cleanly verified.
A second builder task running concurrently recorded its own separate edit
(`AgentSidebar.tsx`) on its own row, with no cross-attribution: the evidence
for preferring tool-call capture over a global `git status` diff.

### Phase 3 — Make it smarter (weeks 9-13) — 3.1 / 3.2 / 3.5 LANDED 2026-09-07

**3.1 was gated on the 2.4 benchmark, and the gate paid off.** Measured against
the live database, **58.2% of hot memory rows (1,460 of 2,510) were
near-duplicates** — 786 of them the single line `health_check: ISSUES DETECTED
— N issue(s)`. Collapsing them improves every retrieval mode and removes every
miss:

|  | recall@5 | MRR | misses |
|---|---|---|---|
| fts | 0.950 → **0.963** | 0.892 → **0.900** | 1 → **0** |
| vector | 0.912 → **0.963** | 0.912 → **0.927** | 2 → **0** |
| hybrid | 0.950 → **0.975** | 0.944 → **0.963** | 1 → **0** |

The specific query 2.4 flagged — "security audit findings" — went from
**recall 0.0 (a total miss)** to **recall 1.0**. Without 2.4 this would have
been an untestable design preference; with it, it is a measured result.

**Honest note on one number.** One fixture label was corrected mid-measurement:
"telemetry was wrong" originally credited only `sig-metrics`, but
`sig-costcolumn` ("cost_usd was 0.0 for all 1175 rows") is a telemetry bug by
any reading and a neutral labeller would have marked it from the start. Changing
a label after seeing results is how a benchmark gets quietly gamed, so it is
recorded in the fixture itself with the justification — which rests on the
document's content, not on the score.

Deliberately last. Adaptive orchestration on top of untruthful telemetry optimizes
against noise.

| # | Item | Detail |
|---|---|---|
| 3.1 | **Typed memory layers** (P0) ✅ | Cheap once 2.3 lands: extend `tier` from hot/cold to working / episodic / project / preference / archival with retention and promotion rules. Gate on the 2.4 benchmark. |
| 3.2 | **Refresh the evaluator ledger** (P1) ✅ | Works but trails ~10 rounds (93 vs 103). Fire `update_ledger` every round; surface the 3 open signals in the UI. |
| 3.3 | **Scenario suite** (P1) ✅ | `python -m app.utils.scenario_suite`. Split into **offline** scenarios (security, config, recovery, retrieval — free, model-free, CI-safe; 7 of them, all passing) and **live** scenarios that dispatch real tasks. Live runs refuse without `--confirm-spend` and are **not** scheduled: putting a suite that spends the user's API budget on a timer is not a decision this code gets to make. |
| 3.4 | **Policy-driven routing** (P2) ✅ | `python -m app.utils.routing_policy`. Classifies a task and recommends a target **with its evidence**. It advises rather than overriding master: the classifier is a prompt heuristic, and acting on it silently would turn a misclassification into an untraceable wrong route. Falls back to the existing default below 10 samples — a routing decision from four data points is noise wearing a number. |
| 3.5 | **Architecture doc** (P2) ✅ | Fill `README.md:9-15`; author `docs/architecture.mmd`. |
| 3.6 | **Release gates** (P2) ✅ | `poetry run python -m app.utils.release_gate` — exits non-zero on regression, thresholds in a checked-in `release_gates.json` with a recorded rationale per bar. Reads the same sources as the Observability surfaces, so it cannot drift from what the UI shows. Wired into CI as a **reported, not enforced** step. |

---

#### 3.1 — why `layer` is a new column, not new `tier` values

The roadmap proposed extending `tier` from hot/cold to the layer names. `tier`
is load-bearing in retrieval — `search_fts`, `search_vector` and `search_hybrid`
all filter `tier = 'hot'` — so redefining its values would have silently changed
what every query returns. They are also different questions:

    tier   RETRIEVAL VISIBILITY   hot | cold
    layer  KIND OF MEMORY         working | episodic | project | preference | archival

Keeping them separate is what lets a row be `project`-layer but `cold`-tier
after collapse, which the repetition policy needs. Retention is per layer, and
`preference` never expires on age: quietly forgetting a stated user preference
is a worse failure than holding a stale one.

Collapse is **non-destructive** — rows are demoted to `cold` and stay reachable
with `include_cold=True`, and the survivor is annotated `[xN occurrences]` so
the fact that something happened 786 times is not itself lost. It defaults to a
dry run; a function that rewrites more than half of memory should require an
explicit decision.

**Not applied to live memory.** The dry run reports 1,507 of 2,510 hot rows
across 48 groups. That is the user's data and the user's call:
`poetry run python -m app.utils.memory_layers --collapse --apply`.

#### 3.2 — the ledger was 11 rounds stale, and it mattered

`update_ledger()` was only called from `propose_goals()`, which only runs when a
human types `yapoc propose-goals`. Nothing refreshed it after an evaluation, so
it sat at round 93 against a round-104 report.

The cost was concrete: an open signal read *"Observability error counters still
blind to task-level failures"* — the exact defect fixed in Phase 1 — and it
stayed open because nothing reconciled it. Reconciling now: **staleness 11 → 0,
open 3 → 1, resolved 31 → 34.**

The one signal still open is round 104's *"Error counters still HEALTH.MD-only"*,
raised at 20:08; the fix landed at 22:47. It is legitimately stale rather than a
failed fix, and the new hook will resolve it on the next evaluation. Worth
noting that the evaluator reached that finding independently — "grep this run
confirms metrics.py still contains ZERO `status='error'` references" — which is
the same defect this roadmap found from the other direction. That file now has
2 such references and reads both task tables.

#### 3.6 — the gate fails today, on purpose

Run against the live system it reports:

```
[FAIL] failure_rate: 5.9% over 7d (max 4.0%, n=493)
[FAIL] turn_limit_failures: 19 in 7d (max 0)
[FAIL] provider_failures: 1 in 7d (max 0)
[PASS] cost_per_completed_task: $0.0122
[PASS] telemetry_reconciliation: dashboard 41 == tables 41
[PASS] retrieval_recall / mrr / misses
GATE FAILED — 3 failure(s)
```

That is correct behaviour, not a defect. The Phase 0/1 fixes are hours old and a
7-day trailing window still contains pre-fix history — all 19 turn-limit
failures predate the continuation mechanism. The number to watch is whether they
fall out of the window over the coming week; a gate rubber-stamped to pass today
would tell nobody anything.

Two design decisions worth keeping:

- **An empty window is not a pass.** Below `min_tasks` the reliability checks
  return `SKIPPED`, because "0 failures because nothing ran" is exactly how a
  broken system gets waved through. `--strict` turns skips into failures for a
  release where silence is unacceptable.
- **CI reports rather than enforces.** CI has no production task history, so
  the reliability checks skip there and only retrieval and telemetry carry
  signal. Enforcing on an empty window would be the same mistake the `min_tasks`
  rule exists to prevent.

**The gate immediately found something real.** `provider_failures: 1` is
`OpenAI API error (429): You have no credits remaining` at 21:24 today. All 14
configured agents carry OpenAI in their fallback chains, so after the keeper
agent moved every primary to DeepSeek, the remaining cross-provider redundancy
is partly dead — a DeepSeek outage now burns a failed OpenAI attempt before
reaching a working fallback.

#### 3.4 — the original report's routing argument, now with numbers

Measured over 30 days of real tasks:

| agent | n | success | avg cost | avg duration |
|---|---:|---:|---:|---:|
| builder | 236 | **97%** | **$0.0103** | **37s** |
| planning | 80 | 85% | $0.0288 | 84s |

Planning costs ~2.8x more, takes ~2.3x longer and fails ~4x as often. For work
that needs no decomposition, routing through it buys nothing and costs all
three. The original harness report argued this from four observed failures;
Phases 1 and 2 turned it into a measurement.

Phase 1 demoted routing to P2 on the grounds that continuations, not routing,
were the fix for turn exhaustion. That still holds — this is a cost and latency
optimisation, not a reliability fix, and it is scoped accordingly.

#### 3.3 — why the scenario suite is not on a schedule

The roadmap suggested running it via `cron`. The offline half could be, and is
CI-safe. The live half dispatches real tasks against the user's account, and a
suite that can be triggered by a scheduler, an import, or a default flag is a
way to spend someone else's money by accident. It requires `--confirm-spend`,
and the scheduling decision is left to the user.

## 3. Targets

Every target is checkable with a query against `data/yapoc.db` or a CI job. **All
failure-rate targets are measured over a trailing 7-day window, never all-time** — see
§1 for why that distinction matters.

| Metric | Today (trailing window) | 30 days | 90 days |
|---|---|---|---|
| Task failure rate | 9.9% (last 3d), 6.2% (since 9-01) | ≤4% | ≤2% |
| Turn-limit *failures* | 19 in 2 days | 0 (converted to continuations) | 0 |
| Work discarded on failure | 100% | 0% | 0% |
| Malformed-output failures (evaluator) | 5 | ≤1 | 0 |
| Timeout failures | 3 | ≤2 | ≤1 |
| Provider/config failures | 0 | 0 (hold) | 0 (hold) |
| Dashboard/DB error reconciliation | not tested | test green in CI | test green in CI |
| Tasks with attributed cost | 0 / 1175 | 100% of new tasks | 100% |
| Memory rows with provenance | 7 / 2480 | — | 100% of new rows |
| Tests executed in CI | 0 of 27 files | 27 files running | + scenario suite |
| Evaluator ledger staleness | 10 rounds | ≤1 round | ≤1 round |

---

## 4. Risks

- **Continuation (0.2) can mask a genuinely stuck agent.** Bound the continuation count;
  the existing stuck-loop detector still applies. A task that burns its continuation
  budget must be a *louder* failure than a turn-limit error, not a quieter one.
- **Continuation can multiply cost.** Each continuation re-pays for context. 1.2 and 1.3
  exist to make that visible; if continuation spend outruns its completion gain, cap it.
- **Partial results can be mistaken for success.** `partial` is its own status, never
  folded into `done`, and never resets the failure counter (0.3).
- **Turning on CI (2.1) will surface a wall of red.** Triage into fix / delete /
  quarantine in one pass; do not let a half-green suite become background noise.
- **Analysis over the wrong window produces confidently wrong priorities.** This document
  did exactly that once (§1). Any future ranking of failure causes states its window.
- **The evaluator observes the same data it is judged on.** Keep the 3.3 scenario
  fixtures out of the evaluator's signal inputs.
