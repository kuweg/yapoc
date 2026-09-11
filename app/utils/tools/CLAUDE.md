# app/utils/tools — Tool System

## Registry
`TOOL_REGISTRY: dict[str, type[BaseTool]]` in `__init__.py`. 41 tools total.

**Always use `build_tools(names, agent_dir)` — never instantiate tools directly.** Some tools require `agent_dir` at construction:
```python
_AGENT_DIR_TOOLS = {"memory_append", "notes_read", "notes_write", "notes_append", "health_log", "update_config"}
```

## Execution model

Tool execution passes through the deterministic/LLM security gate; review failures
are denied. Shell and Python tools also require OS isolation via bubblewrap and
prlimit, without inherited credentials. Validated Poetry dependency commands
can download packages and write the project's managed virtualenv; other
execution supports installed Node/package-manager runtimes and frontend builds, with internet/DNS access by default (`EXECUTION_NETWORK_ENABLED=false` disables it). See
[execution-security.md](../../../docs/execution-security.md) for requirements,
limits, and operational changes.

## Full tool list by file

| File | Tools |
|---|---|
| `server.py` | `server_restart`, `process_restart` |
| `shell.py` | `shell_exec` |
| `execute_code.py` | `execute_code` (script API in `code_api.py`) |
| `file.py` | `file_read`, `file_write`, `file_edit`, `file_delete`, `file_list` |
| `memory.py` | `memory_append`, `notes_read`, `notes_write`, `notes_append`, `health_log` |
| `web.py` | `web_search`, `fetch_page` |
| `search.py` | `search_memory` |
| `delegation.py` | `spawn_agent`, `ping_agent`, `kill_agent`, `check_task_status`, `read_task_result`, `wait_for_agent`, `wait_for_agents`, `read_agent_logs` |
| `agent_mgmt.py` | `create_agent`, `delete_agent` |
| `model_manager.py` | `check_model_availability`, `list_models`, `update_agent_config` |
| `memory.py` | `update_config` |
| `git.py` | `git_status`, `git_diff`, `git_log`, `git_show`, `git_commit`, `git_branch`, `git_restore` |

## Key tool behaviors

### `shell_exec`
Runs inside a Linux bubblewrap namespace. Restricted agents use one exact
executable plus arguments, without shell expansion. The timeout kills and reaps
the process group; stdout/stderr are read with a shared byte limit. Output is
redacted and capped. Native Git/integration tools handle authenticated operations.

### `execute_code`
Runs a Python subprocess in the same OS boundary. `yapoc` provides read, write,
edit, delete, ls, grep, and exists helpers. Helpers improve errors; OS mounts
protect forbidden paths even when scripts bypass helpers with ordinary Python.
Default timeout 30s, maximum 120s. Missing isolation means execution is refused.

### `file_edit`
`old_string` must appear **exactly once** in the file. Atomic write via `mkstemp + os.replace`.

### `file_delete` — protected names
Refuses to delete: `.env`, `.git`, `.gitignore`, `PROMPT.MD`, `TASK.MD`, `MEMORY.MD`, `NOTES.MD`, `HEALTH.MD`, `CONFIG.yaml`.

### `file_read`
Rejects credential files and their symlink aliases. Redacts and caps direct output at 50 KiB; the agent result boundary applies a 20,000-character cap. Paths must resolve inside `project_root`.

### `spawn_agent`
Writes structured TASK.MD frontmatter (`assigned_by: master`, `status: pending`), then either assigns to a running agent (watchdog picks up) or spawns subprocess. Polls STATUS.json for `agent_spawn_timeout` seconds.

### `wait_for_agent`
Polls TASK.MD every `poll_interval` seconds (default 15) up to `timeout` (default 300). Returns full `## Result` or `## Error` content. **Side effect**: if agent has `lifecycle.temporary: true`, auto-deletes the agent directory after reading result.

### `wait_for_agents`
Polls multiple agents' TASK.MD simultaneously via `asyncio.gather`. Parameters: `agent_names: list[str]`, `timeout: int = 300`, `poll_interval: int = 10`, `fail_fast: bool = True`. Returns a structured per-agent summary (status + result/error). If `fail_fast=true` (default), returns early the moment any agent reports `error`, marking remaining agents as `interrupted`. Temporary agents are auto-cleaned on `done` just like `wait_for_agent`.

### `execute_dag`
Run a directed acyclic graph of agent tasks in topological order. Independent nodes run in parallel within each batch; downstream nodes wait for their dependencies. Each downstream node automatically receives its upstream nodes' `## Result` content in its `## Context` section — agents don't need to call `read_task_result`.

**Input:**
```json
{
  "nodes": [
    {"id": "fetch", "agent": "researcher", "task": "...", "depends_on": []},
    {"id": "transform", "agent": "builder", "task": "...", "depends_on": ["fetch"]},
    {"id": "save", "agent": "keeper", "task": "...", "depends_on": ["transform"]}
  ],
  "timeout": 600,
  "poll_interval": 3,
  "fail_fast": true
}
```

**Validation** (returned as `ERROR: ...` strings, no exception leak):
- Empty `nodes` list.
- Missing/empty `id`, `agent`, or `task` on any node.
- Duplicate `id`s.
- Unknown `agent` (no matching directory under `app/agents/`).
- Unknown `depends_on` reference.
- Cycle detected.

