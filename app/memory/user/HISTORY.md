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
