# YAPOC Project Audit Report

**Date:** 2026-05-13
**Scope:** Full codebase — 106 Python files across `app/config`, `app/agents`, `app/utils`, `app/backend`, `app/cli`
**Method:** Static analysis of all source files; comparison against documented architecture in `CLAUDE.md` files

---

## 1. Security Issues

### 1.1 CRITICAL — `shell_exec` is `RiskTier.AUTO`

- **File:** `app/utils/tools/shell.py:25`
- **Impact:** Any agent with `shell_exec` in its CONFIG.md tool list can execute arbitrary shell commands without any confirmation prompt. The tool runs with `start_new_session=True` in the project root directory with the parent process's user permissions. Sandbox policies (`shell_allowlist`) exist but are opt-in per agent and most agents lack them.
- **Recommendation:** Change `shell_exec` to `RiskTier.CONFIRM`. Require sandbox policies with explicit allowlists on all agents that have the tool.

### 1.2 CRITICAL — HTTP `/task/stream` bypasses approval gate

- **File:** `app/backend/routers/tasks.py:142`
- **Impact:** The SSE streaming endpoint constructs an interactive approval gate via `_pending_approvals`, but the CLAUDE.md explicitly states "HTTP `/task/stream` has no gate regardless." When called without the interactive approval flow (e.g., programmatic API calls), CONFIRM-tier tools (file writes, file deletes, agent creates/deletes, server restarts) execute automatically. Any HTTP client can trigger destructive operations.
- **Recommendation:** Implement a non-interactive approval policy for the HTTP stream endpoint (e.g., deny all CONFIRM tools by default unless explicitly authorized via API key scope).

### 1.3 HIGH — CORS allows all origins

- **File:** `app/backend/main.py:381`
- **Description:** `allow_origins=["*"]` with `allow_methods=["*"]` and `allow_headers=["*"]` exposes the entire API to any webpage if the server is network-accessible.
- **Recommendation:** Restrict `allow_origins` to the frontend origin only.

### 1.4 HIGH — Subprocess agents inherit parent environment

- **File:** `app/utils/tools/delegation.py:401`
- **Impact:** Spawned agents via `subprocess.Popen` inherit the full parent process environment including all API keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.). If an agent's OUTPUT.MD is ever leaked (e.g., via `read_agent_logs`), all API keys in the environment are exposed.
- **Recommendation:** Pass a minimal, sanitized environment to subprocess agents. Strip API keys from the environment before spawning.

### 1.5 MEDIUM — `ImageReadTool` base64-encodes images verbatim

- **File:** `app/utils/tools/file.py:328`
- **Impact:** Reads image files and base64-encodes them into the LLM context with no sanitization. Could leak sensitive image content (screenshots with credentials, PII in images) to third-party API providers.
- **Recommendation:** Add risk assessment or user confirmation before sending image data to external LLM providers.

### 1.6 MEDIUM — Webhook endpoint with empty secret is disabled but behavior unclear

- **File:** `app/config/settings.py:51`
- **Description:** `webhook_secret` defaults to `""` meaning the endpoint is "disabled." The actual disable check logic is not documented and its behavior when disabled is unclear (returns 403? 404? silently accepts?).
- **Recommendation:** Document the behavior and add explicit validation in the webhook router.

---

## 2. Bugs

### 2.1 HIGH — `_sanitize_for_memory` drops multi-line content

- **File:** `app/agents/base/__init__.py:116`
- **Description:** `first = text.split('\n')[0].strip()` discards everything after the first newline. Memory entries for multi-line responses lose stack traces, code blocks, bulleted lists, and any other structured content beyond the first line.
- **Fix:** Keep up to N lines (e.g., 3-5) before truncating, or collapse whitespace instead of splitting.

### 2.2 HIGH — `parse_config_block` is not a YAML parser

