
## Rule: Check existing code structure before routing refactoring tasks
- **Observed:** 2026-04-13
- **Context:** User asked to refactor doctor agent to separate stale detection into its own method. I routed to planning (complexity 7) without first checking if the separation already existed. Builder found _check_stale_tasks() was already a dedicated method, so no work was needed.
- **Action:** Before routing any refactoring task: (1) Use file_read to inspect the current code structure, (2) Verify the requested separation/pattern doesn't already exist, (3) If it does exist, inform the user immediately without delegation, (4) Only delegate if actual refactoring work is needed
- **Confidence:** high

## Rule: After code/config changes by sub-agents, restart the backend server
- **Observed:** 2026-05-13
- **Context:** User requested that after any code change made by Builder or Keeper, the backend server should be restarted to apply changes. Not all changes need a restart (e.g., read-only lookups), but file mutations (writes, edits, deletes) to Python files, config files, or agent settings require a server restart to take effect.
- **Action:** After any Builder or Keeper sub-agent completes a file mutation (write, edit, delete), call server_restart to apply changes. Exception: if the change was to agent prompt files (MEMORY.MD, NOTES.MD, LEARNINGS.MD) that only affect agent behavior on next turn, a restart is not needed. In CLI mode, warn the user that the backend will restart. In UI mode, warn that there will be a brief disconnect.
- **Confidence:** high


## Rule: Auto-restart backend after code/config mutations
- **Observed:** 2026-05-13
- **Context:** User explicitly requested that after any code/config change by Builder or Keeper, the backend should restart automatically without asking for permission.
- **Action:** After any Builder or Keeper sub-agent completes a file mutation (write, edit, delete) to Python files, config files, agent-settings.json, or .env: call server_restart automatically. Do NOT ask the user for permission. Exception: skip restart if the change was only to agent prompt files (MEMORY.MD, NOTES.MD, LEARNINGS.MD). In UI mode, warn the user about a brief disconnect before restarting.
- **Confidence:** high

