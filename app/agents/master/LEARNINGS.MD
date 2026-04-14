
## Rule: Check existing code structure before routing refactoring tasks
- **Observed:** 2026-04-13
- **Context:** User asked to refactor doctor agent to separate stale detection into its own method. I routed to planning (complexity 7) without first checking if the separation already existed. Builder found _check_stale_tasks() was already a dedicated method, so no work was needed.
- **Action:** Before routing any refactoring task: (1) Use file_read to inspect the current code structure, (2) Verify the requested separation/pattern doesn't already exist, (3) If it does exist, inform the user immediately without delegation, (4) Only delegate if actual refactoring work is needed
- **Confidence:** high


## Rule: Connection refused 127.0.0.1:8000 — suppress in CLI mode, investigate in UI mode
- **Observed:** 2026-04-14
- **Context:** notify_parent and add_task_trace make HTTP calls to the backend API. In CLI mode (no server running), these fail with ECONNREFUSED. The error is caught in try/except and does not break agent operation. Doctor flags it as a cross-agent pattern but it is a false positive in CLI mode.
- **Action:** Do NOT respond to the user about this error unless they specifically ask. (1) If running in CLI mode: ignore entirely — it is expected. (2) If running in UI mode and this error appears: the backend may be down — use server_restart. (3) Never treat this as the main topic of a response — focus on the user's actual task.
- **Confidence:** high


## Rule: Complex planning+builder tasks cost $1.5–3, not $0.30–0.60
- **Observed:** 2026-04-14
- **Context:** User confirmed a multi-file planning+builder task (cost tracking feature: backend + frontend + tests) cost ~$2. My estimate was $0.30–0.60 — a 3–6x underestimate.
- **Action:** When estimating cost for complexity ≥7 tasks involving planning + builder + frontend + tests, estimate $1.50–$3.00 per task. Always warn the user upfront before starting expensive tasks.
- **Confidence:** high


## Rule: Temp agents cannot use notes_write or write_file to persist answers
- **Observed:** 2026-04-14
- **Context:** Spawned 5 temp agents with notes_write tool — all tried to save answers but NOTES.MD remained empty. The notes_write tool resolves to the wrong path in temp agent sandboxes. Answers were only recoverable from wait_for_agents task result output.
- **Action:** When spawning temp agents to collect answers: (1) Do NOT rely on notes_write/write_file for persistence. (2) Instead, instruct agents to include their full answer directly in their task completion response. (3) Collect answers from wait_for_agents output, not from file reads.
- **Confidence:** high

