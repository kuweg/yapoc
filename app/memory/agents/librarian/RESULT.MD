I'll perform the skill-capture sweep. Let me start by checking existing skills and scanning agent memory for frequently repeated procedures.Let me scan the memory files of the key agents to identify frequently repeated procedures. Let me read the MEMORY.MD files of the most active agents.I have a good picture of the builder's activity. Let me look at the builder's LEARNINGS and NOTES files, and also check the doctor and evaluator memory to identify repeated procedures. Let me also check the builder's NOTES.MD and LEARNINGS.MD.

The builder's MEMORY.MD shows a very clear repeated procedure: **creating a file with exact content and verifying it** (via file_read + wc -c/od -c). This appears many times (pw_verify.txt, pw_leak.txt, chain_test files, chat_probe.txt, anim_probe files, etc.). This is a strong candidate.

Let me also check the builder's LEARNINGS and NOTES to confirm, and check other agents.I now have a clear picture. Let me analyze the most frequently repeated procedures across the agent memory.

**Candidate procedures observed:**

1. **Create file with exact content + verify** (builder): This appears MANY times in builder's MEMORY.MD — pw_verify.txt, pw_leak.txt, pw_leak2.txt, pw_leak3.txt, pw_suite.txt, chain_test step1/2/3 (multiple times), chat_probe.txt, anim_probe files. The pattern is: create file with exact content, then verify via file_read + wc -c/od -c to confirm exact bytes/no trailing newline. This is repeated 15+ times. This is a very strong candidate.

2. **Frontend build** (`npm run build`) — already captured as `frontend_build` skill.

3. **Syntax/compile check** (ast.parse + py_compile) — appears a few times (notification_queue.py, runner.py, concilium.py, skills.py). Maybe 4-5 times.

4. **Config edit in settings.py** — appears a couple times.

The clear winner is the **"create file with exact content and verify byte-exactness"** procedure. It's repeated 15+ times in builder's memory, it's deterministic and reusable, and it's NOT covered by any existing skill (docker_build, git_commit, frontend_build).

Let me verify this isn't already a skill and confirm the pattern. The existing skills are docker_build, git_commit, frontend_build — none cover file creation with byte-exact verification.

Let me create the skill. The procedure is:
1. Create the file with the exact specified content (no trailing newline/whitespace unless specified)
2. Verify via file_read that content matches exactly
3. Verify byte count via wc -c (and od -c if needed) to confirm no trailing newline/whitespace
4. Report the byte count and exact content

Let me create this skill.The skill was created successfully. Let me log this to my memory and notify the parent.Skill-capture sweep complete.

**Summary:** I scanned agent memory (builder, master, keeper, doctor) and identified the single most frequently repeated procedure: **creating a file with byte-exact content and verifying no trailing newline/whitespace**. This appeared 15+ times in builder's MEMORY.MD (pw_verify.txt, pw_leak*.txt, pw_suite.txt, chain_test step1/2/3 across three rounds, chat_probe.txt, anim_probe a/b/c).

I verified it was NOT already covered by existing skills (docker_build, git_commit, frontend_build), then created the new skill **`create_exact_file`** capturing the full procedure:
1. Write exact content via file_write (no trailing newline)
2. Verify via file_read
3. Confirm byte count via wc -c/od -c to rule out trailing newline/whitespace
4. Report byte count + exact content

The skill is now available to all agents.