**Execution:** Kahn's topological sort. Batch `n` is the set of nodes whose deps are all `done`. Within a batch, all nodes spawn first (sequentially to avoid races on the spawn cap), then are polled in parallel via `asyncio.gather`. Per-node duration is measured from spawn → terminal status. `fail_fast=true` (default) aborts the moment any node errors — downstream nodes are marked `interrupted` and the tool returns.

**Output:** JSON-ish string `{summary, nodes: {id: {agent, status, duration_s, result|error}}}`. `result`/`error` are truncated at 500 chars per node — full content remains in each agent's `TASK.MD`.

**When to use:** any time there are real dependencies between sub-agent tasks. Replaces manual `spawn_agent` + `wait_for_agent` chains. For independent fan-out without dependencies, `wait_for_agents` is still fine.

**Authorization:** the DAG tool reuses `SpawnAgentTool` under the hood, so each spawn inside the DAG honors the caller's `delegation_targets`. Master (in `_UNRESTRICTED_SPAWNERS`) can spawn any agent; others must list every spawned agent in their CONFIG.yaml `delegation_targets`.

### `search_memory`
Hybrid retrieval over the indexed memory store (`app/utils/db.py` SQLite + FTS5 + per-row 384-dim embedding). Combines FTS5 keyword rank with cosine similarity via Reciprocal Rank Fusion (`K = 60`). Inputs: `query` (natural language, required), `agent` (optional filter), `top_k` (default 8). Returns ranked entries with `agent`, `source`, `timestamp`, `content`, `rrf_score`. Embeddings are never returned.

**What's indexed** (by `app/utils/indexer.py`, APScheduler job every `settings.embedding_index_interval_minutes`):
- `<agent>/MEMORY.MD` — append-only, line-by-line, checkpointed by last-indexed line number
- `<agent>/NOTES.MD` — per `## section`, hash-checkpointed (re-indexed on change)
- `<agent>/LEARNINGS.MD` — per `## section`, hash-checkpointed
- `<agent>/TASK.MD` — only terminal tasks (`done` / `error`), hash-checkpointed
- `shared/KNOWLEDGE.MD` — per `## section`, hash-checkpointed

Lines under 20 chars are skipped. Embeddings come from `sentence-transformers/all-MiniLM-L6-v2` (~22 MB, 384-dim, lazy-loaded).

**When to call**: before spawning duplicate work, before answering "have we seen this before", before re-deciding on something that may already have a documented decision. Cheap (~5–20 ms once the model is loaded).

**HTTP equivalent**: `GET /memory/search?q=&agent=&top_k=` returns the same hybrid ranking. The UI Memory tab's search panel calls this. Both surfaces hit the same index.

### `fetch_page`
Fetches an http(s) URL and returns extracted main content as markdown via `trafilatura`. Use AFTER `web_search` to read the actual page text. Caps content at `max_chars` (default 16000). Rejects non-http(s) schemes, blocks beyond 5 redirects, 15s total timeout. Does NOT render JavaScript, follow robots.txt, or cache.

### `create_agent`
Protected agent names: `master, planning, builder, keeper, cron, doctor, base, model_manager`. Name must match `^[a-z][a-z0-9_-]+$`. Creates all 8 agent files including `agent.py` and `__init__.py`.

### `delete_agent`
Refuses if agent STATUS.json shows `running` or `idle` — suggests `kill_agent` first.

### git tools (`git.py`)

Granted to builder + master (all seven) and, read-only, to evaluator and planning.

| Tool | Notes |
|---|---|
| `git_status` | Branch + staged/unstaged/untracked. Read-only. |
| `git_diff` | **Defaults to `--stat` when no `paths` given** — a whole-tree patch on this repo is thousands of lines. Pass `paths` for the real patch, or `stat: false` to force one. |
| `git_log` / `git_show` | History. Read-only. |
| `git_commit` | `paths` is **required and explicit**; stages with `git add -- <paths>` then `commit --only -- <paths>`. |
| `git_branch` | list / create / switch / create_and_switch. |
| `git_restore` | Scoped undo. In `RISKY_TOOLS` (destroys uncommitted work) and hard-denied for `app/agents/security/`. |

Three invariants, each with a reason:

1. **Never stage or restore by wildcard.** No `add -A`, no bare `checkout .`. This is
   the same concern that makes `app/backend/git_safety.py` refuse *automatic* commits —
   a dirty-file diff cannot tell an agent's edit from a human's concurrent one. Explicit
   paths make "sweep in someone else's work" structurally impossible rather than merely
   unlikely.
2. **No raw argument passthrough.** Every parameter is structured, paths and refs
   rejected if they start with `-`, and `--` precedes every path list. A tool that
   forwarded arbitrary git flags would be a shell (`git --exec-path`, `--upload-pack`,
   `-c core.pager=`), bypassing `shell_exec`'s allowlist and the sandbox.
3. **The sandbox applies.** All seven take `SandboxPolicy`; `forbidden_paths` blocks a
   restore just as it blocks a write, or the file lock has a hole in it.

No `push`/`pull`/`fetch`/`remote` — publishing to a remote is an irreversible
outside-world action under the user's identity, the same category the security policy
gates for mail. No `merge`/`rebase`/`reset`/`cherry-pick`/`stash`/`clean`/`tag`.

## Adding a new tool
1. Create class in appropriate `tools/*.py` implementing `BaseTool`
2. Add to `TOOL_REGISTRY` in `__init__.py`
3. If it needs `agent_dir` at construction, add name to `_AGENT_DIR_TOOLS`
4. Add tool name to relevant agents' `CONFIG.yaml` tools list
