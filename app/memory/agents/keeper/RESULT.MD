Let me read the agent-settings.json file first.Now I need to check each agent's tools array for "grep" and add it if missing. Let me check each one:

1. **master** — no "grep" → add it
2. **planning** — no "grep" → add it
3. **builder** — no "grep" → add it
4. **keeper** — no "grep" → add it
5. **concilium** — tools: [] → add "grep"
6. **cron** — no "grep" → add it
7. **doctor** — no "grep" → add it
8. **model_manager** — no "grep" → add it
9. **librarian** — no "grep" → add it
10. **evaluator** — no "grep" → add it
11. **security** — tools: [] → add "grep"
12. **researcher** — no "grep" → add it

None of them have "grep". I'll add it to each. Let me do this efficiently with file_edit operations.

I'll add "grep" as the last tool in each array. Let me do them one by one, starting with master.The indentation might be different. Let me check the exact content more carefully.Let me read the file again with precise line numbers.I see — the fallbacks for master are slightly different from what I assumed. Let me get the exact unique string for master's closing bracket.Now I have the exact strings. Let me do the edits. I'll add "grep" to each agent's tools array.

**1. master** — add after "create_skill"**2. planning** — add after "load_skills"**3. builder** — add after "create_skill"**4. keeper** — add after "file_list"**5. concilium** — tools is empty array `[]`**6. cron** — add after "shared_knowledge_append"**7. doctor** — add after "check_task_status"**8. model_manager** — add after "update_agent_config"