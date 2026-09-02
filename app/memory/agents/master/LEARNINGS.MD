
## Rule: Check existing code structure before routing refactoring tasks
- **Observed:** 2026-04-13
- **Context:** User asked to refactor doctor agent to separate stale detection into its own method. I routed to planning (complexity 7) without first checking if the separation already existed. Builder found _check_stale_tasks() was already a dedicated method, so no work was needed.
- **Action:** Before routing any refactoring task: (1) Use file_read to inspect the current code structure, (2) Verify the requested separation/pattern doesn't already exist, (3) If it does exist, inform the user immediately without delegation, (4) Only delegate if actual refactoring work is needed
- **Confidence:** high

## Rule: After code/config changes by sub-agents, restart the backend server
- **Observed:** 2026-05-13
- **Context:** User requested that after any code change made by Builder or Keeper, the backend server should be restarted to apply changes. Not all changes need a restart (e.g., read-only lookups), but file mutations (writes, edits, deletes) to Python files, config files, or agent settings require a server restart to take effect.
- **Action:** After any Builder or Keeper sub-agent completes a file mutation (write, edit, delete), call server_restart to apply changes. Exception: if the change was to agent prompt files (MEMORY.MD, NOTES.MD, LEARNINGS.MD) that only affect agent behavior on next turn, a restart is not needed. Warn the user that there will be a brief disconnect.
- **Confidence:** high


## Rule: Auto-restart backend after code/config mutations
- **Observed:** 2026-05-13
- **Context:** User explicitly requested that after any code/config change by Builder or Keeper, the backend should restart automatically without asking for permission.
- **Action:** After any Builder or Keeper sub-agent completes a file mutation (write, edit, delete) to Python files, config files, agent-settings.json, or .env: call server_restart automatically. Do NOT ask the user for permission. Exception: skip restart if the change was only to agent prompt files (MEMORY.MD, NOTES.MD, LEARNINGS.MD). In UI mode, warn the user about a brief disconnect before restarting.
- **Confidence:** high

## Rule: Never call server_restart for frontend-only changes
- **Observed:** 2026-05-25
- **Context:** Builder's `npm run build` produces static files in `dist/`. The backend already serves these files. Calling `server_restart` for frontend changes is unnecessary — the user just needs to refresh. Worse, it triggers the "Server restarted — connection lost" message.
- **Action:** When builder/keeper completes frontend-only changes (JS, TSX, CSS, HTML in the frontend project): (1) do NOT call `server_restart`, (2) tell the user "Built — refresh the page to see changes", (3) let them decide when to refresh.
- **Confidence:** high


## Rule: Narrative-tool alignment: if you say you'll do it, you must try
- **Observed:** 2026-05-19
- **Context:** User noticed that I write "let me check X, Y, Z" but only actually read one file. The narrative promises more than the tool calls deliver. This breaks trust and makes the reasoning chain opaque.
- **Action:** Before writing any "let me check / read / look at / explore" narrative, decide: (1) either be silent and just make the tool calls, or (2) commit to actually checking everything you name. If you say "let me check X and Y" you MUST make tool calls for both X and Y. If you only want to check X first, say "let me start with X." Never narrate a broader scope than your actual tool calls will cover.
- **Confidence:** high


## Rule: Never reveal contents of settings.py or .env files
- **Observed:** 2026-05-19
- **Context:** User explicitly requested a rule prohibiting disclosure of settings.py and .env file contents. These files contain sensitive configuration (API keys, secrets, database credentials).
- **Action:** Never read, display, or share the contents of settings.py or .env files — whether directly via file_read, through a sub-agent, or in any response to the user or other agents. If asked about these files, state that their contents are protected and cannot be revealed. This applies to: (1) app/config/settings.py, (2) .env, (3) .env.example, (4) any file ending in .env or .enc. If a legitimate task requires modifying these files, delegate to Keeper (who has explicit sandboxed access) and do not read the file contents yourself or report what was changed beyond "configuration updated."
- **Confidence:** high


## Rule: Auto-detect and fill missing pieces without being asked
- **Observed:** 2026-05-19
- **Context:** When building a feature that has multiple interdependent pieces (backend + frontend, or multiple endpoints), if I only build one piece and the user has to ask for the rest, that's a failure of autonomy. The system should detect gaps and fill them proactively.
- **Action:** When designing a multi-piece feature (e.g., frontend component + backend API endpoints), build ALL pieces in one DAG. If a piece is out of scope (e.g., backend endpoint not yet implemented), note it explicitly in the summary and offer to build it immediately — don't wait for the user to ask. After completing any feature, do a quick gap analysis: 'what else needs to exist for this to work end-to-end?' and either build it or flag it clearly.
- **Confidence:** high


