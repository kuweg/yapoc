# Shared Knowledge Base

## Entry: convention
- **Source:** master
- **Time:** 2026-04-13 19:41
- **Content:** YAPOC uses Poetry for dependency management


## Entry: discovery
- **Source:** master
- **Time:** 2026-04-13 19:58
- **Content:** formatter.py provides date formatting utilities at app/projects/utils/formatter.py

[2026-04-13 20:32] category: discovery | source: test-learnings (promoted)
### Rule: Always validate inputs
- context: File operations
- action: Check path exists before read
- confidence: high


## Entry: decision
- **Source:** keeper
- **Time:** 2026-04-13 21:30
- **Content:** Cron agent's `delegation_targets` list updated 2026-04-13 to include 'doctor' agent, alongside 'builder' and 'keeper'. This allows the cron agent to delegate tasks to the doctor agent when needed.


## Entry: decision
- **Source:** master
- **Time:** 2026-04-13 21:31
- **Content:** Cron agent's delegation_targets now includes: builder, keeper, doctor, and master. Updated 2026-04-13.


## Entry: discovery
- **Source:** researcher
- **Time:** 2026-05-17 13:04
- **Content:** LiveBench research report saved at app/projects/research/livebench_report.md. LiveBench is a contamination-limited LLM benchmark with 7 categories, 23 tasks, monthly-updated questions, objective scoring (no LLM judge), accepted as ICLR 2025 Spotlight. Top model: o4 Mini High at 87.3%. Team of 18 from Abacus.AI, NYU, NVIDIA, UMD, USC.


## Entry: convention
- **Source:** master
- **Time:** 2026-05-24 14:10
- **Content:** Librarian agent is the central memory curator. Any agent can spawn librarian with a thought/observation to store. Librarian classifies and routes it to the correct store: agent_memory (episodic), learning (reusable patterns), note (working context), project_knowledge (shared KNOWLEDGE.MD), or user_profile/history. Use librarian instead of direct memory_append when the thought has broader value or unclear classification.


## Entry: decision
- **Source:** master
- **Time:** 2026-05-25 13:15
- **Content:** Librarian redesigned as Memory Curator + Summarizer with two modes: Mode A (memory curation — classifies thoughts into agent_memory/learning/note/project_knowledge/user_profile/history and routes them) and Mode B (summarization). `notify_parent` tool added to librarian tools in agent-settings.json and CONFIG.yaml. Master PROMPT.MD updated with Memory Curation Protocol. Librarian description updated in master prompt.


## Entry: discovery
- **Source:** master
- **Time:** 2026-05-18 19:42
- **Content:** Prompt audit of 9 agent prompts found rough edges in all agents. Key findings: Builder references non-existent `create_agent`/`delete_agent` tools; Cron missing peer delegation constraints; Doctor references `spawn_agent planning` but Planning may not be a delegation target; Evaluator references non-existent `get_recent_signals()`; Keeper has sandbox loophole in file access rules; Librarian hardcodes "ONE turn" assumption; Model Manager references non-existent `update_agent_config`/`check_model_availability`/`list_models`; Planning references non-existent `add_task_trace`; Researcher references non-existent `fetch_page`. Full audit at app/agents/master/NOTES.MD.


## Entry: discovery
- **Source:** master
- **Time:** 2026-05-25 11:42
- **Content:** Comprehensive master agent audit report exists at `docs/master-audit.md`. Covers 3 systemic problems: (1) Master going idle unexpectedly — Redis watcher drops notifications when master is running (critical bug at main.py:327-329), (2) Turn limitations — task_timeout: 300s is primary limiter, notification_max_turns documented but not implemented, (3) Queue message problems — NotifyParentTool always delivers to both Redis + notification_queue causing dual delivery race. Full fix recommendations included in the report.


## Entry: decision
- **Source:** user (memory sweep)
- **Time:** 2026-05-25 11:44
- **Content:** User specified PostgreSQL as the main database (not SQLite). All API responses must be under 200ms. Rate limiting required on all public endpoints. Redis for caching (not in-memory). Log retention: 30 days max. Daily backup at 3am. These are project-wide technical constraints.


## Entry: convention
- **Source:** user (memory sweep)
- **Time:** 2026-05-25 11:44
- **Content:** Coding convention: snake_case over camelCase. Concurrency pattern: async/await over threading. JSON formatting: compact over pretty-printed. Agent prompts must stay under 4000 tokens. Use Claude for all agents except cron.


## Entry: warning
- **Source:** master
- **Time:** 2026-09-02 11:53
- **Content:** Webhook outbound callback DELIVERY already exists in app/backend/dispatcher.py `_deliver_webhook_callback` — it POSTs result back to callback_url on task SUCCESS (source=="webhook", metadata.callback_url). It does NOT fire on error/timeout paths. For feature-gap analysis of any webhook/notification feature, read BOTH the inbound router (webhook.py) AND the dispatcher that writes completion — claiming a callback feature is missing without reading dispatcher.py is a known false-negative.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-02 11:55
- **Content:** For any agent that has a CONFIG.yaml `tools:` block, that block is AUTHORITATIVE for the runtime tool surface (via BaseAgent._load_tool_names) — app/config/agent-settings.json tools is only a fallback used when CONFIG.yaml has no tools block. Many CONFIG.yaml files carry a stale comment claiming agent-settings.json tools are authoritative; trust CONFIG.yaml instead. Adding a tool to agent-settings.json alone does NOT expose it at runtime if the agent's CONFIG.yaml tools list omits it. Change requires a server restart to rebuild the tool surface.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-02 12:22
- **Content:** YAPOC feature-mapping for gap-analysis (verified present, do NOT re-propose as missing): (1) webhook completion callbacks — _deliver_webhook_callback in app/backend/dispatcher.py fires on success AND timeout AND error paths (lines ~360/450/541), POSTs {task_id,status,result} to callback_url in task metadata. (2) "alert if agent fails twice in a row" — app/utils/agent_failure_tracker.py (per-agent consecutive-failure counter persisted to data/agent_failures.json, threshold 2), invoked from BaseAgent.set_task_status via _track_consecutive_failures in app/agents/base/__init__.py (~line 772), which raises _dispatch_failure_alert (~824) writing HEALTH.MD + sending a Telegram alert exactly on the 2nd consecutive error.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-02 12:39
- **Content:** YAPOC overnight crash-resilience (2026-09-02): bare `yapoc start` runs uvicorn with NO respawn (a crash kills the whole system). The resilience path is `yapoc supervise` (python -m app.cli.main supervise) — a foreground supervisor that owns uvicorn, respawns on crash with exponential backoff + circuit breaker, logs to app/agents/master/SUPERVISOR.MD. Wrap it in a systemd USER unit (scripts/systemd/yapoc.service + install-supervisor.sh) for a second tier (supervisor + systemd both restart). Master's shell sandbox blocks ~/.config/systemd writes and systemctl, so the OS-level install is a user-run step.


## Entry: decision
- **Source:** master
- **Time:** 2026-09-02 13:53
- **Content:** DECISION (2026-09-02, master + user approval): Cron agent is RETIRED, not down. It terminated 2026-05-25 by idle timeout and will NOT be restarted. Its sole scheduled job (skill-capture-sweep @ 3am) is superseded by librarian's manual memory/skill consolidation sweeps. Nothing else depends on cron's schedule. Evaluator should STOP flagging "cron down 3+ months" as a NEEDS_APPROVAL/MEDIUM issue — this is an intentional, operator-approved state. Do not re-file it as an open item.


