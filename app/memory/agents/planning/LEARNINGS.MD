
## Rule: Never spawn parallel tasks to the same singleton builder agent
- **Observed:** 2026-09-01
- **Context:** Delegating 3 concurrent subtasks, all to 'builder'. Builder is a single process with ONE TASK.MD; concurrent spawns overwrite each other's TASK.MD and collide on the atomic tmp-replace write. Only one task landed; the other two were silently lost.
- **Action:** When a task needs multiple builder subtasks, run them SEQUENTIALLY: spawn builder, wait_for_agent, verify, then spawn the next. Never send >1 spawn to the same agent in parallel. Use wait_for_agents only when targeting DIFFERENT agent names.
- **Confidence:** medium


## Rule: Verify builder's claimed edits to list literals — silent partial failures happen
- **Observed:** 2026-09-09
- **Context:** Builder claimed "13 passed" and "added drive_download to DRIVE_TOOL_NAMES and DRIVE_TOOL_CLASSES", but DRIVE_TOOL_NAMES was NOT updated (still 12 items) while DRIVE_TOOL_CLASSES was. The manifest test passed only because plugin.yaml ALSO lacked drive_download, so both sides were equally wrong. My own file_edit also landed on the wrong occurrence (drive_export appears in two list literals), silently editing the wrong list.
- **Action:** After any builder subtask that edits list/dict literals or claims test counts, independently re-read the file and run the tests myself. Use unique multi-line anchors (include surrounding context) for file_edit when a string appears in multiple list literals. Never trust a "N passed" claim without re-running pytest myself.
- **Confidence:** high