- **File:** `app/utils/adapters/base.py:136-155`
- **Description:** Uses `line.split(":", 1)` which breaks on values containing colons (`model: claude-sonnet-4-6` works, but `url: http://x:8080` truncates). Multi-line strings, quoted values, and nested blocks are not supported. CONFIG.md is described as YAML-like but uses a fragile line parser that silently corrupts config values.
- **Fix:** Replace with a proper YAML parser (PyYAML or similar), or at minimum add character-by-character parsing that handles quoted strings.

### 2.3 HIGH — Race condition: agent PID recycled after server restart

- **File:** `app/backend/main.py:44`
- **Description:** `_cleanup_stale_agent_statuses` checks `os.kill(pid, 0)` to determine if a process is alive. However, PID numbers can be recycled by the OS. A new, unrelated process could have the same PID, causing the cleanup to incorrectly mark a live agent as "terminated" or worse — leave a stale STATUS.json unchanged thinking the agent is alive.
- **Fix:** Store a unique start timestamp or nonce in STATUS.json and verify it matches before trusting the PID liveness check.

### 2.4 MEDIUM — Config resolution order differs from documentation

- **File:** `app/agents/base/__init__.py:225-271`
- **Description:** The code checks `agent-settings.json` first, then CONFIG.md, then NOTES.MD. The official documentation (CLAUDE.md) says the order is "CONFIG.md → NOTES.MD → defaults." The `agent-settings.json` layer is undocumented and silently takes priority over CONFIG.md, which could confuse users who edit CONFIG.md and don't see changes take effect.
- **Fix:** Either update documentation to include `agent-settings.json` as the first priority, or remove the JSON priority layer.

### 2.5 MEDIUM — Token estimation is inaccurate