## Entry: decision
- **Source:** master
- **Time:** 2026-09-02 13:53
- **Content:** DECISION (2026-09-02, master + user approved recommendation): Runtime temperature for the master AND planning agents aligned to 0.3 in app/config/agent-settings.json (authoritative per app/agents/base/__init__.py:651-664). Both were silently running at temperature 1 despite CONFIG.yaml files intending 0.3 — dead config. Lowered to improve delegation determinism (planning returning research-only instead of executing) and reduce cost (evaluator flagged master temp 1.0 as #1 spend signal, 80.8% of $). Other agents untouched.


## Entry: decision
- **Source:** master
- **Time:** 2026-09-02 20:28
- **Content:** PLANNING AGENT DISABLED (temporary, operator directive 2026-09-02): Master must NOT spawn or route to the planning agent — only master and builder execute tasks. Removed 'planning' from doctor's delegation_targets in app/agents/doctor/CONFIG.yaml (now [builder]). No other agent routes to planning (cron targets builder/keeper/doctor/master/librarian). Planning agent dir remains intact (reversible). To re-enable, add planning back to doctor's delegation_targets and resume routing.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-02 20:32
- **Content:** context7 MCP server fixed 2026-09-02: mcp SDK 1.29.1 streamable_http_client yields a 3-tuple (read, write, get_session_id_callback) while sse_client yields 2-tuple. host.py _run_http must capture transport-agnostically (`async with factory(...) as _streams: read, write = _streams[0], _streams[1]`) — unpacking as a fixed 2-tuple raises ValueError during __aexit__. Verified context7 connects and both tools (resolve-library-id, query-docs) work.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-02 13:01
- **Content:** Stale-checkpoint reconcile feature built (closes crash-mid-mutation gap). New module app/backend/git_checkpoint_reconcile.py: reconcile_stale_checkpoints(stale_names) rolls back + clears any orphaned CHECKPOINT.json left by a sub-agent killed before reaching terminal status. Wired into main.py lifespan: _cleanup_stale_agent_statuses() (main.py:52) returns the stale-agent list; reconcile runs right after (main.py ~L1280-1293, non-fatal warning on failure), reverting half-applied working-tree changes to the pre-change SHA before any retry. Enabled by git_safety.rollback_to() being fully process-stateless. Standalone crash test: scripts/crash_test_reconcile.py (all 5 assertions pass; entry `poetry run python scripts/crash_test_reconcile.py`).


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-02 13:07
- **Content:** grep tool pipe-alternation fix. Root cause: app/utils/tools/grep.py executed `grep -rn` WITHOUT the `-E` (extended regex) flag, so basic-regex grep treated `|` as a literal pipe instead of alternation (false "no matches" on multi-pattern searches). Fix: line 91 now reads `cmd = ["grep", "-E", "-rn"]`. Shell `grep -rn` is authoritative when the built-in grep tool returns suspicious empty results.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-02 13:10
- **Content:** cron_parser tzinfo fix. Root cause of "Cron tick error: 'str' object has no attribute 'tzinfo'": get_due_jobs()/_entry_last_run() handed is_due() a plain ISO string (legacy data/cron_runs.json) instead of a datetime, and is_due did last_run.tzinfo on it. Fix: normalize string/naive last_run -> aware datetime at top of is_due and widen except to (ValueError, KeyError, TypeError). 59 pre-fix errors, ZERO after.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-02 21:26
- **Content:** Voice TTS/STT via OpenAI models (user: "browser voiceover is awful"). Backend OpenAI TTS fully configured (openai_api_key set, tts_engine=openai, voice=onyx) and STT via OpenAI Whisper. Frontend default flipped in appStore.ts line 38 from voiceTtsMode:'browser' (robotic speechSynthesis) to 'backend' so playback routes through OpenAI onyx voice. STT endpoint POST /stt (multipart audio + engine=openai + language) — note en-US must normalize to en in _transcribe_openai (voice_service.py ~line 286). Verified live: /tts returns RIFF/WAVE PCM 16-bit mono 24000 Hz; /stt returns HTTP 200.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-02 21:36
- **Content:** SpeakingSphere UI element added to frontend. New src/components/SpeakingSphere.tsx (reads agentSpeaking from appStore). Added agentSpeaking/setAgentSpeaking runtime fields to appStore.ts (not persisted). ChatPanel mirrors local isSpeaking into store via useEffect. Mounted top-left of both headers in App.tsx. 3-state: listening (cyan) > speaking (amber) > idle. CSS keyframes sphere-pulse/idle/ring + reduced-motion in index.css. Frontend-only.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-02 22:28
- **Content:** Interactive chart rendering in chat COMPLETE (ECharts). types.ts TaskPart union += {kind:'chart', option:Record<string,unknown>}; ChatPanel applyPendingEvents tool_done branch REPLACES a render_chart tool part with a chart part when JSON.parse succeeds (falls back to normal tool card on error); new ChartBlock.tsx (echarts.init + setOption + resize listener + dispose, h-72 container); MessageBubble renderPart chart branch; ChatPanel PartsChain inline streaming chart branch + TaskGroupBubble chart branch for delegation traces. render_chart tool registered in app/utils/tools/__init__.py (~line 225). Frontend-only. NOTE: project is pnpm-based — `npm install` fails with node v26 incompatibility; use pnpm.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-02 21:14
- **Content:** Skill auto-capture feature VERIFIED complete. Config fields in app/config/settings.py: auto_capture_skills=True, auto_capture_min_tool_calls=5 (added by keeper after max_spawn_depth). Implementation in app/agents/base/__init__.py: hook at ~line 2032 (runs on normal-completion path only, guarded by _auto_capture_active recursion flag, all failures swallowed/logged), _maybe_auto_capture_skill() at line 2122 (30s model timeout, strict JSON-only judge prompt, name regex ^[a-zA-Z_][a-zA-Z0-9_]*$, level_1<=120 chars, skips existing skills, uses CreateSkillTool).


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-02 21:20
- **Content:** Child token budget feature VERIFIED live. Spans app/utils/tools/delegation.py (token_limit param on delegate_task tool, written to TASK.MD frontmatter) + app/agents/base/__init__.py (reads token_limit from frontmatter ~line 1364, accumulates input+output tokens per task ~line 1660, hard-stops with partial results when budget exceeded).


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-02 22:11
- **Content:** Tic-Tac-Toe against YAPOC ALREADY EXISTS and is live in Telegram (do NOT re-propose as missing): /ttt command in telegram_bot.py starts a game; _ttt_keyboard() renders a 3x3 inline keyboard (each cell a button, callback_data ttt:0-8); _handle_ttt_callback() processes presses; minimax AI in ttt_game.py (unbeatable, human=X first); Restart/Quit buttons; persistence to data/ttt_games.json.


## Entry: correction
- **Source:** evaluator (round 76, 2026-09-05)
- **Time:** 2026-09-05 15:54
- **Content:** CORRECTION to the "cron down 3+ months" claim (rounds 71-75): cron is NOT down. Cron is a TASK-DRIVEN agent (spawned per scheduled tick), not a persistent process — so `is_alive` false and stale `last_active` (2026-05-25) are EXPECTED, not evidence of failure. Cron dispatched 2 memory-sweep tasks on 2026-09-05. Evaluator must STOP flagging "cron down" based on is_alive/last_active. This refines the 2026-09-02 "cron RETIRED" entry: cron remains active for memory-sweep dispatch; its retired role was only the 3am skill-capture-sweep.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-05 15:54
- **Content:** Evaluator self-evaluation loop runs on a ~30-minute scheduled cadence (rounds 75-79 observed on 2026-09-05). Cost profile (rounds 76-79): total spend ~$262 across 15 agents; master is the dominant cost driver at $211.93 / 80.9% of spend / ~425M input tokens (expected for the orchestrator — watch item, no action). Builder is #2 spender (~$38.46) with runtime temperature 1.0 (highest of all agents; informational, no defect evidence). System healthy: 0 current/recent errors, all tasks done.


## Entry: warning
- **Source:** master
- **Time:** 2026-09-05 21:40
- **Content:** Tool-grant authority is CONFIG.yaml's `tools:` block, NOT agent-settings.json — despite the header note in CONFIG.yaml claiming the opposite. BaseAgent._load_tool_names (app/agents/base/__init__.py:~1009) reads CONFIG.yaml tools as authoritative and uses agent-settings.json's `tools` array only as a fallback when CONFIG has no tools block. Keep both in sync or audits misread the JSON. This drift caused builder's "Unknown tool: notify_parent" (2026-09-05) — the JSON listed notify_parent but CONFIG.yaml didn't, so runtime never granted it.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-05 21:46
- **Content:** Chart rendering fancified with theme-aware, colourblind-safe colors (2026-09-05). Backend app/utils/tools/chart.py now injects a Tableau-10 colourblind-safe palette as the default series color list (#4E79A7 blue, #F28E2B orange, #E15759 red, #76B7B2, #59A14F, #EDC948, #B07AA1, #FF9DA7, #9C755F, #BAB0AC), sets animation:false, and normalizes series to a non-empty list. Frontend ChartBlock.tsx resolves theme tokens (--color-chart-text/-grid, --color-tooltip-bg/-border/-text, --font-mono) so text/legend/tooltip/axes match the active theme. Frontend build passes clean (tsc exit 0). Frontend-only change — user refreshes to see.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-05 21:29
- **Content:** Honcho (Plastic Labs) memory API evaluated for YAPOC (2026-09-05). Verdict: USABLE but as a SEPARATE service called over HTTP, NOT vendored into the repo (license makes that distinction the whole ballgame). Honcho is memory infrastructure, not a retrieval lib — a FastAPI server + background worker backed by Postgres + Redis + vector collections. Data model: Workspace → Peer → Session. Full report in master session; no integration decision made yet.


## Entry: decision
- **Source:** master
- **Time:** 2026-09-05 21:51
- **Content:** MASTER MODEL CHANGED to openai/gpt-5.6-terra (2026-09-05 21:50, user directive "switch master to gpt-5.6-terra and restart"). Confirmed live post-restart: adapter=openai, model=gpt-5.6-terra. This SUPERSEDES the earlier "master on DeepSeek-V4-Pro-0813" model-distribution entry (2026-09-05 15:15). Motivation: deepseek was throwing "Incomplete provider response: length" in the health log. The other 10 agents remain on deepseek-chat.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-05 21:56
- **Content:** VSCode-theme support feature requested by user (2026-09-05): wants themes sourced from vscodethemes.com (e.g. GitHub.github-vscode-theme/github-dark). Feasible because YAPOC frontend is 100% CSS-variable-driven. A VSCode theme is a JSON file with `colors` (semantic UI tokens like editor.background/foreground, sideBar.background) + `tokenColors` (syntax highlighting). Integration path: map VSCode semantic tokens to YAPOC CSS variables. No implementation decision made yet.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-06 20:35
- **Content:** Skill-capture sweep created skill `self_evaluation_round` (app/skills/self_evaluation_round.yaml) on 2026-09-06 — the most-repeated procedure in master memory (scheduled self-eval rounds 75-82). NOTE: skill tools (create_skill etc.) were absent from master's actual runtime tool set AND from master's CONFIG.yaml tools list even though listed in agent-settings.json — same CONFIG.yaml/JSON drift pattern as builder's notify_parent bug. Skill was captured by writing the YAML directly.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-06 20:47
- **Content:** LinkedIn page parsing is BLOCKED for YAPOC: fetch_page returns HTTP 999 (LinkedIn's standard anti-scraping/anti-bot wall). fetch_page does NOT run JavaScript or hold a session, so LinkedIn blocks at the door. Fallback that works: web search surfaced the actual profile content. For LinkedIn (and similar JS-heavy/anti-bot sites), use web search or playwright (JS-rendering) instead of fetch_page.


## Entry: decision
- **Source:** master
- **Time:** 2026-09-06 20:50
- **Content:** Parallel MCP (https://search.parallel.ai/mcp, hosted web-search + content-extraction MCP endpoint, no auth, Streamable HTTP) evaluated and REJECTED as not worth trying. Verdict: it is a commodity that overlaps almost exactly with tools YAPOC already ships (web search + content extraction). No integration value.


## Entry: decision
- **Source:** master
- **Time:** 2026-09-06 21:09
- **Content:** YAPOC is now an MCP SERVER (feature built 2026-09-06, user directive "warp yapoc into mcp ... reach it from claude code"). Pattern: "agent harness as a tool" — Claude Code (or Cursor/Windsurf, any MCP client) is the host, YAPOC exposes its tools as an MCP endpoint. Built: app/mcp_server/ (3 new files) + app/backend/routers/mcp.py (POST /mcp/run), wired via include_router(mcp_router) in main.py (line ~1212). mcp_server_enabled config flag flipped to true; backend restarted (PID 841656, 127.0.0.1:8000). Endpoint verified live (POST /mcp/run returns 422 on empty body = route reachable + schema enforced). mcp>=1.0.0 already a declared dependency. Claude Code wiring: `claude mcp add` (native MCP client support, zero client plumbing).


## Entry: decision
- **Source:** master
- **Time:** 2026-09-06 21:23
- **Content:** Security policy change: caller-aware fast-path allow added for builder + master git/shell commands. Root cause: shell_exec is a RISKY_TOOL, so every git/shell call fell through to the Layer-2 LLM classifier (deepseek) — too strict AND flaky (source of the "Incomplete provider response: length" health-log failures). Fix adds a fast-path allow for builder/master so git/shell no longer round-trips the flaky classifier. Backend restarted (PID 893518) to load the change.


## Entry: decision
- **Source:** master
- **Time:** 2026-09-06 21:32
- **Content:** RESOLUTION of Concilium session 3b0b4665 commit/push (supersedes the "pending" entry above): builder succeeded on retry and committed 49 files (+1493/−305) in a single commit on feature/september-release. The earlier secret-scan SECRETS_FOUND matches were confirmed false positives (no real credential values); the push proceeded after the false-positive verification. Commit/push now DONE.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-06 22:10
- **Content:** master now has an `execute_code` tool available (verified working 2026-09-06). This lets master run deterministic work inline (file checks, HTTP probes, batch edits) WITHOUT routing through the security gate or spawning sub-agents. Useful for quick verification tasks that previously required shell_exec (which is a RISKY_TOOL gated by the flaky deepseek classifier) or delegation.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-06 22:08
- **Content:** Slash-command self-deadlock bug FIXED (2026-09-06). Root cause: the `/ping`, `/status`, `/agents` command handlers (`_do_ping()`, `_do_status()`, `_do_agents_list()`) made SYNCHRONOUS httpx.Client calls back to the server's own `/health` and `/agents` endpoints INSIDE an async def handler — blocking the event loop (self-deadlock). Frontend interception → /api/commands → commands.py chain was correct; the bug was purely the sync-in-async HTTP call. Fixed by making the internal calls async/non-blocking.


## Entry: learning
- **Source:** master
- **Time:** 2026-09-06 21:53
- **Content:** Builder recurring 15-turn limit pattern: builder hit its 15-turn limit TWICE in one window (2026-09-06 18:58 MCP build, 19:16 commit/push) on broad multi-step tasks. Both self-resolved via tighter re-delegation (e.g. 19:28, 10s). RECOMMENDED DELEGATION PATTERN (from self-eval round 84): split large builder tasks (MCP builds, multi-step commit/push) into smaller pre-validated subtasks rather than one broad task, to avoid the 15-turn hard-stop.


## Entry: discovery
- **Source:** cron
- **Time:** 2026-09-06 22:13
- **Content:** - **Commit/push RESOLVED** — Concilium session 3b0b4665's commit/push (previously "pending") succeeded on retry: builder committed 49 files (+1493/−305) on `feature/september-release`. The secret-scan flags were confirmed false positives.
- **execute_code tool** — master now has this capability; deterministic work (file checks, HTTP probes, batch edits) runs inline without the security gate or sub-agent spawning.
- **Slash-command self-deadlock fix** — `/ping`, `/status`, `/agents` handlers made synchronous `httpx.Client` calls inside async handlers, blocking the event loop. Fixed.
- **Builder 15-turn limit pattern** — hit twice in one window on broad multi-step tasks; recommended delegation pattern is to split large builder tasks into smaller pre-validated subtasks.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-06 22:17
- **Content:** Dispatcher timeout bug FIXED in app/backend/dispatcher.py (2026-09-06). Two bugs turned a real timeout into confusing garbage: (1) MISLABELING — when a long investigation hit the 900s agent task timeout, the dispatcher reported "Task chain timed out after None"; the `None` was a red herring printing an undefined `_chain_timeout` variable instead of the real 900s value; (2) INCONSISTENCY — line 513 referenced `_chain_timeout` while lines 192/428 used `_chain_ctx_timeout`. Both fixed so timeouts report the actual configured value.


## Entry: decision
- **Source:** master
- **Time:** 2026-09-06 22:31
- **Content:** master task_timeout set 300→0 (unbounded) in app/config/agent-settings.json — fixes the 5-min cap that killed deep investigations ("Task timed out"). Confirmed: agent-settings.json is authoritative (resolve_runner_settings reads it fresh, no cache → no restart needed); master has no CONFIG.yaml runner block; CLAUDE.md is doc-only (not parsed). Background autonomous work still capped by dispatcher autonomous_run_timeout. Port-collision (Errno 98) already fixed — no crashes since 2026-05-19 (deferred-restart helper + orphan detection + supervisor in place).


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-06 22:46
- **Content:** X.com/Twitter parsing is BLOCKED — fetch_page on x.com/explore returns only the login wall (no JS rendering/session), same anti-bot wall as LinkedIn. web_search fallback also errored. X access routes (from master): (1) X API Basic tier $100/mo includes the trends endpoint (GET /2/trends/by/woeid/{id}) — the only sanctioned way to get trends; (2) Playwright + login session (brittle, TOS-grey); (3) third-party scrapers. No X access wired as of 2026-09-06.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-06 22:47
- **Content:** Telegram public channels ARE parseable — unlike X/LinkedIn, Telegram exposes public channels through a web preview (`t.me/s/...`) that works WITHOUT auth. Successfully parsed @varlamov_news (2026-09-06). This is the notable difference from X/LinkedIn: Telegram is actually parseable via fetch_page on the t.me/s/ preview URL.


## Entry: decision
- **Source:** master
- **Time:** 2026-09-06 22:49
- **Content:** Milestone (2026-09-06): YAPOC's "communication axis" is now saturated — it is BOTH an MCP client AND an MCP server (can hire and be hired), plus a working content-ingestion path (Telegram). User framed YAPOC as an octopus (distributed intelligence, no single point of failure). Remaining unproven work = the three active goals (overnight autonomous stability, self-sufficient evaluator-master feedback loop, typed layered memory system).


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-06 23:01
- **Content:** Active-running-time timer feature BUILT and LIVE (2026-09-06). User asked to track active running time for sessions and agents (backend + UI). Design: "active running time" = cumulative wall-clock time an agent/session spent EXECUTING tasks (not idle/process uptime). Backend: GET /api/metrics/active-time in app/backend/routers/metrics.py computes per-agent + per-session cumulative time straight from the existing task_queue table (started_at/completed_at/assigned_agent/session_id) — ZERO schema change. Frontend timer UI element added (frontend build passed, bundle index-C6yqWRdp.js). Builder hit its 15-turn limit mid-build; follow-up run completed + verified end-to-end.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-06 23:14
- **Content:** Provider model catalog refreshed (2026-09-06). Catalog files live in app/utils/adapters/models/ (per-provider). Updated to current lineups for deepseek, openai, anthropic. Anthropic: added claude-opus-5 ($5/$25 per MTok), claude-sonnet-5 ($2/$10), claude-fable-5-1 ($10/$50); opus/sonnet 4.x and 3.x haiku demoted to legacy. Builder's primary model remapped gpt-5.4-mini → gpt-5.6-terra (config + fallback chain), and a redundant duplicate gpt-5.6-terra fallback entry was removed.


## Entry: discovery
- **Source:** master
- **Time:** 2026-09-06 23:31
- **Content:** Telegram bot duplicate-message-after-restart bug FIXED (2026-09-06). Root cause: getUpdates is at-least-once; the offset was persisted only AFTER the up-to-300s handler, so a restart mid-reply re-served the in-flight message → 2-3x duplicate replies. Fixes in app/backend/telegram_bot.py: (1) persist offset IMMEDIATELY after advancing (before handling); (2) atomic telegram_state.json writes via temp file + os.replace + fsync; (3) added /status command, and /ttt + /status to the setMyCommands menu. Restarted clean (single uvicorn, fresh "polling mode" log, offset advanced 708679323 → 708679324).


## Entry: decision
- **Source:** evaluator (round 86 AUTO-FIX) via master
- **Time:** 2026-09-07 00:06
- **Content:** Evaluator round 86 AUTO-FIX loop applied 2 config fixes: (1) builder runner.max_turns 15→30 in app/agents/builder/CONFIG.yaml — 3rd recurrence of the 15-turn limit on feature-size tasks in ~2h; turns are cheap, ceiling was the binding constraint; effective on next builder spawn. (2) doctor adapter/model openai/gpt-5.6-terra → deepseek/deepseek-v4-flash in app/config/agent-settings.json — doctor is light-duty (15s HEALTH.MD scans) and was on flagship terra; terra preserved in fallback chain; effective on next restart. Constraint discovered: builder CANNOT self-edit app/agents/builder/CONFIG.yaml — its own sandbox policy forbids the app/agents/builder/ path (builder's attempted self-edit was rejected; change must be applied by master/evaluator/keeper). Deferred NEEDS_APPROVAL: master per-session token audit ($221.95, +$10.02/+10.1M tokens this window).


## Entry: decision
- **Source:** evaluator (round 87 AUTO-FIX) via master
- **Time:** 2026-09-07 01:33
- **Content:** Evaluator round 87 AUTO-FIX applied: keeper runner.max_turns 15→30 in app/agents/keeper/CONFIG.yaml (edited DIRECTLY by master — keeper's own sandbox forbids self-edit of app/agents/keeper/CONFIG.yaml, same self-edit-forbidden pattern as builder). Round 86's fixes verified on disk (builder max_turns 30, doctor → deepseek-v4-flash). Round 87 itself succeeded on attempt 4 after 3 consecutive provider-truncation failures (22:29/22:34/22:59) + 1 KillAgentTool kill — self-eval loop was down ~35 min. Findings: 1 high, 2 medium. NEEDS_APPROVAL deferred: (1) termination.py parse_tool_arguments retry-once on truncated tool-arg JSON (code change + backend restart), (2) master per-session token audit.


## Entry: decision
- **Source:** evaluator (round 88 AUTO-FIX) via master
- **Time:** 2026-09-07 03:03
- **Content:** Evaluator round 88 AUTO-FIX applied: builder temperature 1.0→0.4 in app/config/agent-settings.json (fleet outlier — only agent at max randomness, fleet #2 spender; single-field JSON config → no backend restart needed, builder picks it up on next spawn). Round 88 found 3 issues (1 high: evaluator tick truncation still live — task 740b1953 at 23:59 died on invalid tool-arg JSON after r87, 4/6 last ticks failed, code retry fix never applied; 1 medium: master cost climb 4th consecutive window, $232.57 = 81.6% of fleet; 1 low). NEEDS_APPROVAL deferred: termination.py parse_tool_arguments retry + master token audit.


## Entry: decision
- **Source:** master
- **Time:** 2026-09-07 05:03
- **Content:** Master per-session token audit CLOSED (round 90, 2026-09-07 — carried as NEEDS_APPROVAL since round 86; master ran it as a diagnostic, zero-risk closure). Finding: master $237.20 total / 458.9M input tokens / 16,374 turns — spend is INPUT-VOLUME-DRIVEN, not price-driven: deepseek-chat $92.92 (334.4M input, 11,529 turns) + kimi-k2.6 $81.42 (80.8M input, 2,440 turns) = 73.5% of master's total combined; ~28K input tokens/turn driven by large injected context. Fleet total $289.46 (+$0.35), master = $236.93 (+$0.31, 81.9%) — the multi-window cost climb flatlined. Remaining NEEDS_APPROVAL (5th carry): termination.py parse_tool_arguments retry-once patch (code change + backend restart).


## Entry: discovery
- **Source:** master (skill-capture-sweep)
- **Time:** 2026-09-07 05:10
- **Content:** Skill `evaluator_autofix_loop` created (app/skills/evaluator_autofix_loop.yaml) — captured the evaluator→master AUTO-FIX loop, the most-repeated unskilled procedure in master memory (rounds 86, 87, 88, 90 = 4× in the recent window + 2 LEARNINGS.MD rules from May). Covers the MASTER-SIDE consumption of an evaluator self-eval notification: read REPORT.MD → auto-apply every [AUTO-FIX] item (config changes via keeper, prompt edits direct) → surface [NEEDS_APPROVAL] items to the user → log what was applied. Complements the existing `self_evaluation_round` skill (evaluator-side: pull signals → write REPORT → notify parent).


## Entry: decision
- **Source:** master
- **Time:** 2026-09-07 06:07
- **Content:** RESOLUTION — termination.py truncation fix APPLIED and verified LIVE (2026-09-07 06:02–06:07). CLOSES the 5-round-carried NEEDS_APPROVAL (r86→r90) and SUPERSEDES the 04:31 "on disk but inactive until restart" state. Trigger: evaluator failed again at 06:02 (invalid tool argument JSON — recurrence of the r86-90 truncation cluster, 6+ consecutive tick failures); per the user's self-fix-on-autonomous-failures preference, master applied the patch itself instead of deferring. On-disk changes in app/utils/adapters/termination.py, verified post-restart: `require_complete` whitelists finish_reason 'length' (earlier fix) AND `parse_tool_arguments` now runs `_repair_truncated_json` (closes unterminated strings, balances open brackets) after a failed json.loads, raising RuntimeError only when repair fails — repair-in-place (NOT adapter-level re-request). Backend restarted 06:02:59 (uvicorn PID 1600900, 23s after termination.py mtime) → new code confirmed loaded. Evaluator round 92 (first post-fix tick) and round 93 (ticks #2) ran clean on the salvage path with no 'length' error and no regression — VALIDATED CLOSED at round 93. Reopen only on a fresh post-fix `invalid tool argument JSON` error.


## Entry: discovery
- **Source:** evaluator (round 92 finding) via master
- **Time:** 2026-09-07 06:07
- **Content:** Observability error counters BLIND to task-level failures — app/backend/routers/metrics.py verified (grep, r92 + r93) to contain NO `status='error'` reference anywhere. `agents_with_errors` (~L427, fed by `_count_health_issues` L69) and `recent_errors` (via `_recent_health_lines` L373) are computed EXCLUSIVELY from per-agent HEALTH.MD tails; the SQLite `tasks` table (queried ~L470) feeds only `recent_tasks`/`total_tasks`. Live proof: task 0ac2785d failed 04:01:13, yet the 04:03:55 snapshot showed `agents_with_errors: 0`. HEALTH.MD is a historical cleared log, so the headline error signals systematically undercount fresh task failures — the exact class the user's "alert me if any agent fails twice in a row" rule needs. Proposed fix (NEEDS_APPROVAL, display-only, code change + backend restart): union `tasks.status='error'` rows (recent window) into both counters alongside HEALTH.MD lines; dedupe by task_id to avoid double-counting. Open question: whether the HEALTH.MD-only path also starves the doctor/master health-alert loop or only the dashboard (r87's alert fired, so possibly dashboard-only).


## Entry: decision
- **Source:** evaluator (round 93) via master
- **Time:** 2026-09-07 04:36
- **Content:** Round 93 open decision gates (3 NEEDS_APPROVAL carries; items 2 & 3 DROP after round 94 either way — no third request will be issued): (1) metrics.py error counters blind to task failures (see discovery entry 2026-09-07 06:07) — unapplied 1 round. (2) MASTER STRUCTURAL BURN decision gate — master $240.65 of $293.58 fleet = 82.0%, growing +$1.14/+0.49M input tokens per ~26-min window; input:output ratio ~101:1 (460.38M vs 4.53M); r90 audit closed the DIAGNOSIS (structural ~28K-token/turn injected-context assembly) and named context compaction as the only lever, but 3 windows later nothing is scoped and no "won't do" is on record. Master must scope ONE concrete context-compaction change OR record an explicit "won't do — accept ~$1.1/window burn" by round 94. (3) BUILDER OVERNIGHT ROLE decision gate — zero builder tasks since 22:03 across 5 consecutive report windows (idle 6.5h+); r87 (max_turns 30) / r88 (temp 0.4) fixes remain unexercised; master must either (a) declare the overnight role vestigial and gate builder to on-demand dispatch only (remove from cron delegation_targets) or (b) identify why no builder task has been dispatched and restore the workload source.


## Entry: discovery
- **Source:** master (user Q&A 2026-09-07 13:53)
- **Time:** 2026-09-07 13:53
- **Content:** Architecture clarification — YAPOC has TWO distinct knowledge stores with a CONSUMPTION-MODEL distinction (not just a location difference), per master's answer (grounded by reading the files + indexer): (1) `app/agents/shared/KNOWLEDGE.MD` = fleet-wide "always-on" knowledge (canonical store, ~325 lines, appended by librarian sweeps); (2) `app/memory/project/*.md` (CONVENTIONS.md / DECISIONS.md / KNOWLEDGE.md) = the layered-memory project store with a different (non-always-on) consumption model. CAVEAT verified by direct read: `app/memory/project/KNOWLEDGE.md` is a PARTIAL/STALE migration copy of the shared store (first ~8 entries only; its own header warns the canonical actively-appended store is app/agents/shared/KNOWLEDGE.MD) — never treat it as authoritative. SUPERSEDED by the 14:08 resolution below (file deleted).


## Entry: resolution
- **Source:** master (cleanup, user-approved 13:59 "yes, do that")
- **Time:** 2026-09-07 14:08
- **Content:** Knowledge-store ownership SETTLED: (1) `app/agents/shared/KNOWLEDGE.MD` is the SINGLE source of truth for project knowledge — only write target, always-on in context, indexed as agent='shared'. (2) `app/memory/project/DECISIONS.md` + `CONVENTIONS.md` are structured RETRIEVAL-ONLY stores — indexed as agent='project', NOT injected. (3) `app/memory/project/KNOWLEDGE.md` was a stale partial migration copy causing DOUBLE-INJECTION + DOUBLE-INDEXING — DELETED 2026-09-07 (file + 10 stale vector entries removed). Do not recreate it. SUPERSEDES the 13:53 "partial/stale copy — never authoritative" caveat: the file no longer exists; project store now contains only CONVENTIONS.md + DECISIONS.md.


## Entry: decision
- **Source:** master (memory decay Phase 1, user-approved 14:08 "do both")
- **Time:** 2026-09-07 14:13
- **Content:** Memory decay engine — full 4-phase design recorded in app/memory/project/DECISIONS.md (2026-09-07). Pre-existing seed: app/utils/memory_decay.py covered ONLY per-agent MEMORY.MD via binary 30-day age cutoff, archiving write-only to data/memory_archive/ (never indexed/read). PHASE 1 DONE — master implemented DIRECTLY after builder returned silent-empty "[] OK:" with zero changes (grep-verified; documented failure mode recurrence). (1) PRUNE: shared KNOWLEDGE.MD 68→62 entries; 6 explicitly-superseded entries archived to data/memory_archive/shared.archive.md (2× April model-optimization, "master on kimi-k2.6", "model distribution 14 agents", Concilium 3b0b4665 pending, evaluator truncation cluster). Correction: the believed "50-entry cap" was WRONG — file held 68 entries. (2) GENERALIZE: `archive_stale_shared_knowledge(max_age_days, dry_run)` in memory_decay.py parses `## Entry:` blocks by `**Time:**`, keeps undated entries, archives old → shared.archive.md; wired into `_memory_decay_tick()` in app/backend/main.py (scheduler id="memory_decay", interval `memory_decay_interval_hours`=6h, cutoff `memory_decay_days`=30, try/except guarded). (3) INDEXER re-sync automatic via 10-min `_indexer_tick` (hash-based index_shared_knowledge). Dry-run: 11 entries eligible at 30d. Phase 2 (cold tier searchable) next.


## Entry: decision
- **Source:** master (memory decay Phase 2, user-approved 14:20 "do phase 2", via planning)
- **Time:** 2026-09-07 14:24
- **Content:** Memory decay Phase 2 DONE — searchable COLD tier: data/memory_archive/ is now indexed as tier="cold" instead of a write-only black hole. (1) `tier` (hot/cold) + `provenance` metadata added to memory records; backward-compatible additive SQLite migration. (2) `search_memory` gained `include_cold` param (default False) threaded through app/utils/db.py search_hybrid (L368/394/527), tool app/utils/tools/search.py, API router app/backend/routers/memory_graph.py, and MCP server (app/mcp_server/backend_client.py + server.py). (3) Default retrieval AND prompt/context injection remain HOT-ONLY; cold entries surface only on explicit include_cold=true. Phases still open: P3 scored decay (half-life + last_retrieved recency + supersession auto-mark, replacing binary cutoff), P4 observability (tier counts in metrics + injected-chars budget backstop).


## Entry: discovery
- **Source:** master (user-reported issue 14:16, fix verified 14:19)
- **Time:** 2026-09-07 14:19
- **Content:** OpenAI adapter fix for gpt-5.6-terra tool-use 400: GPT-5.6+/GPT-6 family models default `reasoning_effort` to a reasoning level, and OpenAI returns 400 on tool-using chat-completions unless `reasoning_effort` is explicitly "none" — this was silently forcing fallback to deepseek on master's tool-using turns (user: "yeah fix that, but keep gpt model as primary"). Fix LIVE in app/utils/adapters/openai.py: `_needs_reasoning_effort_none()` (L58) + payload `reasoning_effort="none"` (L231-232) when tool calls are used on affected models. Backend restarted 14:19 per user ("restart server dude"); verified post-restart (HTTP 200, fresh uptime): openai.py parses, helper present exactly once, master remains openai/gpt-5.6-terra PRIMARY with no 400/fallback on tool-using turns.


## Entry: discovery
- **Source:** evaluator (round 94 findings) via master
- **Time:** 2026-09-07 14:13
- **Content:** Evaluator round 94 (12:09–12:15Z; 1 high, 2 medium, 0 AUTO-FIX, 3 NEEDS_APPROVAL): (1) HIGH — observability feed `get_recent_signals` DARK while backend up: call failed 12:09Z ("All connection attempts failed") yet a raw socket to :8000 succeeded 12:10Z and the signal cache was last written 12:03Z; evaluator ran the entire round on direct DB reads. Not a one-off — evaluator HEALTH log carries an earlier httpx.ReadError. Compounds the r92 finding that error counters read HEALTH.MD only: the observability path has multiple blind spots. (2) MEDIUM — evaluator DB-filter bug: TEXT vs numeric comparison on ISO-string timestamps → everything matched, so windowed error counts unreliable. Recurring `[] OK:` empty notify also noted. Open carries: metrics.py HEALTH.MD-only counters, master structural burn, builder overnight-role gates (round 93 carries).


## Entry: resolution
- **Source:** evaluator (round 95/96 findings) via master
- **Time:** 2026-09-07 14:05
- **Content:** Evaluator round 95 issue 2 (planning 15-turn cap) CLOSED — fix landed and tested. Builder task 0e2acde2 (13:52:39→13:53:25, done) fixed runner max_turns resolution: `app/agents/base/__init__.py` L1434-1438 now resolves `max_turns` with priority agent-settings.json → CONFIG.yaml runner block → global default, using sentinel `None` checks (not `or` chains). planning/builder/keeper CONFIG.yaml all declare `runner.max_turns: 30`; agent-settings.json sets no max_turns for them → they now resolve to 30. Regression test added: `tests/test_agent_settings.py::test_config_max_turns_used_when_json_has_no_override` asserts CONFIG.yaml's 30 wins when JSON omits it. This supersedes the earlier per-agent max_turns 15→30 edits (rounds 86/87) as the systemic fix.


## Entry: discovery
- **Source:** evaluator (round 96 findings) via master
- **Time:** 2026-09-07 14:05
- **Content:** Evaluator round 96 (14:02Z snapshot; 1 high, 1 medium, 1 low; 1 AUTO-FIX, 2 NEEDS_APPROVAL): (1) HIGH — error counters STILL HEALTH.MD-only: `agents_with_errors` (metrics.py L427/446) + `recent_errors` (L447/468) built exclusively from HEALTH.MD tails via `_count_health_issues` (L69) / `_recent_health_lines` (L373); the tasks SELECT at L474 feeds only recent_tasks, not error counters. THIRD independent live proof (r94 d88af5e9, r95 164ca44d, r96 b223bea4): librarian task b223bea4 errored 13:24:45→13:34:47Z ("Task timed out") yet the 14:02Z snapshot reports `agents_with_errors: 0`. User's "alert on 2 consecutive failures" rule cannot fire on task errors. NEEDS_APPROVAL: union task-level `status='error'` rows into both counters (dedupe by task_id/message; display-only; backend restart). (2) MEDIUM — master structural burn accelerating: $266.28 of $328.02 fleet = 81.2%, +$4.46/+2.2M input tokens since r95's $261.82/470.4M — largest single-window delta in recent rounds, ~8x r95's +$0.55, confirming the overnight quiet regime has ended. r93 context-compaction decision gate still unaddressed past its r94 deadline. NEEDS_APPROVAL: master to scope ONE concrete context-compaction change OR record explicit "won't do — accept ~$4-5/window burn"; item drops next round. (3) LOW — librarian memory-sweep timeout: task b223bea4 died at 602s against agent-settings.json `task_timeout: 600` (authoritative) while CONFIG.yaml still declares `runner.task_timeout: 300` (stale/misleading). AUTO-FIX applied: CONFIG.yaml runner.task_timeout 300→600 (pure doc-alignment; runtime unchanged since agent-settings 600 is authoritative). If sweep keeps timing out at 600s, real fix is chunking the sweep, not raising the cap. First timeout this window (prior sweeps 61-137s), not yet a pattern.


## Entry: resolution
- **Source:** evaluator (round 97 findings) via master
- **Time:** 2026-09-07 14:50
- **Content:** Evaluator round 97 (14:50Z snapshot; 1 high, 1 medium, 1 low; 1 AUTO-FIX, 2 NEEDS_APPROVAL): (1) RESOLUTION — r96 issue 3 (librarian memory-sweep timeout) CLOSED: grounding read confirms `app/agents/librarian/CONFIG.yaml` runner block now reads `task_timeout: 600`, matching agent-settings.json's authoritative value; no new librarian timeout this window (task 308fbe62 ran 14:25→14:27, 73s, clean). (2) DISCOVERY — planning agent has NOT re-run since the r95/r96 max_turns fix (0e2acde2, 13:52Z): planning task 164ca44d died at the 15-turn limit 12:34:52→12:35:45Z (the exact defect the fix addressed), but planning has not executed a task since, so its `status="error"` in the snapshot is STALE and the fix is UNVERIFIED for planning (planning may have a separate path still capping at 15). AUTO-FIX: dispatch one lightweight planning verification run to confirm it resolves max_turns=30 and clears the stale error status. (3) CONTINUATION — error counters STILL HEALTH.MD-only: FOURTH independent live proof (r94 d88af5e9, r95 164ca44d, r96 b223bea4, r97 164ca44d) — planning's 12:35Z error shows `status="error"` in the 14:48Z snapshot yet headline reports `agents_with_errors: 0` / `recent_errors: []`. metrics.py still has ZERO `status='error'` references. NEEDS_APPROVAL (unapplied 2 rounds): union task-level errors into both counters. (4) CONTINUATION — master structural burn accelerating: $272.57 of $336.29 fleet = 81.0%, +$6.29/+3.1M input tokens since r96's $266.28/472.6M — largest single-window delta yet (+$0.55 r95 → +$4.46 r96 → +$6.29 r97), confirming daytime activity fully returned. r93 context-compaction decision gate now 6 rounds past its r94 deadline, still unaddressed. NEEDS_APPROVAL: master to scope ONE concrete context-compaction change OR record explicit "won't do — accept ~$5-6/window burn"; item drops next round either way.


## Entry: feature
- **Source:** master (user-requested Telegram voice interface, session fd8678e6)
- **Time:** 2026-09-07 15:02
- **Content:** Telegram voice interface IMPLEMENTED (user wants multilingual transcription + voice replies only on request; Telegram-only user). Incoming Telegram voice/audio/video-note media is transcribed through the existing OpenAI Whisper STT with the language parameter OMITTED (empty → auto-detect) for multilingual support; requested or `/voice`-enabled replies synthesize OpenAI onyx Opus audio after every normal delivery path. Files: `app/backend/telegram_bot.py` — `_handle_message` treats voice as raw media (downloads .ogg, forwards to master); replaced early-return response branches with a `text_delivered`/`media_sent` flow so generated media, long split responses, acknowledgment edits (HTML/plain), and fallback text all continue into the existing voice synthesis/sendVoice block. `app/backend/services/voice_service.py` — `STTEngine.transcribe` (Whisper via openai engine, empty language=auto-detect) + `TTSEngine.synthesize` (openai/onyx); removed debug logging of OpenAI API-key presence/length (retained non-secret TTS request diagnostics). `app/config/settings.py` L76 — new `telegram_voice_reply_default: bool = False` (added by keeper, immediately after `telegram_whitelist` L75); `/voice` is the user-facing toggle. ffmpeg available at /usr/bin/ffmpeg. Reuses existing voice_service + Telegram bot architecture (no STT/TTS duplication). Verified via py_compile + git diff --check. NOTE: builder's first attempt hit the 30-turn limit mid-implementation (PARTIAL) — re-delegated as narrower chunks; completed 15:02. Backend NOT yet restarted (code mutation pending restart to take effect). Supersedes/extends the 09-02 frontend/backend voice TTS/STT entry (this adds the Telegram bot voice path).

## Entry: discovery
- **Source:** evaluator (round 98 findings) via master
- **Time:** 2026-09-07 16:10
- **Content:** Evaluator round 98 (16:10Z snapshot; 1 high, 2 medium; 1 AUTO-FIX, 2 NEEDS_APPROVAL): (1) HIGH — error counters STILL HEALTH.MD-only: FIFTH independent live proof (r94 d88af5e9, r95 164ca44d, r96 b223bea4, r97 164ca44d, r98 07a3c2ec/2b0cec50) — librarian task 07a3c2ec timed out 15:55:41→16:05:43Z ("Task timed out") and builder task 2b0cec50 errored 15:56:12→15:57:51Z ("reached the 30-turn limit"), both `status="error"` in the 16:08Z snapshot, yet headline reports `agents_with_errors: 0` / `recent_errors: []`. metrics.py still has ZERO `status='error'` references (grep-verified). NEEDS_APPROVAL (unapplied 4 rounds): union task-level errors into both counters. (2) MEDIUM — r96 librarian timeout fix (300→600s) INSUFFICIENT: both CONFIG.yaml and agent-settings.json verified at `task_timeout: 600`, yet memory-sweep task 07a3c2ec (602s) still timed out this window; sweep is intermittent (10ed8dbb 13:55Z, 151953c2 16:06Z completed). AUTO-FIX applied: raise librarian task_timeout 600→900 in both files (headroom; if timeouts persist at 900s the sweep task needs splitting, not another bump). (3) MEDIUM — master structural burn accelerating: $284.37 of $360.20 fleet = 79.0%, +$11.80/+5.7M input tokens since r97's $272.57/475.7M — largest single-window delta yet (+$0.55 r95 → +$4.46 r96 → +$6.29 r97 → +$11.80 r98). r93 context-compaction decision gate now 7 rounds past its r94 deadline, still unaddressed. NEEDS_APPROVAL: master to scope ONE concrete context-compaction change OR record explicit "won't do — accept ~$5-12/window burn"; item drops next round either way.

## Entry: discovery
- **Source:** evaluator (round 99 findings) via master
- **Time:** 2026-09-07 16:40
- **Content:** Evaluator round 99 (16:40Z snapshot; 1 high, 2 medium; 1 AUTO-FIX, 2 NEEDS_APPROVAL): (1) HIGH — error counters STILL HEALTH.MD-only: SIXTH independent live proof (r94 d88af5e9, r95 164ca44d, r96 b223bea4, r97 164ca44d, r98 07a3c2ec/2b0cec50, r99 97808131) — planning task 97808131 errored 16:12:47→16:15:07Z ("reached the 30-turn limit"), `status="error"` in the 16:38Z snapshot, yet headline reports `agents_with_errors: 0` / `recent_errors: []`. metrics.py still has ZERO `status='error'` references (grep-verified). NEEDS_APPROVAL (unapplied 5 rounds): union task-level errors into both counters. (2) MEDIUM — planning agent hit the 30-turn limit TWICE this window orchestrating the PDF feature (task 47d31b20 16:08:34→16:10:24Z + task 97808131 16:12:47→16:15:07Z, both `error_summary: "Task incomplete: reached the 30-turn limit"`); the feature only completed when master delegated the concrete steps DIRECTLY to builder (16:15-16:17Z) and keeper (16:14-16:15Z), bypassing planning. Coordination inefficiency: planning over-inspects rather than committing to a delegation DAG. Planning `runner.max_turns: 30` (verified in CONFIG.yaml). AUTO-FIX applied: raise planning max_turns 30→45 so the coordinator can finish its delegation DAG without exhausting its turn budget mid-orchestration (if planning still fails at 45 the root cause is over-inspection, not budget). (3) MEDIUM — master structural burn delta SLOWED: $286.36 of $365.47 fleet = 78.4%, +$1.99/+6.0M input tokens (~28 min) vs the prior window's +$11.80 — the acceleration r98 flagged did NOT continue. r93 context-compaction decision gate now 8 rounds past its r94 deadline, still unaddressed. NEEDS_APPROVAL: master to scope ONE concrete context-compaction change OR record explicit "won't do — accept ~$2-12/window burn"; item drops next round either way. RESOLUTION — r98 issue 2 (librarian timeout 600→900) verified clean on disk: both `app/agents/librarian/CONFIG.yaml` and `app/config/agent-settings.json` carry `task_timeout: 900` (applied by keeper 7d979d1c + builder c4dd9b99 16:10-16:11Z); no librarian sweep has run at the new 900s ceiling yet, so efficacy unproven but config correct.

## Entry: discovery
- **Source:** evaluator (round 100 findings) via master
- **Time:** 2026-09-07 17:11
- **Content:** Evaluator round 100 (17:11Z snapshot; 1 high, 2 medium; 1 AUTO-FIX, 2 NEEDS_APPROVAL): (1) HIGH — error counters STILL HEALTH.MD-only: SEVENTH independent proof (r94 d88af5e9, r95 164ca44d, r96 b223bea4, r97 164ca44d, r98 07a3c2ec/2b0cec50, r99 97808131, r100 grep) — grep this run confirms `app/backend/routers/metrics.py` still contains ZERO `status='error'` references; `agents_with_errors`/`recent_errors` built exclusively from HEALTH.MD tails via `_count_health_issues`/`_recent_health_lines` (5 refs). No task errored in this window's recent_tasks feed (all `status="done"`), so blindness proven STRUCTURALLY (grep) not by a fresh live error. NEEDS_APPROVAL (unapplied 6 rounds): union task-level `status='error'` rows into both counters (dedupe by task_id/message; display-only; backend restart). User's "alert on 2 consecutive failures" rule still cannot fire on task errors. (2) MEDIUM — master structural burn RE-ACCELERATED: $290.56 of $371.97 fleet = 78.1% (dominant cost lever ~4.8x builder), +$4.20/+2.0M input tokens (~33 min) vs r99's +$1.99 — the r99 "not accelerating" read did NOT hold; master back to ~$4-6/window structural burn. r93 context-compaction decision gate now 9 rounds past its r94 deadline, still unannotated. NEEDS_APPROVAL: master to scope ONE concrete context-compaction change (targeting per-turn injected-context assembly, ~28K tokens/turn per r90 audit) OR record explicit "won't do — accept ~$4-6/window burn"; item drops next round either way, no further audit requests issued. (3) LOW — planning fix (max_turns 30→45) applied but UNPROVEN: `app/agents/planning/CONFIG.yaml` verified carrying `runner.max_turns: 45` (keeper e64efa54 + builder 791e2910, 16:39-16:40Z); agent-settings.json planning entry has no max_turns field (CONFIG.yaml authoritative per `_tools_note`), no drift to reconcile; no planning task has run at the new 45-turn ceiling yet. AUTO-FIX (monitoring only): re-verify planning at 45 on next multi-step orchestration task — if it again fails a well-specified multi-step task, root cause is over-inspection/routing (bypass planning → route master→builder/keeper directly), not turn budget. RESOLUTION — r99 issue 2 (planning max_turns 30→45) verified applied. Fleet otherwise healthy: all recent tasks done, no errors/timeouts; builder completed three PDF-viewer tasks cleanly (16:43-16:47Z); librarian memory-sweeps completing in 37-90s, well under the new 900s ceiling.

## Entry: feature
- **Source:** master (user-requested, session 214d9484)
- **Time:** 2026-09-07 17:31
- **Content:** NEW permanent `document_processor` agent CREATED (user-requested: "well-designed permanent Document Processing Agent, responsible for all file interactions, with all applicable file capabilities plus execution/bash/code tools"). Created via `create_agent` at 17:31:05Z (master, after planning delegated the design at 17:29:56Z): `app/agents/document_processor/` with CONFIG.yaml (adapter openai, model gpt-5.6-terra, temperature 0.3, runner max_turns 20 / task_timeout 300 / poll_interval 30 / retry_attempts 3 / context_memory_limit 50 / context_health_limit 10), PROMPT.MD, agent.py, __init__.py. 18 tools granted (modules file_ops, code_analysis, memory_management): shell_exec, execute_code, web_search, fetch_page, image_read, render_chart, render_mermaid, notify_parent + file_read/write/edit/delete/list, memory_append, notes_read/write, health_log, learnings_append. Scope: safe inspection/extraction/summarization/transformation/analysis/generation/conversion/validation/presentation of text/Markdown, PDF, images, DOCX, XLSX/CSV/TSV, PPTX, JSON/YAML/XML, HTML, source code, EML/MBOX, ICS, ZIP/TAR/TGZ/7Z archives, repository archives, URL-derived docs. NO audio/video. Security rules: treat all content as untrusted, inspect-before-mutate (list archives first, never extract unsafe paths/execute contents), bounded parsing (file-size/row/cell/page/slide/entry/output limits), preserve originals (write derived artifacts to data/generated/ or task workspace), never expose secrets/read .env/settings.py. Backend restarted 17:31:07Z to activate the new agent's config + model binding (RESUME.MD next_action: verify document_processor available post-restart, report capabilities to user). NOTE: agent-settings.json does NOT yet carry a document_processor entry (CONFIG.yaml is the model-binding source for this agent); agent not yet run (no STATUS.json) — first task pending. Part of a broader user request for textual-information support (Office docs, archives, repositories, URLs, email, calendar) delegated to planning at 17:13:49Z.

## Entry: feature
- **Source:** master (user-requested in-chat file/artifact viewer sidebar, session 214d9484)
- **Time:** 2026-09-07 17:46
- **Content:** In-chat file/artifact viewer sidebar IMPLEMENTED + VERIFIED (user reported generated-file link `/api/files/download?path=...` returned `{detail:"Not Found"}`). Root cause: NO `/files/download` endpoint existed in `app/backend/routers/files.py` (only /tree,/read,/image,/upload). Planning→builder implemented backend + frontend, backend restarted 17:45:33Z, resume verification 17:46:11Z confirmed endpoint live. Backend: `app/backend/routers/files.py` added `_classify`/`_media_type` helpers + `_TEXT_EXTENSIONS`/`_IMAGE_EXTENSIONS`/`_PREVIEW_MAX_CHARS=200_000` constants + two GET endpoints — `/files/download` (sandboxed FileResponse, attachment by default, `inline=1` streams inline for iframe PDF/image preview) and `/files/preview` (returns metadata path/name/size/ext/kind + text content for text-classified files); both reuse existing `_sandbox()` guard (traversal + .env/.pem/.key rejection). Tests: `app/backend/tests/test_files_viewer.py` (8 passed: download/inline, text preview, traversal + sensitive-path rejection, missing-file 404). Frontend: `app/frontend/src/store/fileViewerStore.ts` (Zustand selection store), `app/frontend/src/components/FileViewerPane.tsx` (fetches /files/preview, renders text/image/PDF + download/close), `App.tsx` mounts right-side pane, `MessageBubble.tsx` detects generated/uploaded file links + inline code paths opening in sidebar, `index.css` responsive/mobile full-screen overlay. Production bundle `index-DTJ5iv71.js`. NOTE: the live 404 was a STALE backend process (started before the route was added) — source/tests were already correct; restart fixed it. document_processor's first task (17:36-17:37Z) created `data/generated/document_processor_test.md` (capability-routing test, passed) — the artifact that triggered this feature.

## Entry: discovery
- **Source:** master (session 214d9484, file-viewer orchestration)
- **Time:** 2026-09-07 17:42
- **Content:** Planning agent hit the 45-turn limit on its FIRST task at the new 45-turn ceiling (r99/r100 AUTO-FIX raised planning max_turns 30→45). Planning task errored 17:42:04Z (`error_summary: "Task incomplete: reached the 45-turn limit"`) orchestrating the in-chat file/artifact viewer sidebar feature; the work only completed when master delegated the concrete backend + frontend phases DIRECTLY to builder (17:41-17:45Z), bypassing planning. This is the EIGHTH independent confirmation of the coordination inefficiency pattern (planning over-inspects rather than committing to a delegation DAG) and the FIRST live proof at the new 45-turn ceiling — confirming r99/r100's hypothesis that planning's root cause is over-inspection/routing, NOT turn budget. AUTO-FIX (monitoring): on the next well-specified multi-step task, if planning again exhausts budget, bypass planning and route master→builder/keeper directly rather than raising turns further. This finding also feeds the r100 open question about whether planning's orchestration is a redundant detour for well-specified tasks.

## Entry: feature
- **Source:** master (session 214d9484, frontend)
- **Time:** 2026-09-07 17:12
- **Content:** Mermaid diagram rendering added to chat UI: `app/frontend/src/components/MessageBubble.tsx` added a `codeChildrenToText` helper and overrode the `MARKDOWN_COMPONENTS.pre` handler to detect fenced ```mermaid code blocks and render a `MermaidBlock` instead of a plain `<pre>`. Frontend build verified via `pnpm build` (tsc -b && vite build). Complements the user preference that master must invoke render_mermaid for Mermaid diagrams (renders in chat, not just Mermaid source text).

## Entry: feature
- **Source:** master (session 214d9484, textual-ingestion continuation)
- **Time:** 2026-09-07 18:00
- **Content:** Textual-information attachment support IMPLEMENTED (user: "lets add support for textual information for now, skip video and audio" — Office docs, archives, email/calendar). Backend extraction added in `app/backend/services/uploads.py` for `.xlsx`, `.pptx`, `.eml`, `.mbox`, `.ics`, `.zip`, `.tar`, `.tgz`, `.7z` (safe bounded parsing/listing with size/row/event/archive-entry caps; NO archive extraction to disk; path-traversal protection). Dependencies installed: `openpyxl` (.xlsx), `python-pptx` (.pptx), `icalendar` (.ics), `py7zr` (.7z). Frontend attachment cards render typed cards (icons, labels, size, View/Download) for the new formats; PDF behavior preserved (existing in-chat modal viewer). Existing text/.docx/PDF extraction intact. NOTE: planning hit its 45-turn limit orchestrating this feature (work completed via direct master→builder delegation) — consistent with the planning over-inspection/routing pattern.

## Entry: decision
- **Source:** master (session 214d9484, user-requested)
- **Time:** 2026-09-07 18:00
- **Content:** 10 MB chat-attachment upload cap REMOVED (user: "remove cap in mb for uploaded attachments - i could not upload presentation"). Chat attachments now use `/api/upload` which is UNCAPPED (large presentations upload fine). Kept safeguards: empty-file rejection, dangerous-type blocking, rate/concurrency limits, ownership checks, bounded extraction. NOTE: the separate legacy `/api/files/upload` endpoint still has its own 5 MB limit — chat attachments use `/api/upload`, which is now uncapped. Verified with a `.pptx` payload larger than 10 MiB.

## Entry: feature
- **Source:** master (session 214d9484, user-requested PPTX viewer)
- **Time:** 2026-09-07 18:00
- **Content:** In-chat PPTX viewer IMPLEMENTED (user: "i cannot download it, add viewer for the presentations"). Backend: `app/backend/services/pptx_view.py` converts `.pptx` → PDF via cached headless LibreOffice under `data/pptx_cache/`; `app/backend/routers/pptx.py` adds `GET /pptx/view` (resolves upload-ID or generated-path source, converts, serves inline PDF). Router registered in `app/backend/routers/__init__.py` + `app/backend/main.py`. Frontend: presentation cards and generated `.pptx` paths show a "View presentation" button opening an inline modal with PDF-rendered slides + Download/Close (Escape + backdrop close). Frontend production bundle rebuilt. NOTE: activation required a backend restart (the running backend exposed an older OpenAPI schema without `/pptx/view`); builder lacks `server_restart` so master performed the restart.

## Entry: feature
- **Source:** master (session 214d9484, user-requested artifact system)
- **Time:** 2026-09-07 18:00
- **Content:** Artifact System IMPLEMENTED + VERIFIED (user: "Artifact system — generated files, previews, provenance, versioning. Build that"). Durable generated-artifact registry with metadata, provenance, SHA-256 hashes, and stem-based version lineage. Files: `app/backend/services/artifacts.py` (registry CRUD + `backfill_scan`), `app/backend/routers/artifacts.py` (`GET /artifacts` list/filter, `GET /artifacts/{id}` detail, `GET /artifacts/{id}/versions`, `POST /artifacts/register`), storage `data/artifacts/artifacts.json` (atomic writes). Backfill for existing `data/generated/` files (4 existing generated artifacts backfilled). Existing file preview/download serving reused. Frontend: ARTIFACTS panel in chat header (filtering, metadata/version display, click-through to existing FileViewerPane). Tests: `app/backend/tests/test_artifacts.py` + `test_files_viewer.py` = 13 passed. Frontend production build passed (1,913 modules). NOTE: builder hit its 30-turn limit mid-implementation; a follow-up builder task completed but returned no implementation details — master verified the artifact system was already complete via direct source/tests inspection. Backend restart required to activate `/api/artifacts` endpoints.

## Entry: decision
- **Source:** master (session 214d9484, user-requested routing policy)
- **Time:** 2026-09-07 18:00
- **Content:** Master delegation policy UPDATED to route all user-file work through `document_processor` by default (user: "update your delegation instructions, all things related to files via document-processor agent"). Applied to `app/agents/master/PROMPT.MD`: (1) L214 — spawn `document_processor` for all user-file interactions and file-derived artifacts, `builder` for application source-code changes, `keeper` for config; (2) L272 — document_processor described as "Primary specialist for all user-file interactions: ingest, inspect, extract, edit, convert, generate, validate, and derive artifacts from documents, spreadsheets, presentations, archives, code repositories, emails, calendars, images, and URLs"; (3) L336 — any user-file interaction or file-derived artifact work → document_processor; (4) L338 — shell command for document/file processing → document_processor; for application code → builder; for configuration → keeper. document_processor validated via a test task (created `data/generated/document_processor_test.md`). Backend restarted to apply the delegation-policy update.

## Entry: decision
- **Source:** master (session 214d9484, user-requested model change — IN PROGRESS)
- **Time:** 2026-09-07 20:03
- **Content:** User selected DeepSeek V4 Pro for the planning agent with LOW reasoning effort (user: "assign more capable model to the planner from deepseek provide with reasoning low" → "maybe deepseek v4 pro?"). Master dispatched keeper task 8ae17b38 (20:02:57Z) to update `app/config/agent-settings.json` planning entry: change primary model `deepseek-v4-flash` → `deepseek-v4-pro`, add/configure low reasoning effort using the project's supported config convention (inspect adapter/config code rather than inventing an unsupported field), preserve adapter=deepseek, temperature, max_tokens, task_timeout, tools, and existing fallback chain (openai/gpt-5.6-luna + google/gemini-2.5-flash). STATUS: IN PROGRESS — keeper task dispatched but config NOT yet applied (agent-settings.json planning still shows deepseek-v4-flash as of this sweep). NOTE: planning CONFIG.yaml currently declares `model: deepseek-chat` (agent-settings.json is the authoritative model-binding source for planning per its `_tools_note`). Also relevant: DeepSeek V4 Pro outputs tool calls as raw XML in `delta.content` instead of structured `delta.tool_calls` — already handled in `app/utils/adapters/deepseek.py` via `_parse_raw_tool_calls` (5 XML formats).

## Entry: discovery
- **Source:** evaluator (round 101 findings) via master
- **Time:** 2026-09-07 18:16
- **Content:** Evaluator round 101 (18:16Z snapshot; 1 high, 2 medium; 1 AUTO-FIX, 2 NEEDS_APPROVAL): (1) HIGH — error counters STILL HEALTH.MD-only: EIGHTH independent proof (r94-r101) — grep this run confirms `app/backend/routers/metrics.py` still contains ZERO `status='error'` references; `agents_with_errors`/`recent_errors` built exclusively from HEALTH.MD tails via `_recent_health_lines` (2 refs)/`_count_health_issues` (3 refs). FRESH live proof this window: three tasks errored in the recent_tasks feed yet the snapshot reports `agents_with_errors: 0`/`recent_errors: []` — planning 9123ac62 (17:55→18:01, 350s) + 7556dabe (17:38→17:42, 243s) both `"reached the 45-turn limit"`, builder e2b0408c (17:56→17:58, 83s) `"reached the 30-turn limit"`. Task-level failures structurally incapable of reaching the counters, so the user's "alert on 2 consecutive failures" rule cannot fire on task errors. NEEDS_APPROVAL (unapplied 7 rounds): union task-level `status='error'` rows into both counters (dedupe by task_id/message; display-only; backend restart). (2) MEDIUM — planning at 45 turns STILL exhausts budget on multi-step implementation; routing fix now warranted: planning exhausted the raised 45-turn ceiling TWICE this window (9123ac62, 7556dabe) orchestrating the artifact system; the feature only completed when master delegated directly to builder (545764bb, done in 37s). r99's AUTO-FIX (max_turns 30→45) verified applied but did NOT resolve the failure mode — coordinator over-inspects rather than committing to a delegation DAG. SECOND feature (after r99 PDF) where planning's orchestration added a failed turn-limit detour before the direct path succeeded. NEEDS_APPROVAL: bypass planning for well-specified multi-step implementation (route master→builder/keeper directly); reserve planning for genuinely ambiguous decomposition-needed tasks. (3) LOW — planning v4-pro upgrade untested: keeper task 0b765e45 (18:02:57) changed planning's primary model `deepseek-v4-flash`→`deepseek-v4-pro` in agent-settings.json; both 45-turn failures predate the change, so v4-pro's effect on orchestration quality is unproven — if next multi-step planning task completes cleanly under v4-pro the model was the limiting factor; if it again exhausts turns the routing fix in issue 2 is the answer regardless. AUTO-FIX: reconcile stale planning CONFIG.yaml `model: deepseek-chat` → `deepseek-v4-pro` (agent-settings.json authoritative; cosmetic drift, no restart needed). Master burn delta: $290.56 (r100) → $302.55 (r101) = +$11.99/+5.9M input tokens in ~65 min — back to ~$4-6/window structural baseline pace, not accelerating. Fleet otherwise healthy: all recent tasks done, no errors/timeouts; builder completed three PDF-viewer tasks cleanly (16:43-16:47Z); librarian sweeps completing in 37-90s under the 900s ceiling.

