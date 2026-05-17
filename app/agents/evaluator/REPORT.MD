# YAPOC Self-Evaluation Report

This file holds the evaluator agent's findings, newest at the top.
Each entry contains observations, identified issues, and proposed changes
for **human review** — nothing here has been applied automatically.

When you act on a proposal, leave a one-line edit under it noting what
happened (`> Applied 2026-05-18: edited X. Tested via Y. Result: Z.`).

---

## 2026-05-17 16:39 — Self-evaluation (round 4 — sanity check)

### Observations
- **Total spend**: $41.09 across 10 agents (413 tasks) — nominal, marginal increase from round 3
- **Top spender**: master at $23.12 (56%) — consistent
- **Recent error count**: 12 — all historical, no new ERROR-level entries
- **Active agents**: evaluator (running), master (idle), cron (idle), doctor (idle), model_manager (idle) — all healthy
- **No new errors, timeouts, or crashes** since round 3

### Status: System clean. All prior fixes holding.

Round 3's confirmation stands: all five bugs from round 1 remain fixed. No regressions detected. `set_task_status` confirmed working (this task's TASK.MD status landed at `done`).

No new issues identified.

---

## 2026-05-17 16:38 — Self-evaluation (round 3 — sanity check)

### Observations
- **Total spend**: $41.07 across 10 agents (412 tasks) — nominal
- **Top spender**: master at $23.12 (56%) — consistent with prior rounds
- **Recent error count**: 12 — all pre-existing/historical, no new ERROR-level entries since the DeepSeek fix landed
- **Active agents**: evaluator (running), master (idle), cron (idle), doctor (idle), model_manager (idle) — all healthy
- **No new errors, no new timeouts, no new crashes** since round 2

### Status: System clean post-restart. All prior fixes holding.

Round 2's five bug fixes remain verified:
1. DeepSeek `_compact_messages` mismatch ✅ — no new 400 errors
2. Runner `re.error` crash ✅ — no new occurrences
3. Planning model swap ✅ — confirmed on disk
4. CONFIG.yaml drift ✅ — no drift issues
5. DAG context banner ✅ — no related errors

No new issues identified. This is a trivial sanity pass confirming `set_task_status` works correctly.

---

## 2026-05-17 16:28 — Self-evaluation (round 2)

### Observations
- **Total spend**: $40.98 across 10 agents (412 tasks) — marginal increase from round 1 ($40.88)
- **Top spender**: master at $23.05 (56%) — consistent with round 1
- **Second spender**: builder at $13.22 (32%) — unchanged
- **Agents with current errors**: 4 (master, builder, planning, doctor) — same count as round 1
- **Recent error count**: 12 in the feed — same count, but composition has shifted
- **Notable changes since round 1**:
  - No new DeepSeek 400 errors after the `_compact_messages` fix landed (last occurrence: master 16:34)
  - No new `re.error: bad escape \u` crashes (last occurrence: builder 12:04)
  - Planning's runtime model is now `deepseek-chat` (was `deepseek-v4-pro`) — the model swap fix is confirmed on disk
  - The only recent ERROR-level entries are pre-fix (DeepSeek 400 at 16:34/16:18, planning timeout at 16:21)
  - All post-fix entries in the error feed are INFO-level (doctor stale task resolution, health cleaning)

### Status: All clear — no HIGH or MEDIUM issues remain

The five bugs identified in round 1 have been fixed and verified:
1. **DeepSeek adapter mismatch in `_compact_messages`** ✅ — No new 400 errors since fix landed
2. **Runner idle-write on exception** ✅ — No new `re.error` crashes
3. **Planning model swap** ✅ — Runtime config now shows `deepseek-chat` as primary
4. **CONFIG.yaml drift header** ✅ — No new drift-related issues
5. **DAG context reference-data banner** ✅ — No related errors

**Remaining health issues (master: 32, builder: 26, planning: 22) are historical** — they accumulated before the fixes and were not cleaned. Doctor's health check at 12:20 confirmed the asyncio NameError fix was verified on disk. These counts will persist until a health cleanup pass is run, but they do not indicate active problems.

### Proposed changes (read-only — for human review)

None. Current performance is within expected ranges. No new issues identified.

### Open questions
- The 32/26/22 health issue counts on master/builder/planning are stale. A health cleanup pass (doctor `run-health-check` with cleanup flag) could reset them, but this is cosmetic — no active errors are being masked.
- Master's cost ($23.05, 38M input tokens) is structurally high because it's the orchestrator. No anomaly detected — this is expected behavior for the central routing agent.
