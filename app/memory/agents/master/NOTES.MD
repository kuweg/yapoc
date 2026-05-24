## Prompt Audit 2026-05-18 19:42

Audited 9 agent PROMPT.MD files (excluded: security, master). One rough edge identified per agent.

### 1. Builder — References non-existent tools `create_agent` and `delete_agent`
- **File:** `app/agents/builder/PROMPT.MD`
- **Rough edge:** The prompt says "Scaffold new agents using the `create_agent` tool" and "Delete dynamic agents using the `delete_agent` tool" — but neither tool exists in Builder's actual tool list. Builder can only create files via `file_write`/`file_edit` and delete via `file_delete`. This instruction is misleading and would cause Builder to hallucinate tool calls.
- **Fix:** Replace with "Create agent directory scaffolding (TASK.MD, MEMORY.MD, NOTES.MD) using file_write" and "Delete agent directories by deleting individual files with file_delete."

### 2. Cron — Missing peer delegation constraints
- **File:** `app/agents/cron/PROMPT.MD`
- **Rough edge:** The prompt says "spawn the appropriate agents to execute recurring work" but doesn't specify which agents Cron can spawn. It references `spawn_agent(agent_name=job.assign_to, ...)` without any guardrails on which agents are allowed. Cron's CONFIG.md `delegation_targets` may restrict this, but the prompt itself should mention the constraint.
- **Fix:** Add a constraint line: "Only spawn agents listed in your CONFIG.md delegation_targets. Currently: builder, keeper, doctor, master."

### 3. Doctor — Response Actions table references `spawn_agent planning` but Planning may not be a delegation target
- **File:** `app/agents/doctor/PROMPT.MD`
- **Rough edge:** The "Response Actions" table says "Spawn planning to investigate" (`spawn_agent planning`) but Doctor's `delegation_targets` may not include Planning. If the sandbox enforces delegation_targets, this action would fail silently. The prompt assumes Doctor can spawn any agent.
- **Fix:** Either add Planning to Doctor's delegation_targets, or change the action to "Create a task for Master to investigate via memory_append" since Master can spawn Planning.

### 4. Evaluator — References non-existent tool `get_recent_signals()`
- **File:** `app/agents/evaluator/PROMPT.MD`
- **Rough edge:** The entire methodology is built around calling `get_recent_signals()` which returns "unified observability snapshot" — but this tool does not exist in Evaluator's tool list. The prompt was written for a tool that was never implemented. Every proposal is supposed to "cite at least one specific signal" from this tool, making the entire workflow impossible.
- **Fix:** Either implement `get_recent_signals` as a real tool, or rewrite the methodology to use available tools (file_read on HEALTH.MD files, search_memory, etc.).

### 5. Keeper — Sandbox loophole in file access rules
- **File:** `app/agents/keeper/PROMPT.MD`
- **Rough edge:** The "Sandboxed File Access" section lists specific paths (.env, settings.py, pyproject.toml, .env.example) but then adds "Any file explicitly listed in your task" — this is a loophole that could allow a task to bypass the sandbox by simply listing any file. The sandbox should be enforced at the tool level, not the prompt level.
- **Fix:** Remove the "Any file explicitly listed in your task" exception, or clarify that it only applies to files within the same config domain.

### 6. Librarian — Hardcodes "ONE turn" assumption that may not hold
- **File:** `app/agents/librarian/PROMPT.MD`
- **Rough edge:** The prompt repeatedly states "Due to system limitations, you only get ONE turn" and "After calling file_read, the tool result is provided to you. Your output (the ## Result section) IS your final answer" — this hardcodes a runtime constraint that may not be true for all deployments. If the agent gets multiple turns, this instruction actively prevents it from doing proper work.
- **Fix:** Replace with a soft constraint: "Prefer single-turn execution. Read the document, then output your summary. If you need a second turn, use it sparingly."

### 7. Model Manager — References non-existent tools `update_agent_config`, `check_model_availability`, `list_models`
- **File:** `app/agents/model_manager/PROMPT.MD`
- **Rough edge:** The prompt references three tools (`update_agent_config`, `check_model_availability`, `list_models`) that do not appear in Model Manager's actual tool list. The entire workflow section ("When asked to audit or optimize agents") depends on these tools. Without them, the agent cannot execute its core responsibilities.
- **Fix:** Either implement these tools, or rewrite the workflow to use available tools (file_read on agent-settings.json, file_edit for config changes, web_search for model info).

### 8. Planning — References non-existent tool `add_task_trace`
- **File:** `app/agents/planning/PROMPT.MD`
- **Rough edge:** The prompt says "call `add_task_trace` BEFORE spawning sub-agents" and "call `add_task_trace` with a 1-sentence rationale BEFORE executing" — but `add_task_trace` is not in Planning's tool list. This instruction would cause the agent to hallucinate a tool call or waste a turn trying to use it.
- **Fix:** Replace with `memory_append` for decision logging, or remove the instruction entirely.

### 9. Researcher — References non-existent tool `fetch_page`
- **File:** `app/agents/researcher/PROMPT.MD`
- **Rough edge:** The prompt lists `fetch_page` as an available tool ("Fetch and read a specific URL, returns extracted main content as markdown") but this tool does not exist in Researcher's actual tool list. The research methodology depends on it ("Read Multiple Sources: Fetch the 2–4 most relevant pages"). Without it, Researcher can only see search snippets.
- **Fix:** Either implement `fetch_page` as a real tool, or remove references to it and adjust the methodology to work with search snippets only.

[test-2026-05-18] direct-edit-verified
