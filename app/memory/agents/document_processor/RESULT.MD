I'll scan agent memory and session history for repeated procedures, then check existing skills.I see existing skills. Let me check the load_skills mechanism and the existing skill names, plus scan memory/session history.I need to understand the create_skill mechanism and load_skills. Let me check how skills are defined and whether there's a create_skill tool/function.I understand the skill system now. Note: I don't have `create_skill`/`load_skills` as actual tools in my toolset — but I can create the YAML file directly via file_write (which is what create_skill does). Let me scan memory and session history for repeated procedures.I have a rich picture of master's memory. Now let me look at the session history and other agents' memory to find the most frequently repeated procedure. The most obvious candidate I see is the **"Continue the original request / Summarize this child result"** pattern, and the **memory-sweep** pattern. Let me check the session history and other agent memories to quantify.Let me look at the cron agent's MEMORY.MD (the one that runs these sweeps) and the doctor/librarian memories to find the most repeated procedure. Also let me check the session history structure.I now have overwhelming evidence. The single most frequently repeated procedure is the **memory-sweep** — it appears dozens of times across cron and librarian memory. But critically, the librarian's own sweep notes repeatedly state: *"No skill capture needed (no 3x-repeated unskilled procedure)"* and *"memory-sweep procedure itself intentionally left unskilled (fully specified per-task by cron)"*.

However, the task asks me to find the most frequently repeated procedure. The memory-sweep is clearly the #1 repeated procedure, but it's already fully specified per-task by cron and intentionally left unskilled. Let me check the existing skills list precisely and confirm what's already captured.I now have a complete picture. Let me analyze the candidates for the "single most frequently repeated procedure":

1. **memory-sweep** — by far the most repeated (dozens of times), but the librarian has *explicitly and repeatedly* documented it as "intentionally left unskilled (fully specified per-task by cron)". It's not a candidate for a skill because it's already fully specified.

2. **"Continue the original request / Summarize this child result"** — this is the master's child-result consumption loop, repeated hundreds of times. But it's not a "procedure" in the skill sense; it's the master's core dispatch loop.

3. **The "verify X is live after restart, then summarize" pattern** — repeated many times (verify endpoint/tool live via 404-vs-405 check, then summarize). This is a genuinely repeatable procedure.

4. **"Spawn builder/keeper → verify edits actually landed → restart → verify live"** — the feature-build verification loop.

The most defensible candidate that is (a) clearly repeated 3+ times, (b) a real procedure, and (c) NOT already a skill is the **post-restart verification pattern**: verify a new endpoint/tool is actually live (using the 404-vs-405 heuristic), confirm edits persisted, then summarize. This appears dozens of times in master's memory.

However, I need to be careful. The librarian's own sweeps have repeatedly concluded "no skill capture needed (no 3x-repeated unskilled procedure)". The memory-sweep is the #1 repeated procedure but is deliberately unskilled.

Let me check whether there's a "verify after restart" type skill already, and look at what the most genuinely repeated *unskilled* procedure is. The strongest candidate is the **"verify a change is live after restart"** procedure, which recurs constantly.This confirms the pattern clearly. The **"verify a change is live after backend restart"** procedure is repeated 20+ times in master's memory alone, with a consistent methodology:

1. Restart backend (or confirm it restarted)
2. Verify the new endpoint/tool is live — using the **404-vs-405 heuristic** (404 = route registered + existence check working; 405 = route missing)
3. Verify edits actually persisted (grep/file_read)
4. Summarize to user

This is a genuinely repeatable procedure, occurs 3+ times (actually 20+), and is NOT already a skill. The existing `backend_restart_decision` skill covers *deciding whether* to restart, and `restart_recovery` covers *recovering pending work* — but neither covers the *post-restart verification* procedure.

This is the clear winner. Let me create the skill.Skill-capture sweep complete.

## Result

**Created one skill: `verify_after_restart`** (`app/skills/verify_after_restart.yaml`)

**Evidence of repetition:** The procedure "verify a change is actually live after a backend restart, then summarize" appears **20+ times** in master's MEMORY.MD (43 "verify" mentions, 21 matching the live-verification pattern). The methodology is consistent every time:
1. Confirm the backend actually restarted (never assume)
2. Verify endpoint/tool live via the **404-vs-405 heuristic** (404 = route registered; 405 = route missing)
3. Verify edits persisted (grep/file_read — parallel `file_edit` can silently drop)
4. Verify both config layers (CONFIG.yaml authoritative + agent-settings.json fallback)
5. Summarize with evidence

**Why it qualified:** Clear procedure, 3+ occurrences (actually 20+), and not already a skill. `backend_restart_decision` covers *deciding whether* to restart; `restart_recovery` covers *recovering pending work* — neither covers post-restart verification.

**Runner-up excluded:** `memory-sweep` is the single most-repeated procedure overall (dozens of occurrences), but the librarian has explicitly and repeatedly documented it as *"intentionally left unskilled (fully specified per-task by cron)"* — so it was correctly excluded.

No application code was modified.