- **File:** `app/agents/base/__init__.py:41-43`
- **Description:** `len(json.dumps(messages)) // 4` uses a 4-char-per-token heuristic. For code (operators, syntax), the ratio can be 2-3 chars per token. For verbose English, 5-6 chars per token. Error margin ≈ ±50%. This means auto-compaction triggers at wrong times — either too early (wasting LLM calls on compaction) or too late (hitting context limits and getting API errors).
- **Fix:** Use a proper tokenizer (tiktoken for OpenAI models, Anthropic's token counting API) or at least calibrate the heuristic per model family.

### 2.6 MEDIUM — Duplicate frontmatter parsing code

Three implementations with subtly different behaviors:

| Location | Type | Returns |
|----------|------|---------|
| `BaseAgent._parse_frontmatter` (`app/agents/base/__init__.py:320-331`) | Static method | `dict[str, str]` |
| `AgentRunner._parse_task_frontmatter` (`app/agents/base/runner.py:121-136`) | Instance method | `dict[str, str]` |
| `delegation._parse_frontmatter` (`app/utils/tools/delegation.py:39-49`) | Module function | `tuple[dict, str]` |

**Fix:** Consolidate into a single shared function in `app/utils/helpers.py` or a dedicated `app/utils/frontmatter.py`.

### 2.7 LOW — RESULT.MD contains error text as "success"

- **File:** `app/agents/base/__init__.py:1077-1082`
- **Description:** The `finally` block writes `[ERROR] <exception>` to RESULT.MD when the task fails and no response was produced. The runner then reads RESULT.MD and writes it as the TASK.MD `## Result` section — meaning the user sees `[ERROR] ...` formatted as a successful result.
- **Fix:** Distinguish between result and error in RESULT.MD, or write errors to a separate ERROR.MD.

### 2.8 LOW — `FileListTool` truncation notice has incorrect count

- **File:** `app/utils/tools/file.py:136-138`
- **Description:** When entries exceed 200, it overwrites `entries` with `entries[:200]` and then uses `f"... ({len(entries)} more entries)"` — but `len(entries)` is now always 200, losing the true remaining count.
- **Fix:** Store the original count before truncating.

### 2.9 LOW — `idle_since` race in AgentRunner

- **File:** `app/agents/base/runner.py:362-393`
- **Description:** If an agent has been idle for ~290s and a `notify_parent` wake trigger is written, the runner may already be past `_check_task` (which returned False) and into the idle timeout check, causing self-termination just as a notification arrives. The wake-to-termination window is approximately 1 loop iteration (up to `runner_poll_interval` seconds, default 30).
- **Fix:** Check notification queue before the idle timeout, or reset idle_since when new notifications arrive.

---

## 3. Architectural Problems

### 3.1 File-based IPC as primary communication

- **Scope:** All agent-task interaction
- **Description:** The entire system relies on watching TASK.MD files with `watchdog` (inotify) + 30s polling fallback. Consequences:
  - Minimum task dispatch latency: 100-200ms at best, 30s at worst (poll fallback)
  - No transactional guarantees — two processes can read/write TASK.MD simultaneously
  - STATUS.json is written atomically (tmp + rename) but TASK.MD frontmatter is not
  - High disk I/O for a system that should be low-latency
  - File watchers can miss events on some filesystems (NFS, Docker overlay)
- **Recommendation:** Phase in a proper IPC mechanism (Unix domain sockets, Redis pub/sub, or in-process queues for agents running in the same process).

### 3.2 Agent subclasses carry no behavioral logic

- **Files:** `app/agents/planning/agent.py:7-9`, `app/agents/builder/agent.py:7-9`, `app/agents/keeper/agent.py:5-7`, `app/agents/cron/agent.py:5-7`
- **Description:** PlanningAgent, BuilderAgent, KeeperAgent, and CronAgent are 3-line constructors with zero specialized behavior. All behavior is driven by PROMPT.MD text + CONFIG.md tool list. There is no compile-time enforcement that a Builder agent can only access file-related tools — enforcement relies entirely on the LLM reading its prompt correctly and the tool list in CONFIG.md (which the LLM could edit via the `update_config` tool).
- **Recommendation:** Add programmatic guardrails in each agent subclass (e.g., BuilderAgent should validate that it only uses file_mutate tools; CronAgent should validate schedule-related constraints).

### 3.3 No structured error propagation

- **Scope:** All agents
- **Description:** Errors are stored as plain text in HEALTH.MD. Cross-agent error pattern detection (`app/agents/doctor/agent.py:176-218`) uses regex on error messages (`_ERROR_EXTRACT_RE`). This is fragile — a typo, rephrasing, or different formatting of the same error breaks pattern matching. There is no error taxonomy, error codes, or structured error types.
- **Recommendation:** Define error types/codes and store structured error records (JSON or SQLite) alongside the text-based HEALTH.MD.

### 3.4 Excessive silent error suppression

Pattern `except Exception: pass` or equivalent appears in ~15+ locations. Key examples:

| Location | Effect of failure |
|----------|-------------------|
| `app/agents/base/__init__.py:172-178` | Event emission silently dropped |
| `app/agents/base/__init__.py:424-430` | Ticket status silently out of sync |
| `app/agents/base/runner.py:162-163` | Notification queue drain silently skipped |
| `app/agents/base/runner.py:249, 272, 293` | DB task history silently lost |
| `app/utils/tools/delegation.py:384-385` | Spawn registry silently stale |
| `app/backend/main.py:170-172` | Notification watcher silently dead |

This makes production debugging extremely difficult — failures are invisible until secondary symptoms appear (tickets not updating, notifications not delivering).

**Recommendation:** Log all suppressed exceptions at WARNING level at minimum. Consider a dead-letter queue pattern for critical failures.

### 3.5 Memory growth unbounded

- **Files:** All agent `MEMORY.MD`, `HEALTH.MD`, `OUTPUT.MD`
- **Description:** MEMORY.MD is pruned at 200 lines → 100 lines. HEALTH.MD is pruned by Doctor (7-day retention). But OUTPUT.MD (subprocess stdout/stderr) grows unboundedly except for log rotation at 512KB, which only halves it. An agent running for weeks will accumulate gigabytes of markdown files. All of these files are read and injected into system prompts on every LLM turn.
- **Recommendation:** Implement size-based truncation for all agent files. Rotate OUTPUT.MD more aggressively. Add a global audit that flags agents with >1MB of markdown files.

### 3.6 Config reloaded every LLM turn

- **File:** `app/agents/base/__init__.py:752`
- **Description:** `_load_config()` reads and parses CONFIG.md + agent-settings.json on every turn of the multi-turn loop. This is intentional for hot-reload support but unnecessary in practice — config rarely changes mid-task.
- **Recommendation:** Cache config for the duration of a task, with an optional file watch to invalidate the cache.

### 3.7 Python 3.12+ requirement

- **File:** `pyproject.toml`
- **Description:** `python = ">=3.12,<4.0"` limits deployment on LTS distributions (Ubuntu 22.04 ships Python 3.10, Debian 12 ships 3.11). The primary 3.12-specific feature appears to be `asyncio.timeout` context manager.
- **Recommendation:** Lower the minimum to 3.10 or 3.11 and use `asyncio.wait_for` as a fallback.

### 3.8 Mixed sync/async file I/O

- **Scope:** BaseAgent (async via aiofiles) vs DoctorAgent/tools (sync via Path methods)
- **Description:** BaseAgent uses `aiofiles` for async file I/O, but DoctorAgent and many tools use synchronous `path.read_text()` / `path.write_text()`. During Doctor health checks that scan all agent directories, synchronous reads can block the asyncio event loop for hundreds of milliseconds.
- **Recommendation:** Use `asyncio.to_thread()` for sync file I/O in async contexts, or standardize on aiofiles throughout.

---

## 4. Code Quality Issues

### 4.1 Duplicate status writing logic

- `AgentRunner._write_status` (`app/agents/base/runner.py:63-98`)
- `MasterAgent._write_status` (`app/agents/master/agent.py:25-61`)

Both implement the same pattern: `tempfile.mkstemp` → `os.write` → `os.close` → `os.replace`. Extract into a shared utility.

### 4.2 Duplicate uvicorn command construction

- `_build_uvicorn_cmd` in `app/utils/tools/server.py:22-27`
- Inline command in `app/cli/main.py:119-120` and `app/cli/main.py:1024-1026`

### 4.3 Wildcard / convenience imports

- `from app.utils import AGENTS_DIR` (used in `keeper/agent.py`, `cron/agent.py`) re-exports from `app.config.settings` via `app/utils/__init__.py`. Creates unnecessary indirection.
- **Recommendation:** Import directly from `app.config import settings` and use `settings.agents_dir`.

### 4.4 Magic numbers scattered without central constants

| Constant | Value | Location |
|----------|-------|----------|
| `_MAX_READ_CHARS` | 18000 | `app/utils/tools/file.py:17` |
| `_MAX_OUTPUT_CHARS` | 10000 | `app/utils/tools/shell.py:10` |
| `TOOL_OUTPUT_CHAR_CAP` | 6000 | `app/utils/tools/__init__.py:21` |
| `_MEMORY_RESPONSE_CHAR_CAP` | 500 | `app/agents/base/__init__.py:77` |
| `_PER_AGENT_WAIT_SECTION_CAP` | 8000 | `app/utils/tools/delegation.py:668` |

**Recommendation:** Create a central `app/config/limits.py` or add these as settings.

### 4.5 Lazy imports to avoid circular dependencies

Many files use `from x import y` inside function bodies to avoid circular imports:
- `from app.backend.services.ticket_service import ...` inside `set_task_status`
- `from app.backend.services.notification_queue import ...` inside `_run_task`
- `from app.utils.db import ...` inside `_run_task`

This is a symptom of unclear module boundaries. The dependency graph needs refactoring (e.g., extract shared interfaces to a `core` module).

### 4.6 No test coverage

- **From CLAUDE.md:** "No tests yet — MVP phase"
- `tests/` directory contains 9 test files but their quality and coverage are unknown.
- `app/backend/tests/` contains 8 test files.

### 4.7 Inconsistent type annotations

- `BaseTool.execute(**params: Any)` loses all type safety on tool parameters.
- `_execute_tool` parameter `tc: Any` should be `ToolCall`.
- Agent file helpers read/write strings but return types are loosely annotated.

---

## 5. Documentation Inconsistencies

| Document | Claim | Actual |
|----------|-------|--------|
| Root CLAUDE.md | "3 adapters" | 8 adapters (anthropic, openai, deepseek, codex, ollama, openrouter, google, lmstudio) |
| Root CLAUDE.md / Tools CLAUDE.md | "20 tools" / "28 tools" | 38 entries in TOOL_REGISTRY |
| Agents CLAUDE.md | Config resolution: CONFIG.md → NOTES.MD → defaults | Code adds agent-settings.json as first priority |
| Backend CLAUDE.md | "restart_agent clears TASK.MD + HEALTH.MD" | Does NOT kill subprocess — agent runs with cleared state |
| Settings CLAUDE.md | `default_model: claude-sonnet-4-6` | Code has `"claude-sonnet-4-6"` which may not exist (Claude Sonnet 4 was announced but model ID may differ) |
| utils/__init__.py docstring | "Re-exports PROJECT_ROOT and AGENTS_DIR" | Only re-exports `PROJECT_ROOT`, `AGENTS_DIR`; not all mentioned names are exported |

---

## 6. Summary — Top 10 Issues to Fix

| # | Severity | Issue | File:Line |
|---|----------|-------|-----------|
| 1 | **Critical** | `shell_exec` runs without confirmation (`RiskTier.AUTO`) | `app/utils/tools/shell.py:25` |
| 2 | **Critical** | HTTP `/task/stream` endpoint bypasses approval gate | `app/backend/routers/tasks.py:142` |
| 3 | **High** | CORS `allow_origins=["*"]` | `app/backend/main.py:381` |
| 4 | **High** | Subprocess agents inherit parent env with API keys | `app/utils/tools/delegation.py:401` |
| 5 | **Bug** | Config parser breaks on colons in values | `app/utils/adapters/base.py:152` |
| 6 | **Bug** | Memory entries lose all content after first newline | `app/agents/base/__init__.py:116` |
| 7 | **Bug** | PID recycling race after server restart | `app/backend/main.py:44` |
| 8 | **Arch** | File-based IPC is fragile and slow | All `TASK.MD` watchers |
| 9 | **Arch** | ~15 instances of silent `except Exception: pass` | See §3.4 |
| 10 | **Quality** | Three duplicate frontmatter parser implementations | base, runner, delegation |

---

## 7. Strengths

Despite the issues above, the project demonstrates strong engineering in several areas:

1. **Rich, functional architecture** — The multi-agent hierarchy with file-based communication is conceptually clean and allows each agent to operate independently.
2. **Comprehensive adapter system** — 8 LLM adapters with a robust `FallbackAdapter` that handles provider failures gracefully.
3. **Well-designed cost governance** — Per-task budgets, per-agent lifetime caps, runaway cost detection (via Doctor), and autonomous daily budgets.
4. **Loop detection** — The 10+ repeated tool call detection with reflection injection is a thoughtful guard against infinite loops.
5. **Cross-process notification queue** — The `NotificationQueue` with `fcntl.flock` is a proper cross-process-safe solution.
6. **Atomic file writes** — Throughout the codebase, file writes use `tempfile.mkstemp` + `os.replace` for atomicity.
7. **Prompt caching** — The Anthropic adapter intelligently applies `cache_control` to system prompts, tool definitions, and message history for significant cost savings.
8. **CLAUDE.md per directory** — Each module has a comprehensive CLAUDE.md that documents architecture, gotchas, and conventions.
9. **Secret scrubbing** — `app/utils/secrets.py` provides pattern-based detection of API keys, passwords, PEM keys, and PII.
10. **Graceful degradation** — The system is designed to survive failures (ticket services, DB writes, notification queues) without crashing the primary agent loop.

---

*Generated by manual code audit of 106 Python files across the yapoc codebase.*
