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
- **Source:** model_manager
- **Time:** 2026-04-13 20:52
- **Content:** Model optimization implementation completed 2026-04-13: cron downgraded to claude-3-haiku-20240307 (75% cost reduction), keeper & doctor migrated from lmstudio to cloud Haiku, master updated to sonnet-4-6 for catalog compliance. Total estimated savings: 72% (~$0.22/session). All changes reversible.

## Entry: decision
- **Source:** model_manager
- **Time:** 2026-04-13 20:57
- **Content:** Model optimization implementation completed 2026-04-13 21:45: master (sonnet-4-5→4-6, catalog compliance), cron (haiku-4-5→3-haiku, 75% cost reduction), keeper & doctor (haiku-4-5→3-haiku, cost reduction). Total estimated savings: 72% (~$0.22/session, $287.52/year). All changes in app/config/agent-settings.json, fully reversible.

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

## Entry: decision
- **Source:** master
- **Time:** 2026-05-25 11:42
- **Content:** Master agent model changed from deepseek/deepseek-chat to moonshot/kimi-k2.6 in agent-settings.json. Master task_timeout set to 900s (user-approved 2026-05-23). Master CONFIG.yaml still shows deepseek-chat with task_timeout: 0 (unbounded) but agent-settings.json is authoritative at runtime. This is a significant model upgrade from the earlier sonnet-4-6/deepseek-chat era.

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
- **Time:** 2026-09-05 15:15
- **Content:** Current model distribution across 14 agents (from app/config/agent-settings.json): deepseek-chat used by 10 agents (planning, builder, keeper, concilium, librarian, evaluator, security, researcher, tester, mcp); master uses DeepSeek-V4-Pro-0813. (One additional agent on a distinct model; total 14.)

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
