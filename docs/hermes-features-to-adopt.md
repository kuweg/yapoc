# Hermes Agent — Features Worth Adopting in YAPOC

> **Verdict:** Hermes (Nous Research, MIT) is the closest architectural analogue to YAPOC.
> This doc is the **current-state** (Sept 2026) gap analysis. It supersedes
> `app/projects/research/yapoc_vs_hermes_comparison.md` (June 2026) and
> `hermes_multiagent_features.md`, whose "missing ❌" flags for skills/FTS5/observability
> are now **stale** — those features have since been implemented in YAPOC and were
> verified against the live repo.

**How to use:** each item below marks a genuine, verified gap. Prioritized by
value-to-effort. Repeated "already have" items were explicitly checked so we don't
re-build what exists (recurring failure mode — see notes).

---

## Legend

| Mark | Meaning |
|---|---|
| ✅ | YAPOC already has this (verified against code Sept 2026) |
| 🎯 | Worth adopting — real gap, high value |
| 🔧 | Real gap, lower priority / larger effort |
| ❌ | Recommend skipping (low value or wrong fit for YAPOC) |

---

## 1. Skills System

### Current YAPOC state (verified)
- `app/utils/tools/skills.py` implements `load_skills` + `create_skill` with **progressive disclosure L1/L2/L3** (summary → params → full procedure) — matches Hermes L0/L1/L2.
- Skills live in `app/skills/*.yaml` (4 real skills: `create_exact_file`, `docker_build`, `frontend_build`, `git_commit`).
- Backend router `skills.py` + frontend `SkillsTab.tsx` exist.
- NOTE: module docstring says `app/projects/skills/` but code uses `app/skills/` — docstring is stale, code is correct.

### Gaps worth adopting
| Gap | Hermes | YAPOC | Verdict |
|---|---|---|---|
| **Agent-managed skill creation** | `skill_manage` auto-creates a skill after complex tasks (5+ tool calls) | Only manual `create_skill`; no auto-capture hook | 🎯 High — closes the learning loop; the single most Hermes-distinctive feature |
| **Skill editing / patches** | `edit`, `patch`, `write_file`, `remove_file`, `delete` actions | `create_skill` only (no update/delete) | 🎯 Medium — without it skills are append-only |
| **Knowledge-base skills** | `/learn <dir|url|workflow>` → lean SKILL.md + `references/` per chapter | None | 🔧 Medium — currently `create_skill` requires the LLM to paste full content inline |
| **Conditional activation** | `requires_toolsets` / `fallback_for_toolsets` frontmatter | None | 🔧 Low — YAPOC has 1 shell+tools surface; little toolset variance |
| **Skill bundles** | YAML aliases group skills under one command | None | 🔧 Low — YAPOC skills are loaded by name anyway |
| **Skill security scan** | Inline scanner + NVIDIA SkillEvaluator, `.hub/lock.json` | None | ❌ Low — YAPOC's `security` gate covers runtime tool calls; skill-source scanning is niche |

**Recommended:** implement `skill_capture` as a cron-swept routine (scan recent agent memory for a repeated 3+ procedure → `create_skill`). This is cheap and delivers the learning-loop payoff.

---

## 2. Memory

### Current YAPOC state (verified — several June gaps now closed)
- `app/utils/db.py` has **FTS5** (`memory_fts` virtual table, `search_fts`) **and** hybrid search (`search_hybrid` = RRF fusion of FTS5 + cosine vector). `search_memory` sits on top. June's "❌ no FTS5" is **stale**.
- Semantic indexer (`indexer.py`, all-MiniLM-L6-v2), `memory_graph.py` + frontend memory-graph viz exist.
- Storage: `app/memory/agents/<name>/` (MEMORY/NOTES/LEARNINGS/HEALTH/ERROR/RESULT), `app/memory/user/` (PROFILE/HISTORY), `app/memory/project/` (KNOWLEDGE/CONVENTIONS/DECISIONS). Librarian = central curator.

### Gaps worth adopting
| Gap | Hermes | YAPOC | Verdict |
|---|---|---|---|
| **Frozen snapshot injection** | Memory captured once at session start (never changes mid-session) → preserves LLM prefix cache + predictable context | System prompt rebuilt every turn from files | 🎯 High — direct cost/latency win; YAPOC re-reads memory files per turn |
| **Bounded memory + consolidation-on-overflow** | Hard char limits (MEMORY 2,200 / USER 1,375); tool errors when full → agent consolidates | Unbounded growth; no limit, no overflow handling | 🎯 Medium — controls context bloat |
| **`replace` / `remove` substring actions** | `memory old_text` substring replace/delete | Only append; `agent_amnesia` wipes whole agent | 🎯 Medium — lets agents prune stale facts without nuking context |
| **Session full-text search surface** | `session_search` returns real FTS5 messages (~20ms) | FTS5 exists under `search_hybrid` but only over memory_entries, not chat-session transcripts | 🔧 Medium — expose `scope='sessions'` FTS5 path |
| **Duplicate prevention** | Exact-duplicate rejects | Append allows duplicates | 🔧 Low |
| **External memory providers** | Honcho / Mem0 / Hindsight etc. | None | ❌ Skip — YAPOC's layered local memory is strong; adding a provider is dependency creep |

**Recommended:** #Frozen-snapshot is the highest ROI — ship it alone as a first step. Add char limits + replace/remove second.

---

## 3. Delegation & Orchestration