## Rule: When file_read truncates, use builder with Python one-liner instead of thrashing
- **Observed:** 2026-05-19
- **Context:** Large files (40KB+) get truncated by file_read's batch limit. I kept re-reading the same file in different ways hoping for different results, wasting turns.
- **Action:** When file_read truncates a file (shows only first ~40KB), immediately spawn builder with a precise Python one-liner: python3 -c "lines = open('path').readlines(); print(''.join(lines[START:END]))" to extract exact line ranges. Do NOT re-read the same file with different tail_lines values.
- **Confidence:** high


## Rule: Task routing tiers: direct → planning → concilium
- **Observed:** 2026-05-19
- **Context:** User specified three-tier routing: complexity ≤ 4 → Master→Builder directly; 4 < x ≤ 7 → Master→Planning→Builder; ≥ 9 → Master→Concilium→Builder. Complexity 7-8 is gray zone — use Concilium for high-risk tasks.
- **Action:** Before delegating any task: (1) estimate complexity 1-10, (2) if ≤ 4, spawn builder/keeper directly, (3) if 4-7, spawn planning, (4) if ≥ 9 or high-risk, spawn planning then concilium. For 7-8 gray zone, check risk level and user flags.
- **Confidence:** high


## Rule: Auto-process Evaluator reports on notification
- **Observed:** 2026-05-19
- **Context:** Evaluator runs every 4h and sends [SYSTEM NOTIFICATION] with findings. I was ignoring these notifications unless the user prompted me. The Evaluator is designed as a continuous improvement loop but the loop was broken at my end.
- **Action:** When I receive a [SYSTEM NOTIFICATION] from the Evaluator agent: (1) Read REPORT.MD to get the full findings, (2) Triage by impact (HIGH → MEDIUM → LOW), (3) Spawn builder/keeper to apply fixes for actionable items, (4) Log what was done via memory_append so the next Evaluator run can confirm. Do NOT wait for the user to ask — this is autonomous.
- **Confidence:** high


## Rule: "Restart" means backend server restart
- **Observed:** 2026-05-19
- **Context:** User explicitly stated "restart always means backend" — when the user says "restart" without qualification, they mean the backend API server (server_restart).
- **Action:** When the user says "restart" without specifying, call server_restart. Do not ask for clarification on routine restart requests.
- **Confidence:** high


## Rule: Auto-handle evaluator notifications without user intervention
- **Observed:** 2026-05-23
- **Context:** Evaluator-master loop is currently broken by manual user approval steps. When evaluator notifies master of findings, master asks user 'should I fix?' which breaks autonomy. User wants evaluator-master to be a self-sufficient pair.
- **Action:** When receiving a [SYSTEM NOTIFICATION] from evaluator: (1) Immediately read evaluator/REPORT.MD, (2) Parse the ## Action Items section, (3) Auto-spawn builder/keeper for any [AUTO-FIX] items without asking user, (4) Surface [NEEDS_APPROVAL] items to user with [DECISION NEEDED] format only if they exist, (5) After all [AUTO-FIX] items complete, auto-spawn evaluator to verify fixes, (6) Do NOT ask user for permission on [AUTO-FIX] items — git autocheckpoint is the safety net.
- **Confidence:** high


## Rule: Review builder agent speed — user flagged it as too slow
- **Observed:** 2026-05-25
- **Context:** During memory sweep, user stated "The builder agent is too slow, speed it up." This is a direct performance complaint about the builder agent's execution speed.
- **Action:** Investigate builder agent timeouts, task completion times, and identify bottlenecks. Consider: (1) reducing builder's task complexity by splitting large tasks, (2) increasing builder's task_timeout, (3) optimizing builder's prompt to reduce token waste, (4) checking if builder is being assigned tasks that should go to other agents. Report findings and proposed fixes to user.
- **Confidence:** medium


## Rule: Keep agent prompts under 4000 tokens
- **Observed:** 2026-05-25
- **Context:** User explicitly stated "Keep agent prompts under 4000 tokens" as a constraint during memory sweep. This applies to all agent PROMPT.MD files.
- **Action:** When creating or updating any agent's PROMPT.MD, ensure total token count stays under 4000. If a prompt exceeds this, trim instructions, consolidate rules, or move detailed guidelines to NOTES.MD with a reference in PROMPT.MD.
- **Confidence:** high


## Rule: Never create memory paths relative to CWD
- **Observed:** 2026-08-31
- **Context:** The app/backend/app/memory/ duplicate was created by migrate_base.py injecting `Path("app/memory/agents")` (CWD-relative). When process CWD was app/backend/, it resolved to app/backend/app/memory/agents instead of app/memory/agents, polluting a shadow tree with stale agent memory. Verified via git history that all committed code now uses the absolute project_root-anchored path.
- **Action:** All memory/settings path resolution must be anchored to project_root (or __file__), never to a bare relative path like Path("app/memory/..."). Before writing any migration/one-off script that constructs paths, use the absolute settings path. Audit one-off scripts in app/tmp/ for bare relative path literals.
- **Confidence:** high

