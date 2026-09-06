# User Interaction History
[2026-05-23] Requested self-evaluation audit for long-session stability
[2026-05-23] Approved fixing evaluator stale-data problem (metrics.py + evaluator prompt)
[2026-05-23] Approved bumping master timeout to 900s
[2026-05-23] Requested evaluator-master autonomous loop (no user in loop)
[2026-05-23] Approved moonshot timeout reduction to 60s
[2026-05-23] Requested full memory refactor (Option 2)
[2026-05-24] Memory refactor implemented: app/memory/{user,project,agents}/ structure live, context.py reads user profile + project knowledge into all agents
[2026-05-24] Added user identity: name=kuweg, YAPOC=Yet Another Python OpenClaw
[2026-05-25] Master model upgraded to moonshot/kimi-k2.6 (from deepseek-chat), task_timeout=900s active in agent-settings.json
[2026-05-25] Comprehensive master audit completed: docs/master-audit.md documents 3 systemic problems with fix recommendations
[2026-05-25] Memory sweep test: user provided 20 preference statements covering UI (dark mode, mobile-first), database (PostgreSQL), performance (API <200ms, rate limiting), caching (Redis), logging (30-day retention), backup (daily 3am), notifications (Telegram-only, alert on 2 consecutive failures), coding style (snake_case, async/await, compact JSON, Claude for all agents except cron, prompts under 4000 tokens), schedule (10pm-2am), and builder speed concern.
[2026-05-25] User reported builder agent is too slow — requested speed improvement. Needs timeout/performance review.
[2026-09-02] User requested voice support revision — wants to talk with YAPOC via real models (OpenAI TTS/STT), not browser voiceover. Implemented: backend OpenAI onyx TTS + Whisper STT, frontend default flipped to backend.
[2026-09-02] User requested animated speaking sphere UI element (top-left, pulses with agent speech). Implemented SpeakingSphere 3-state.
[2026-09-02] User requested interactive plots + HTML reports in chat ("how much money did I burn?" should return charts). Implemented ECharts in-chat rendering + render_chart tool.
[2026-09-02] User requested automation without being asked every time (wants automatic behavior, not confirmation prompts).
[2026-09-02] User asked about adding a game to Telegram; confirmed Tic-Tac-Toe already exists (/ttt command).
[2026-09-05] User ran network scan + speed test (5 WiFi networks, connected HUAWEI-5G-43Jb_EXT at 85%; ping ~61-65ms, download ~63 Mbps, upload ~51 Mbps).
[2026-09-05] User asked for a chart of current model distribution across agents (14 agents; deepseek-chat on 10, master on DeepSeek-V4-Pro-0813).
[2026-09-05] User requested Belgrade 7-day weather forecast (via Open-Meteo) and authorized a live backend restart test (RESTART-CHECK-ac27942c, 17*23=391).
[2026-09-05] User asked what features YAPOC might be missing (no inner-doc references) and for a menu of test tasks to exercise YAPOC.
