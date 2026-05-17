# Self-Improvement Loop — design + roadmap

## Status: v1 shipped (read-only)

The Evaluator Agent (`app/agents/evaluator/`) reviews YAPOC's recent performance and writes a human-reviewable proposals report. **It does not apply changes.** This is the safe foundation for roadmap #10 (Self-Improvement Loop) — auto-apply is intentionally deferred until #3 (git integration) and #4 (approval gates) land.

## v1 components (current)

| Piece | Where | Purpose |
|---|---|---|
| `evaluator` agent | `app/agents/evaluator/` | The agent itself — prompt, config, file artifacts |
| `get_recent_signals` tool | `app/utils/tools/evaluator_signals.py` | One call returns observability snapshot + per-agent config + sandbox map |
| `REPORT.MD` | `app/agents/evaluator/REPORT.MD` | Append-only log of timestamped findings. Newest entry at the top. |
| Sandbox enforcement | `app/agents/evaluator/CONFIG.yaml` (sandbox.forbidden) | Evaluator can ONLY write to its own dir. Even if the LLM tries to apply a proposal, the file-mutation tools block it. |

**Invocation:** master spawns the evaluator like any other sub-agent.
- Example user prompt: *"Run a self-evaluation of YAPOC."*
- Master calls `spawn_agent("evaluator", task=...)`, `wait_for_agent`, then surfaces the evaluator's 3-line summary.

**Hard turn budget:** evaluator's PROMPT.MD enforces a 20-turn cap with explicit "stop gathering" guidance at turn 7. Prior versions ran out of turns mid-analysis without writing the report; the budget is now non-negotiable.

**Output contract:** every entry in REPORT.MD has:
- `## YYYY-MM-DD HH:MM — Self-evaluation (round N)` header
- **Observations** — bullet list of key signals with numbers
- **Top issues** — 3–5 ranked by impact (high/medium/low) with data citations
- **Proposed changes** — each with `Target`, `Change` (before/after), `Why`, `Risk`
- **Open questions** — what to disambiguate next round

## v2 — auto-apply path (deferred)

These pieces are designed but **NOT built**. They require #3 (git) and #4 (approval gates) as safety prereqs.

### Component 1 — Proposal queue

When a human marks a proposal "approved" in REPORT.MD (e.g., flips a `[ ]` to `[x]`), an APScheduler job picks it up and routes it to the applier pipeline.

```markdown
### Proposed changes
1. **Target**: `app/agents/builder/CONFIG.yaml`
   **Status**: [x] approved              ← human flips this
   **Change**: ...
   **Why**: ...
   **Risk**: ...
```

Keeps approval in-band with the proposal so context isn't lost. No separate queue file to keep in sync.

### Component 2 — Applier pipeline

Sequence per approved proposal:
1. **Snapshot**: git commit the current state with `pre-apply: <proposal-id>` message. Requires roadmap #3.
2. **Apply**: route to keeper or builder based on target file. Use existing `spawn_agent` with a task scoped to the specific edit.
3. **Verify**: spawn a verifier (existing test runners / smoke scripts).
4. **Commit or rollback**:
   - Verify passed → commit applied change with `apply: <proposal-id>` message
   - Verify failed → `git reset --hard HEAD~1` to roll back to the snapshot, mark proposal `[!] failed` in REPORT.MD with reason

### Component 3 — Approval gates

For changes flagged as risky (touch a sandbox-forbidden path, edit master's prompt, change adapter settings), require human approval through the UI before applying. Requires roadmap #4.

### Component 4 — Scheduled cadence

APScheduler job that runs the evaluator daily (or on demand). Currently manual — user asks master to run it. Adding cadence is small (mirror the existing doctor/model_manager APScheduler ticks) but should wait until the proposals have demonstrably useful signal.

## Why v1 is shipped this way

The evaluator's prompt explicitly says it cannot apply changes. The agent's sandbox enforces it. Two layers of defense before we add a third (approval gates).

The pattern is: **insight ≫ action, until action is safe.** The evaluator generating reports that get manually reviewed gives us:
- A real corpus of self-improvement proposals to study (do they hold up?)
- Time to find prompt-engineering mistakes in the evaluator before they have apply-side consequences
- An immediate signal-gen surface that's useful on its own

## Open questions for v2

- **Proposal idempotency**: if the evaluator re-proposes the same change after a human approved+applied it, should it auto-mark "already applied"? Needs a stable proposal-id scheme.
- **Conflict between rounds**: round 5 proposes "revert the change round 3 proposed". How do we surface that?
- **Cost budget**: a daily evaluator run is cheap (~$0.05 in current testing). But if we add per-domain evaluators (cost evaluator, quality evaluator, etc.), need a budget cap.

## Files to know

- `app/agents/evaluator/PROMPT.MD` — methodology + turn budget + output contract
- `app/agents/evaluator/CONFIG.yaml` — tools list, sandbox forbidden-paths, runner limits
- `app/agents/evaluator/REPORT.MD` — the living findings log
- `app/utils/tools/evaluator_signals.py` — `get_recent_signals` tool
- `docs/roadmap.md` — feature #10 entry covering the original L-effort scope
- `docs/test-findings.md` — known bugs the evaluator was specifically asked NOT to deduce (it should rediscover them from signals)
