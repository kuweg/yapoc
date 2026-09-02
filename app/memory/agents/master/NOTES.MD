# Session 2026-09-01 — Feature audit corrections

## What happened
User asked: (1) what I thought about "YAPOC 2.0" (I needed the plan/doc — unanswered), (2) steal something useful from chebupelka.py, (3) how memory works, (4) what features YAPOC lacks from Master's perspective, (5) build the 3 features I proposed. Then "compress dialogue".

## Key result: all 3 proposed "gaps" already exist.
Verified by reading actual code — my gap analysis was WRONG. Over-claimed twice, corrected both times by repo reads. Did NOT delegate redundant builder work.

- **#1 Webhook inbound** — EXISTS. `app/backend/routers/webhook.py`: Bearer-token auth (`settings.webhook_secret`), task queueing, `callback_url`, wired into `main.py`.
- **#4 Observability dashboard** — EXISTS. `observability.py` router + frontend `ObservabilityTab.tsx`: per-agent HEALTH.MD → error counts (1h/24h), last error, recent errors, recent task durations/status.
- **#6 Live per-tool-call streaming** — EXISTS, full granularity. `BaseAgent._emit_event()` in `app/agents/base/__init__.py` pushes live Redis events: `turn_start` → `thinking_delta` → `message_delta` → `tool_call` (ToolStart, name+input) → `tool_result` (completion, name/result/is_error) → `turn_done`. Channels: `agent:{name}:activity` (Agents tab, always on) + `session:{id}:events` (Chat tab), relayed by `app/backend/websocket.py`. tool_result emit confirmed at lines ~1652-1657.

## Other findings
- `runner.py` "corruption" (byte 0x94 @ pos 0) was a TOOL READ ARTIFACT — reads fine with `start_line=1`. Not a real bug. Don't chase.
- Memory architecture: markdown source (MEMORY/NOTES/LEARNINGS/HEALTH per agent + user PROFILE/HISTORY + project + shared KNOWLEDGE) + embedding indexer (`indexer.py`, all-MiniLM-L6-v2, 384-dim, local) + SQLite hybrid retrieval (`db.py`: memory_entries + memory_fts FTS5, RRF fusion k=60). 3rd-party options ranked: sqlite-vec (best cheap upgrade, brute-force→ANN), Qdrant/Weaviate, pgvector, Pinecone. Current weakness = brute-force vector scan.
- chebupelka.py — nothing worth copying; the 3 "useful" ideas (500-char truncation preview, unknown-tool→graceful error string, content-or-None in tool_call msgs) all already handled in YAPOC.

## Lesson (strengthened)
VERIFY against repo before proposing gaps. Presented 3 features as missing; all existed. Never build on a wrong foundation — the correct move was honest correction + no delegation.

## Possible real follow-ups (none attempted; user picked "1" then dialogue compressed)
- Is Observability tab surfacing/usable in UI?
- Webhook API-status surface / callback-retry display?
- Cost/latency time-series metrics (beyond HEALTH.MD)?
- Audit a different layer (e.g. AgentFlowPane rendering these events).

## 2026-09 — Beyond-Hermes feature additions (not in hermes_multiagent_features.md)

Genuinely NEW angles beyond the existing Phase 1–5 Hermes-derived plan:

1. **`delegate_task` as a real tool** — today spawning is master-side primitive only. Give sub-agents a runtime `delegate_task(goal, context, allowed_tools)` tool so any agent fans out work mid-turn without TASK.MD plumbing. Biggest missing primitive.
2. **Child-side token budget** — parent sets token cap per child; child hard-stops + returns partial results when exhausted. Prevents runaway agents.
3. **Structured result contract** — typed result schema `{status, summary, files[], artifacts[]}` downstream agents parse deterministically instead of free-text.
4. **Time-based memory decay** — auto-archive MEMORY.md entries older than N days to cold store; keeps hot memory dense. YAPOC has compaction but no aging-out.
5. **Per-session working context that survives restart** — CONVERSATION.md frozen + restored, beyond RESUME.md resume triggers.
6. **Negative knowledge** — documented "things we tried that didn't work" list to prevent re-litigating rejected approaches.
7. **Budget-aware autonomous mode** — global daily token/$ cap shared across cron+doctor+goals; scheduler checks remaining budget per goal before spawning.
8. **Escalation ladder on repeated failure** — N consecutive failures → auto-disable job + page user, not silent infinite retry.
9. **Planned-downtime queue** — jobs firing during maintenance window get queued, run on next tick instead of dropped.
10. **Cost/latency time-series** — per-agent per-task $$ + ms stored & graphed, feeds model_manager downgrade decisions (HEALTH.MD only has error counts today).
11. **Skill verification** — feedback loop: "did the skill produce expected outcome" auto-demotes bad procedures. (Manual version already exists via self-improvement loop.)


## 8-feature batch — verified status (2026-09-01)
## Feature batch status — ALL 8 verified against code this session

| # | Feature | Status | Where / blocker |
|---|---------|--------|-----------------|
| 1 | delegate_task runtime tool | ✅ DONE | `DelegateTaskTool` in `app/utils/tools/delegation.py` (~L1420); allowed_tools whitelist enforced; registered in registry |
| 2 | Child token budget | ⛔ NOT DONE | `token_limit` in delegate_task schema is "accepted for forward-compat and ignored"; `# (params.get("token_limit"))` commented out at ~L1490 |
| 3 | Structured result contract | ✅ DONE | `app/agents/base/result.py` (AgentResult/parse_result/to_result_json), backward-compatible coercion |
| 4 | Memory decay to cold store | ⛔ NOT DONE | no `data/memory_archive/` dir; needs base-layer runtime hook (PROTECTED) |
| 5 | Survivable CONVERSATION.md | ⛔ NOT DONE | no CONVERSATION.md anywhere; restore logic needs base-layer (PROTECTED) |
| 6 | Negative knowledge store | 🟡 PARTIAL | `app/agents/shared/NEGATIVE_KNOWLEDGE.md` + librarian PROMPT.MD routing rule (L42-56) LANDED. Context INJECTION BLOCKED — `app/agents/base/context.py` + `__init__.py` are gate-protected |
| 7 | Budget-aware autonomy | 🟡 PRE-EXISTING | `app/utils/cost_governor.py` + `daily_autonomous_budget_usd` (settings) existed BEFORE batch. No new unified-cap work layered on |
| 8 | Cron escalation ladder | ✅ DONE | dispatcher L218 record_cron_success (success), L365/L455 record_cron_failure+disable-notify (timeout/error). helpers in cron_parser.py |

## Core blocker
`app/agents/base/` entire dir is gate-protected (context.py, __init__.py, runner.py — core orchestration). Builder + shell both blocked. Features needing base-layer runtime hook for context INJECTION (4, 5, and the injection-half of 6) cannot be wired there.

## Non-protected landing spots (viable)
- Feature 2: `app/utils/tools/delegation.py` (NOT protected) — child token budget enforced in DelegateTaskTool/WaitForAgentTool
- Feature 7: `app/utils/cost_governor.py` (NOT protected) — unify to one daily cap
- Features 4/5/6 "record but don't inject": standalone maintenance helpers called by librarian/cron at runtime on non-protected paths. Context-injection into prompt stays blocked unless base/ gate is opened for a carefully-scoped edit.

## Lesson
DAG/async-planning produced truncated no-op results. Working pattern = synchronous spawn_agent(builder) + wait_for_agent + DIRECT verification (used for #8). Gate blocks only base-layer; utils/tools + utils/* are fair game.
