# app/agents/base — BaseAgent & Runner

## Files
- `__init__.py` — `BaseAgent` class
- `context.py` — `build_system_context()`, `_parse_runner_config()`
- `runner.py` — `AgentRunner` (long-lived subprocess watcher)
- `runner_entry.py` — subprocess entry point (`yapoc-agent --agent <name>`)

## BaseAgent

```python
BaseAgent(agent_dir: Path)
```

All agents inherit from this. Key methods:

| Method | Use when |
|---|---|
| `run(history)` | Simple one-shot, no tools, no streaming |
| `run_stream(history)` | Streaming, no tools |
| `run_stream_with_tools(history, approval_gate, manage_task_file)` | **Primary method** — streaming + tools |

### `run_stream_with_tools` details
- Multi-turn loop up to `max_turns` (from CONFIG.md or settings)
- Auto-compacts context at `context_compact_threshold` (85%) of context window
- Tools run in parallel via `asyncio.gather` — **unless** `approval_gate` is set (then sequential)
- Wrapped in `asyncio.timeout(task_timeout)`
- `manage_task_file=True` (default): clears TASK.MD after run. Set to `False` when AgentRunner calls it — the runner manages TASK.MD frontmatter itself.

### Config loading
`_load_config()` runs on every turn (not cached per-run). Order:
1. CONFIG.md YAML block
2. NOTES.MD `[config]` block (legacy)
3. `settings` defaults

`max_tokens` hardcoded to `8096` unless CONFIG.md overrides it.

### Task status lifecycle (structured TASK.MD)
```
pending → running → done | error
```
Written to frontmatter by `set_task_status()`. Regex replaces `## Result` / `## Error` sections.

`mark_task_consumed()` — adds `consumed_at` timestamp to frontmatter; prevents re-injection by the runner.

## build_system_context(agent_dir)
Assembles LLM system prompt:
1. Full `PROMPT.MD`
2. Last `context_memory_limit` (default 20) non-empty lines of `MEMORY.MD`
3. `NOTES.MD` capped at `context_notes_limit` chars (default 4000)
4. Last `context_health_limit` (default 10) lines of `HEALTH.MD`

Sections joined by `\n\n---\n\n`. All limits come from CONFIG.md runner block.

## AgentRunner (runner.py)
Long-lived subprocess; watches TASK.MD with watchdog + polls every `runner_poll_interval` seconds as fallback.

**STATUS.json schema:**
```json
{"state": "idle", "pid": 12345, "task_summary": "...", "started_at": "...", "updated_at": "...", "idle_since": "..."}
```
States: `spawning → idle → running → terminated`

**Idle timeout**: self-terminates after `agent_idle_timeout` seconds (300s default) with no tasks.

**Temporary agents**: `lifecycle.temporary: true` in CONFIG.md → agent self-terminates after one task.

**Crash handling**: `runner_entry.py` catches all exceptions and writes to `CRASH.MD` via `app.utils.crash`.

## Gotchas
- `shell_exec` tool is `RiskTier.AUTO` — runs without confirmation by default
- Token estimation is rough: `len(json.dumps(messages)) // 4`
- Config change detection requires the same `BaseAgent` instance to be reused; freshly instantiated agent won't detect changes
- `build_system_context` reads files synchronously (blocking) — only called once per turn at the start
