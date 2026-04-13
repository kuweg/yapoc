
## Rule: Check existing code structure before routing refactoring tasks
- **Observed:** 2026-04-13
- **Context:** User asked to refactor doctor agent to separate stale detection into its own method. I routed to planning (complexity 7) without first checking if the separation already existed. Builder found _check_stale_tasks() was already a dedicated method, so no work was needed.
- **Action:** Before routing any refactoring task: (1) Use file_read to inspect the current code structure, (2) Verify the requested separation/pattern doesn't already exist, (3) If it does exist, inform the user immediately without delegation, (4) Only delegate if actual refactoring work is needed
- **Confidence:** high

