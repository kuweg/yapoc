# Master Agent Prompt & Config Analysis

> Generated: 2026-05-25
> Purpose: Inform image recognition feature planning

---

## 1. Image/Media/Vision References in PROMPT.MD

### `image_read` — 1 mention

The only mention of `image_read` is in the **tools list** embedded in the prompt's "Available agents" table and the direct tools section. Specifically:

**From the CONFIG.yaml tools list** (reproduced in prompt context):
```yaml
  - image_read
```
It's listed alongside `send_telegram_message`, `web_search`, `fetch_page`, etc. under the `# ── Self` section. No special instructions about its usage exist in the prompt body.

**No mentions of**:
- `media` — not found in PROMPT.MD
- `photo` — not found in PROMPT.MD
- `vision` — not found in PROMPT.MD

**Conclusion**: `image_read` is granted as a tool but **never described** — Master has no instructions on when or how to use it.

---

## 2. Tools/Commands Section for Master Agent

Master's PROMPT.MD does not contain a dedicated "tools" section per se. Instead, tool-related information lives in two places:

### A. Tool Ladder (section "How to get information")

| Question | Tool |
|---|---|
| "what model does X use?" | `show_agent_settings(agent_name="X")` |
| "what's in file Y?" | `file_read(path="Y")` |
| "what files are in dir Z?" | `file_list(path="Z")` |
| "what did sub-agent X produce?" | `read_task_result(agent_name="X")` |
| "is sub-agent X still running?" | `ping_agent` / `check_task_status` |
| "what's in sub-agent X's crash log?" | `read_agent_logs` |

### B. Direct Edits vs Delegation (section)

**Edit directly** when:
- File is under `app/agents/master/` (own dir)
- Single config value in `app/config/agent-settings.json` / `app/config/settings.py` / `.env`
- Single well-specified change (one value, one line)
- Reversible (git autocheckpoint)

**Delegate** when:
- Multi-file changes or unclear scope → planning
- Source code edits (Python, TS, frontend) → builder
- Shell commands → builder or keeper
- Need to read+understand before editing → builder/keeper
- JSON shape uncertain for agent-settings.json → keeper

### C. Available Agents Table

Lists all sub-agents with their roles, tools, and delegation targets.

---

## 3. CONFIG.yaml — Tools List (Complete)

From `app/agents/master/CONFIG.yaml`:

### Reads (safe — do them yourself)
```yaml
- file_read
- file_list
- file_write
- file_edit
- file_delete
- show_agent_settings
```

### Delegation
```yaml
- spawn_agent
- ping_agent
- kill_agent
- wait_for_agent
- wait_for_agents
- execute_dag
- check_task_status
- read_task_result
- read_agent_logs
```

### Agent management
```yaml
- create_agent
- delete_agent
```

### Self
```yaml
- server_restart
- process_restart
- web_search
- fetch_page
- memory_append
- notes_read
- notes_write
- notes_append
- health_log
- agent_amnesia
- search_memory
- learnings_append
- shared_knowledge_append
- image_read
- send_telegram_message
```

### Sandbox restrictions
```yaml
sandbox:
  forbidden:
    - .env
    - app/config/settings.py
    - pyproject.toml
```

### Runner config
```yaml
runner:
  task_timeout: 0          # unbounded
  poll_interval: 30
  retry_attempts: 3
  context_memory_limit: 30
  context_health_limit: 10
  context_notes_limit: 5000
  context_learnings_chars: 4000
  context_knowledge_chars: 3000
```

---

## Key Findings for Image Recognition Feature

| Finding | Detail |
|---------|--------|
| `image_read` is in tools | Yes — listed under `# ── Self` in CONFIG.yaml |
| PROMPT.MD mentions image_read? | No — zero instructions on how/when to use it |
| PROMPT.MD mentions vision/media/photo? | No |
| PROMPT.MD mentions "tool" in relevant context? | Only in tool ladder and delegation sections — no image-specific guidance |
| Master has `image_read` capability | **Undocumented** — tool is gated by CONFIG.yaml but never described in the prompt |
| Runner config | `task_timeout: 0` (unbounded), supports long-running image processing |

### Recommendations

1. **Add a section to Master's PROMPT.MD** describing when to use `image_read` (e.g., "The user may send images via the web UI. When you receive an image, use `image_read` to load it and analyze it directly.")
2. **If image processing should be delegated** (e.g., to a dedicated vision agent), update the "Available agents" table and complexity routing to include it.
3. **Verify `image_read` actually works** in Master's runtime context — it's listed in CONFIG.yaml but may need backend tool registration before it returns usable data.
