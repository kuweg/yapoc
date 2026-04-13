# app/utils — Utilities

## Subpackages
- `adapters/` — LLM adapter registry (anthropic, openai, ollama, openrouter). See `adapters/CLAUDE.md`.
- `tools/` — 26-tool registry for agents. See `tools/CLAUDE.md`.

## context.py — Token estimation & auto-compact

`estimate_tokens(messages: list[dict]) -> int`
- Rough estimate: `len(json.dumps(messages)) // 4`

`should_compact(messages, context_window, threshold=0.85) -> bool`
- Returns True when estimated tokens ≥ `threshold * context_window`

`compact_messages(messages, system_prompt, config, focus, adapter) -> list[dict]`
- Calls a cheap LLM (`settings.context_compact_model`, default `claude-haiku-4-5-20251001`) to summarize the conversation into a single user message. Returns `[{"role": "user", "content": "<summary>"}]`.
- Called internally by `BaseAgent._compact_messages()`.

## crash.py — Crash tracking & subprocess watchers

`count_crashes(crash_path: Path) -> int`
- Counts `## Crash` headers in CRASH.MD. Returns 0 if file missing.

`write_crash_report(crash_path, *, pid, exit_code, entity_name, restart_count, traceback_str, last_output_lines)`
- Appends structured markdown entry to CRASH.MD.

`server_exit_watcher(proc, log_path, crash_path) -> threading.Thread`
- Daemon thread; watches uvicorn process. Writes crash report on non-zero exit. Used by CLI.

`agent_exit_watcher(proc, log_path, crash_path, agent_name, restart_count) -> threading.Thread`
- Same for agent subprocesses. Used by `SpawnAgentTool` and `routers/agents.py`.

`rotate_output_log(output_path, max_size_kb)`
- Truncates oldest half of OUTPUT.MD when it exceeds `settings.log_max_size_kb` (512KB). Note: splits at midpoint character, not line boundary.

## __init__.py
Re-exports `PROJECT_ROOT` and `AGENTS_DIR` from `settings` for convenience:
```python
from app.utils import PROJECT_ROOT, AGENTS_DIR
```