### Current YAPOC state (verified)
- `spawn_agent` / `wait_for_agent(s)` / `execute_dag` — parallel subtasks with dependency routing exist.
- `kill_agent`, `agent_amnesia` exist.
- Intentional design choice: **Master is the only agent that spawns** (authority model) — Hermes' free-form parent→child nesting is partly a different philosophy.

### Gaps worth adopting
| Gap | Hermes | YAPOC | Verdict |
|---|---|---|---|
| **Depth / blast-radius guards** | `max_spawn_depth` (1–3), global kill switch, cost warning at depth×concurrency | Recursion unguarded; no depth cap, no cost warning | 🎯 High — protects against runaway deep chains and token blowout |
| **Per-branch cost/token rollups + tree monitor** | `/agents` overlay: live tree, per-branch cost/files, kill-without-siblings | Agents tab shows flat status; ObservabilityTab shows error counts, no delegation tree | 🔧 Medium — the UI wiring is sizeable |
| **Runtime model override on spawn** | Spawn a child with a cheaper/faster model | Model fixed per agent in agent-settings.json | 🔧 Low — YAPOC has model_manager already; override is a nicety |
| **Working-dir isolation per child** | Each child gets own dir + shell state | Single project root, `cwd` param only on shell_exec | 🔧 Medium — YAPOC is a single-repo system; per-child dirs add little |
| **Automatic cancel propagation** | Parent interrupt → children cancelled | `kill_agent` per-child, no cascade | ❌ Low — YAPOC's synchronous wait model mostly handles this |

**Recommended:** `max_spawn_depth` + cost warning on `spawn_agent`/`execute_dag` — small, high-protection win.

---

## 4. Cron / Automation

### Current YAPOC state (verified)
- Cron agent + APScheduler + NOTES.MD schedules; `memory-sweep` / skill-capture sweeps already run.
- Delivery: Telegram + morning reports + notification queue.

### Gaps worth adopting
| Gap | Hermes | YAPOC | Verdict |
|---|---|---|---|
| **No-agent script-only mode** | `no_agent=True` → run a script, zero LLM tokens, `[SILENT]` on success | Every job spawns an agent → token cost on trivial watchdogs | 🎯 High — direct cost saving on heartbeat/watchdog checks |
| **Natural-language schedule parsing** | "every 2h", "every morning at 9am" | Cron expressions only | 🔧 Low — cron is fine; NL is UX sugar |
| **Job chaining (`context_from`)** | One job's output feeds next job's context | No chaining | 🔧 Low — YAPOC has DAG for one-shot, not for scheduled repeats |

**Recommended:** script-only cron tasks with `[SILENT]` semantics — real token savings on recurring health checks.

---

## 5. Platform / Ecosystem (mostly ❌ for YAPOC now)

| Gap | Verdict |
|---|---|
| **MCP client integration** | 🎯 Medium — full greenfield (`docs/mcp-integration-design.md` dated 2026-05-20, no code). Genuine capability island. But push to *after* the high-ROI memory/delegation wins; MCP ecosystem still maturing. |
| **ACP / IDE plugins** | ❌ Skip |
| **20+ messaging gateways** | ❌ YAPOC is Telegram+UI by design; more platforms = more maintenance |
| **Multi-profile isolation** | ❌ Single-profile is a feature, not a bug, for YAPOC's scale |
| **7 terminal backends (Docker/SSH)** | 🔧 Medium-long-term; local shell suffices now |
| **Plugin system (memory/context engines)** | ❌ Dependency creep |

---

## Implementation Plan (ordered by value/effort)

### Phase 1 — High ROI, small effort (do first)
1. **`max_spawn_depth` + cost warning** on `spawn_agent`/`execute_dag` (guards runaway chains).
2. **`skill_capture` sweep** — cron routine: scan recent memory for a procedure repeated 3+ times → `create_skill` if none exists (closes the Hermes learning loop).
3. **Frozen-snapshot memory injection** — read MEMORY/PROFILE files once at session start, reuse across turns (prefix-cache win, lower latency/cost).

### Phase 2 — Medium
4. **Memory `replace`/`remove` substring actions** + optional **char-limit/consolidation** triggers.
5. **Script-only cron tasks** (`no_agent=True`, `[SILENT]`) for watchdogs.
6. **Skill edit/delete** actions + `references/` knowledge-base format.

### Phase 3 — Larger
7. **MCP client integration** (host only first; skip server-exposing side) from `mcp-integration-design.md`.
8. **Delegation tree monitor** in Observability tab (per-branch cost/token rollups).
9. **Session-transcript FTS5 search** surface.

### Explicitly NOT adopting
- External memory providers, 20+ messaging gateways, multi-profile, ACP, plugin system, skill security scanner. These add maintenance for marginal gain at YAPOC's scale.

---

## Sources
- Hermes GitHub: `github.com/NousResearch/hermes-agent` (MIT, Nous Research)
- Hermes docs: `hermes-agent.nousresearch.com/docs` (Skills, Memory, Delegation, Cron sections)
- YAPOC repo evidence: `app/utils/tools/skills.py`, `app/utils/db.py`, `app/config/agent-settings.json`, `docs/mcp-integration-design.md`, `app/backend/routers/{skills,observability}.py`
- Prior research (superseded where flagged): `app/projects/research/{yapoc_vs_hermes_comparison,hermes_multiagent_features}.md` (June 2026)

*Compiled 2026-09-01 by master. Re-verify each ✅ before building on it — the June doc demonstrates how quickly "missing" becomes "already done."*
