# Memory Consolidation — 2026-09-06

## Scope
Checked every agent's memory files plus the user + project stores. Summarized each,
archived stale/test content, and flagged structural duplication.

## Per-agent memory inventory

| Store | Files | State |
|-------|-------|-------|
| **master** | MEMORY.MD, NOTES.MD, LEARNINGS.MD, GOALS.MD, MORNING_REPORT.md, RESUME.MD, HEALTH.MD | 5 learned rules + UI-observability investigation notes. MEMORY had stale test block (cleaned). RESUME already consumed. |
| **concilium** | NOTES.MD (MEMORY/HEALTH empty templates) | Architecture + deepseek-chat counselor gotchas. Useful. |
| **cron** | NOTES.MD, MEMORY.MD | skill-capture-sweep 3am schedule + sweep log. Useful. |
| **doctor** | HEALTH_SUMMARY.MD, HEALTH.MD | SUMMARY (2026-09-06): 52 issues/16 agents + runaway-cost alerts. HEALTH.MD carries stale 06-07 warnings (left as history). |
| **evaluator** | REPORT.MD | Round 85 (2026-09-06): clean window, 0 errors, watch-items on master cost + builder temp. |
| **model_manager** | NOTES.MD, REPORT.MD | NOTES = live audit (2026-09-06). REPORT = stale (2026-06-07) → superseded banner added. |
| **shared** | KNOWLEDGE.MD | 286 lines, active, canonical. |
| **user** | PROFILE.md, HISTORY.md | Current through 2026-09-06. Active. |
| **project** | KNOWLEDGE.md, DECISIONS.md, CONVENTIONS.md | KNOWLEDGE.md is a partial migration → flagged. DECISIONS/CONVENTIONS fine. |

Agents with **no memory files** (fresh/curator-only): builder, keeper, librarian,
planning, researcher, security, mcp, tester, telegram-killer.

## Actions taken
1. ✅ **Archived stale `model_manager/REPORT.MD`** — 3-month-old audit with outdated
   model bindings (deepseek-chat primary, claude-sonnet-4-6 fallbacks). Added
   SUPERSEDED banner pointing to NOTES.MD (2026-09-06).
2. ✅ **Removed test data from `master/MEMORY.MD`** — deleted the 20-turn
   `[SIMULATED DIALOGUE FOR MEMORY-SWEEP TEST]` block (synthetic scaffolding).
3. ✅ **Flagged `app/memory/project/KNOWLEDGE.md`** — added a PARTIAL/STALE banner:
   it holds only ~8 entries vs the canonical 286-line `shared/KNOWLEDGE.MD`.

## Findings surfaced (not auto-deleted — history/structural)
- `doctor/HEALTH.MD` keeps 2026-06-07 warnings (builder `re.error` crash, port 8000
  conflict) — historical, since resolved; health logs are append-only.
- `shared/KNOWLEDGE.MD` ↔ `project/KNOWLEDGE.md` overlap — migration was incomplete;
  `shared/KNOWLEDGE.MD` is canonical. A real dedupe would need context.py + indexer
  agreement on which store wins.
- `master/GOALS.MD` `## Proposed` holds one autonomous proposal (2026-06-07,
  "29 consecutive zero-health rounds") — read-only by design, left untouched.
