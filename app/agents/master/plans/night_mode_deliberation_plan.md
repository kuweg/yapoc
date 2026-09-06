# ARCHITECTURAL PROPOSAL: "Night Mode" Overnight-Autonomy Layer

## Goal
A user types "Make prototype of X" at night and leaves. In the morning they
expect a fully-functional, tested prototype of X — no YAPOC failure, no
half-finished build.

## Current shortfall (4 failure classes against this goal)
1. **Turn/process death kills long work** — per-turn timeouts + dropped
   subprocesses chop multi-hour work (evidenced by TimeoutError→CancelledError
   in master HEALTH.MD). RESUME.MD auto-recovers *state* but nothing
   *re-launches and continues* a half-done prototype after restart.
2. **No autonomous initiation loop** — work starts only when the user messages
   in and a turn runs. Nothing keeps an unfinished goal being worked until done.
3. **Verification is reactive, not enforced** — evaluator runs when notified,
   not as a mandatory gate after each build milestone. A prototype can
   "complete" while broken.
4. **No overnight operator** — when doctor flags a failure at 3am, nothing wakes
   to retry/re-plan/revert.

## Proposed architecture — a background "night worker" layer
Promote the user's request to a persistent structured **goal** with acceptance
criteria, then drive it via an autonomous scheduler until done or budget-exhausted.

### Component A. Goal intake & state
- User message ("Make prototype of X") → structured goal {title, description,
  acceptance_criteria, max_milestones, budget_cap_usd} persisted to a
  NIGHT_GOALS.json / GOALS.MD extension.
- Distinct state per milestone: pending | running | done | failed(retry_count).

### Component B. Software-decomposition into resumable milestones
- planning agent decomposes the prototype into `planning` milestone units.
- Each milestone = {id, description, verify_cmd/test, depends_on}.
- Milestone journal written to disk *after every step* — the unit of resume.

### Component C. Persistent worker & checkpoint/resume
- A long-lived worker (could be a new `night_runner` agent OR a hardened cron
  task running each cycle) that executes milestones in order.
- After each milestone: persist progress → advance pointer.
- On timeout/crash/restart: worker re-reads journal, resumes at the last
  incomplete milestone. This closes failure class 1 structurally.

### Component D. Mandatory verify gate (auto-fix loop)
- After each milestone, spawn **evaluator** to run build+test/verify.
- Pass → next milestone. Fail → spawn fix agent with the evaluator's findings;
  bounded retries (e.g. 3) per milestone before the milestone is marked failed
  and the goal escalates. Closes failure class 3.

### Component E. Autonomous scheduler / night operator
- cron-style driver polls unfinished goals every N minutes (overnight).
- Re-engages the worker; applies doctor health findings; retries failed work
  with backoff; escalates after retry budget. Closes failure classes 2 & 4.
- Morning: push a Telegram summary to the user regardless of outcome.

### Component F. Budget guard (hard cost cap)
- cost_governor already exists — enforce a per-goal + per-night USD/token cap.
- Worker halts + escalates if cap hit, never burns money in a runaway retry loop.

## Key design decisions Concilium must arbitrate
D1. **Where does the persistent worker live?** — new `night_runner` agent
    (clean, isolated, new failure surface) vs. hardened cron task (less new
    code, but cron is single-shot per cycle — needs stateful resume).
D2. **Checkpoint/resume semantics** — milestone-granularity journal on local
    disk vs. deeper step-granularity. Trade-off: resume granularity vs. I/O &
    context bloat.
D3. **Verify-gate failure handling** — auto-fix-with-bounded-retries vs.
    escalate-to-user-immediately on first failure. Trade-off: autonomy vs. risk
    of a broken prototype "passing" after forced retries.
D4. **Scheduler location** — extend cron agent vs. new dedicated scheduler.
D5. **Budget defaults** — sensible per-goal cap when user gives none.
D6. **What "tested prototype" means per prototype type** (web app vs CLI vs
    script) — acceptance criteria need a sane default template.

## Affected subsystems / files (initial, not exhaustive)
- app/agents/cron/ (scheduler) — scheduling logic
- agent-settings.json + possibly new `night_runner` agent
- app/utils/cost_governor.py (budget hooks)
- GOALS.MD / goal_proposer.py (goal persistence)
- app/agents/planning + evaluator (decomposition + verify gate wiring)
- new: night-mode journal + scheduler + resume logic files

## Constraints
- Reversible via git autocheckpoint (no .env, no project/data mutation).
- Async-first; snake_case; compact JSON (user conventions).
- Must not run cost-unbounded overnight.
- Must deliver a morning status report via Telegram regardless of outcome.
