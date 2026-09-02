
## Rule: Never spawn parallel tasks to the same singleton builder agent
- **Observed:** 2026-09-01
- **Context:** Delegating 3 concurrent subtasks, all to 'builder'. Builder is a single process with ONE TASK.MD; concurrent spawns overwrite each other's TASK.MD and collide on the atomic tmp-replace write. Only one task landed; the other two were silently lost.
- **Action:** When a task needs multiple builder subtasks, run them SEQUENTIALLY: spawn builder, wait_for_agent, verify, then spawn the next. Never send >1 spawn to the same agent in parallel. Use wait_for_agents only when targeting DIFFERENT agent names.
- **Confidence:** medium

