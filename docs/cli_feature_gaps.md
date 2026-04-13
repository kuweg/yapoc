# CLI Feature Gaps: Claude Code vs YAPOC

Analysis of every gap between Claude Code CLI and YAPOC CLI, with feasibility assessment and implementation design for each.

---

## Gap Categories

- **P0 — Critical**: Missing features that cause real problems (data loss, crashes, bad UX)
- **P1 — High**: Features that significantly improve daily usability
- **P2 — Medium**: Nice-to-have features that round out the experience
- **P3 — Low / Not applicable**: Features that don't fit YAPOC's architecture or are post-MVP

---

## P0 — Critical Gaps

### 1. Context Window Management (auto-compact / /compact) — DONE

**What Claude Code does:** Automatically compresses conversation at ~95% context usage. Manual `/compact` command summarizes history with optional focus instructions. After compaction, CLAUDE.md is re-injected fresh.

**What YAPOC does:** Auto-compacts at ~85% context usage via `app/utils/context.py`. Manual `/compact [focus]` command available. System prompt is re-injected fresh after compaction. CLI shows "Context compacted: X,XXX → Y,YYY tokens".

**Design:**

```
New file: app/utils/context.py

Functions:
  estimate_tokens(messages: list[dict]) -> int
    Rough estimate: len(json.dumps(messages)) / 4
    Used for threshold checks, not billing

  compact_history(
    adapter, model, messages, system_prompt,
    focus: str | None = None
  ) -> list[dict]
    1. Send all messages to LLM with instruction:
       "Summarize this conversation preserving: tool results,
        decisions made, current task state, key facts."
    2. If focus provided, add: "Focus especially on: {focus}"
    3. Return [{"role": "user", "content": "<summary>"}]
    4. Re-inject system prompt (PROMPT.MD) fresh after compaction

Settings (settings.py):
  compact_threshold_pct: int = 85   # auto-compact trigger
  compact_model: str = ""           # empty = use same model

Integration points:
  BaseAgent.run_stream_with_tools() — before each LLM call:
    total = estimate_tokens(messages)
    ctx = context_window_size
    if total / ctx > compact_threshold_pct / 100:
      messages = compact_history(...)
      yield CompactEvent(old_tokens=total, new_tokens=estimate_tokens(messages))

  CLI _repl() — new slash command:
    /compact [focus] — force compaction with optional focus

New stream event:
  @dataclass
  class CompactEvent:
    old_tokens: int
    new_tokens: int

Renderer:
  on_compact(old, new) — print "Context compacted: {old:,} → {new:,} tokens"
```

**Files changed:** `app/utils/context.py` (new), `app/agents/base/__init__.py`, `app/utils/adapters/base.py`, `app/cli/main.py`, `app/cli/renderer.py`, `app/config/settings.py`

---

### 2. Session Persistence — DONE

**What Claude Code does:** All conversations saved as JSONL, resumable via `--continue` / `--resume` / interactive picker. Sessions indexed per project directory.

**What YAPOC does:** Sessions saved as JSONL in `app/agents/master/sessions/`. Resumable via `/continue` (last session), `/resume [id]` (specific session), `/sessions` (list all). `SessionStore` class in `app/cli/sessions.py`.

**Design:**

```
New file: app/cli/sessions.py

Storage: app/agents/master/sessions/
  {session_id}.jsonl — one JSON object per message
  Format: {"role": "user"|"assistant", "content": "...", "ts": "ISO8601",
           "usage": {...} | null, "tools": [...] | null}

Classes:
  @dataclass
  class Session:
    id: str           # UUID
    name: str | None   # user-assigned name
    created_at: str
    updated_at: str
    message_count: int
    model: str

  class SessionStore:
    def __init__(self, sessions_dir: Path)
    def create() -> Session
    def list_sessions(limit=20) -> list[Session]
    def load(session_id: str) -> list[Message]
    def append(session_id: str, message: Message, usage: UsageStats | None)
    def get_latest() -> Session | None
    def rename(session_id: str, name: str)
    def delete(session_id: str)

CLI integration:
  _repl():
    store = SessionStore(...)
    session = store.create()
    # After each _send_to_agent, append both user + assistant messages
    # On startup, no auto-resume (explicit only)

  New slash commands:
    /sessions          — list recent sessions
    /resume [id|name]  — resume a previous session (load history)
    /continue          — resume most recent session
    /rename [name]     — name current session
    /save              — force flush (auto-saves by default)

  CLI flags:
    yapoc chat --continue    — resume last session
    yapoc chat --resume ID   — resume specific session
```

**Files changed:** `app/cli/sessions.py` (new), `app/cli/main.py`, `app/config/settings.py`

---

### 3. File Write/Edit Tools — DONE

**What Claude Code does:** `Write` (create/overwrite files), `Edit` (surgical string replacement with uniqueness check). Both require permission on first use.

**What YAPOC does:** `file_write` (create/overwrite with atomic write + sandbox check), `file_edit` (unique string replacement), `file_delete` (with sandbox check + base dir protection). All use `RiskTier.CONFIRM`. Implemented in `app/utils/tools/file.py`.

**Design:**

```
New file: app/utils/tools/file_write.py

class FileWriteTool(BaseTool):
  name = "file_write"
  risk_tier = RiskTier.CONFIRM
  input_schema:
    path: str          # relative to project root
    content: str       # full file content
    create_dirs: bool  # create parent dirs (default: true)
  execute():
    1. Sandbox check (no .. escapes, stays within project root)
    2. Atomic write (write to .tmp, rename)
    3. Return "Wrote {len} bytes to {path}"

class FileEditTool(BaseTool):
  name = "file_edit"
  risk_tier = RiskTier.CONFIRM
  input_schema:
    path: str
    old_string: str     # text to find (must be unique in file)
    new_string: str     # replacement text
    replace_all: bool   # default: false
  execute():
    1. Read file
    2. Check old_string exists (and is unique if not replace_all)
    3. Replace
    4. Atomic write
    5. Return "Edited {path}: replaced {n} occurrence(s)"

class FileDeleteTool(BaseTool):
  name = "file_delete"
  risk_tier = RiskTier.CONFIRM
  input_schema:
    path: str
  execute():
    1. Sandbox check
    2. Refuse to delete agent base directories
    3. os.unlink()
    4. Return "Deleted {path}"

Register in __init__.py:
  "file_write": FileWriteTool
  "file_edit": FileEditTool
  "file_delete": FileDeleteTool
```

**Files changed:** `app/utils/tools/file_write.py` (new), `app/utils/tools/__init__.py`, master `CONFIG.md` (add tools)

---

## P1 — High Priority Gaps

### 4. Cost Tracking — DONE

**What Claude Code does:** Shows cumulative cost in USD per session. Available via `/cost` command and in status line.

**What YAPOC does:** `calc_cost()` in `renderer.py` with pricing for 6 models. Status line shows `$X.XXXX` per turn and `($X.XXXX)` session total. `/cost` command shows session breakdown.

**Design:**

```
Add to app/cli/renderer.py:

# Pricing per 1M tokens (input/output) — update as prices change
_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-6":              (15.0, 75.0),
    "claude-sonnet-4-6":            (3.0, 15.0),
    "claude-haiku-4-5-20251001":    (0.80, 4.0),
}

def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = _PRICING.get(model, (3.0, 15.0))
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000

In print_status_line():
  After session totals, append: "  $X.XXXX"

In _repl():
  Track _session_cost as running total
  /cost command prints breakdown per model

Add to settings.py:
  show_cost: bool = True
```

**Files changed:** `app/cli/renderer.py`, `app/cli/main.py`, `app/config/settings.py`

---

### 5. Tab Completion for Slash Commands — DONE

**What Claude Code does:** `/` opens a command picker with filtering.

**What YAPOC does:** `SlashCompleter` class provides tab completion for 18 slash commands with descriptions. Activated on `/` prefix, `complete_while_typing=False` (Tab only).

**Design:**

```
In app/cli/main.py, add a prompt_toolkit Completer:

from prompt_toolkit.completion import Completer, Completion

_SLASH_COMMANDS = [
    ("/help", "Show help"),
    ("/exit", "Quit"),
    ("/clear", "Clear history"),
    ("/model", "Show model"),
    ("/start", "Start server"),
    ("/stop", "Stop server"),
    ("/restart", "Restart server"),
    ("/status", "Server status"),
    ("/ping", "Ping server"),
    ("/agents", "List agents"),
    ("/compact", "Compact context"),
    ("/sessions", "List sessions"),
    ("/resume", "Resume session"),
    ("/continue", "Resume last session"),
    ("/cost", "Show cost"),
]

class SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith("/"):
            for cmd, desc in _SLASH_COMMANDS:
                if cmd.startswith(text):
                    yield Completion(cmd, start_position=-len(text),
                                     display_meta=desc)

session = PromptSession(completer=SlashCompleter(), ...)
```

**Files changed:** `app/cli/main.py`

---

### 6. `@` File Mentions — DONE

**What Claude Code does:** Type `@` to fuzzy-search files. Selected file path is inserted and its content is automatically included in context.

**What YAPOC does:** `FileCompleter` class provides fuzzy file search on `@` prefix (cap 30 results). `_expand_file_mentions()` replaces `@path` with inline file content in code fences before sending to agent.

**Design:**

```
In app/cli/main.py:

class FileCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        # Find the last @ in text
        at_idx = text.rfind("@")
        if at_idx == -1:
            return
        partial = text[at_idx + 1:]
        # Walk project files matching partial (fuzzy)
        for path in _glob_project_files(partial):
            yield Completion(
                f"@{path}",
                start_position=-(len(partial) + 1),
                display=path,
            )

from prompt_toolkit.completion import merge_completers
session = PromptSession(
    completer=merge_completers([SlashCompleter(), FileCompleter()]),
    ...
)

In _send_to_agent():
  Before sending message, scan for @path patterns:
    for match in re.finditer(r"@([\w/.\\-]+)", text):
        path = match.group(1)
        content = read_file(path)  # sandboxed
        text += f"\n\n--- Content of {path} ---\n{content}\n---"
```

**Files changed:** `app/cli/main.py`

---

### 7. `!` Bash Mode — DONE

**What Claude Code does:** Prefix with `!` to run a shell command directly. Output added to context.

**What YAPOC does:** `!command` runs via `subprocess.run(shell=True, timeout=30)`. Output printed dimmed. Does not add to agent context (user-only convenience).

**Design:**

```
In _repl(), before slash command check:

if text.startswith("!"):
    cmd = text[1:].strip()
    if cmd:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=30, cwd=str(settings.project_root)
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR: {result.stderr}"
        output += f"\nExit code: {result.returncode}"
        console.print(f"[dim]{output}[/dim]")
        # Optionally add to history so agent sees it
    continue
```

**Files changed:** `app/cli/main.py`

---

### 8. Checkpoints + Rewind

**What Claude Code does:** Every user prompt creates a file-state checkpoint. `/rewind` lets you restore code, conversation, or both.

**What YAPOC does:** Nothing. No way to undo agent file changes.

**Why it matters:** When the agent writes/edits files (especially with new file_write/file_edit tools), mistakes are permanent. Users need an undo mechanism.

**Design:**

```
New file: app/cli/checkpoints.py

Storage: app/agents/master/sessions/{session_id}/checkpoints/
  {turn_number}.json — snapshot of changed files

class CheckpointStore:
    def __init__(self, session_dir: Path)

    def save(self, turn: int, tool_results: list[ToolDone]):
        # For each file_write/file_edit/file_delete tool:
        #   Save the BEFORE state of the affected file
        # Write to {turn}.json: [{"path": ..., "before": ..., "action": ...}]

    def rewind_to(self, turn: int):
        # Restore all files from checkpoints after `turn`
        # Walk backwards, applying "before" states

    def list_checkpoints(self) -> list[dict]:
        # Return [{turn, timestamp, files_changed: [...]}]

Integration:
  In _send_to_agent():
    After tool execution, before response:
      checkpoint_store.save(turn_number, renderer.completed_tools)

  New slash command:
    /rewind [turn]  — show checkpoint list or rewind to specific turn
    /undo           — rewind last turn
```

**Files changed:** `app/cli/checkpoints.py` (new), `app/cli/main.py`

---

### 9. Per-Tool Permission Rules

**What Claude Code does:** Granular rules with glob patterns: `Bash(npm run *)`, `Read(./.env)`, `Edit(/src/**/*.ts)`. Stored in settings.json.

**What YAPOC does:** Only `RiskTier.AUTO` vs `RiskTier.CONFIRM`. No per-command or per-path rules.

**Design:**

```
Add to app/config/settings.py:

permission_rules: dict[str, list[str]] = {
    "allow": [],   # ["shell_exec(npm run *)", "file_read(app/*)"]
    "deny": [],    # ["shell_exec(rm *)", "file_write(.env)"]
}

New file: app/utils/permissions.py

def check_permission(
    tool_name: str,
    tool_input: dict,
    rules: dict[str, list[str]],
    risk_tier: RiskTier,
) -> Literal["allow", "deny", "ask"]:
    # 1. Check deny rules first (highest priority)
    # 2. Check allow rules
    # 3. Fall back to risk tier behavior
    # Pattern matching: fnmatch on tool_name(arg_preview)

Integration:
  BaseAgent._execute_tool() — call check_permission() before approval gate
  If "allow" → skip gate
  If "deny" → return denial immediately
  If "ask" → proceed to approval gate as normal
```

**Files changed:** `app/utils/permissions.py` (new), `app/agents/base/__init__.py`, `app/config/settings.py`

---

## P2 — Medium Priority Gaps

### 10. /diff Command — DONE

**What Claude Code does:** Interactive diff viewer for uncommitted changes and per-turn diffs.

**What YAPOC does:** `/diff` runs `git diff` and renders via `rich.syntax.Syntax` with "monokai" theme. Shows "Not in a git repository" if no `.git` present.

---

### 11. /copy and /export — DONE

**What Claude Code does:** `/copy` copies last response to clipboard. `/export` saves conversation as text.

**What YAPOC does:** `/copy` uses `pbcopy` (macOS) or `xclip` (Linux) to copy last assistant response. `/export [file]` writes conversation history to a text file (default: `yapoc_export_{timestamp}.txt`).

---

### 12. Hooks System

**What Claude Code does:** Shell commands that fire on lifecycle events (PreToolUse, PostToolUse, SessionStart, Stop). Can block, approve, or transform tool calls.

**What YAPOC does:** Nothing.

**Design:**

```
New file: app/utils/hooks.py

Lifecycle events:
  SessionStart     — REPL starts
  PreToolUse       — before tool execution (can block with exit 2)
  PostToolUse      — after tool execution
  TurnComplete     — after LLM response

Config (settings.py):
  hooks: dict[str, list[HookConfig]] = {}

@dataclass
class HookConfig:
    event: str
    command: str       # shell command to run
    match_tool: str | None = None  # filter by tool name

class HookRunner:
    def __init__(self, hooks: dict[str, list[HookConfig]])
    async def fire(self, event: str, context: dict) -> HookResult:
        # Run matching hooks, pass context as JSON on stdin
        # Check exit code: 0=pass, 2=block, other=error
        # Return HookResult(blocked=bool, output=str)

Integration:
  BaseAgent._execute_tool():
    result = await hooks.fire("PreToolUse", {"tool": name, "input": inp})
    if result.blocked: return "Blocked by hook: {result.output}"
    ... execute tool ...
    await hooks.fire("PostToolUse", {"tool": name, "result": ...})
```

**Files changed:** `app/utils/hooks.py` (new), `app/agents/base/__init__.py`, `app/config/settings.py`

---

### 13. Task List Display

**What Claude Code does:** Visual task list (Ctrl+T) showing multi-step task progress.

**Design:**

```
Agent-native approach — YAPOC already has TASK.MD per agent.

New slash command:
  /tasks — read TASK.MD from all agents, display as table:
    | Agent    | Status  | Task (first 60 chars)           |
    |----------|---------|----------------------------------|
    | master   | running | Change color palette to cyan...  |
    | planning | idle    | -                                |
    | doctor   | done    | Health check completed           |

Implementation:
  Walk settings.agents_dir, read each agent's TASK.MD
  Parse YAML frontmatter for status
  Display as Rich table
```

**Files changed:** `app/cli/main.py`

---

### 14. Multiline Input — DONE (partial)

**What Claude Code does:** Shift+Enter works natively in iTerm2/WezTerm/Ghostty/Kitty.

**What YAPOC does:** `Ctrl+J` inserts a newline (universal). `Esc+Enter` also works (prompt_toolkit default). Shift+Enter (`s-enter`) was removed because prompt_toolkit doesn't support it as a key name — it causes a crash.

---

### 15. Custom Skills / Slash Commands

**What Claude Code does:** Skill files (`.claude/skills/<name>/SKILL.md`) define custom commands with argument substitution and tool access control.

**Design:**

```
Directory: app/agents/master/skills/
  <name>.md — skill definition

Format:
  ---
  name: deploy
  description: Deploy to staging
  argument-hint: [environment]
  ---
  Run the deployment script for $ARGUMENTS environment.
  If no environment specified, use "staging".

Loading:
  On startup, scan skills/ directory
  Register as slash commands: /deploy, /skill-name
  When invoked: substitute $ARGUMENTS, send as message to agent

New slash command:
  /skills — list available skills
```

**Files changed:** `app/cli/main.py`, `app/cli/skills.py` (new)

---

## P3 — Low Priority / Not Applicable

### 16. Vim Mode

**What Claude Code does:** Full vim keybindings in the input (normal/insert mode, motions, text objects).

**Why low priority:** prompt_toolkit has built-in vi mode (`vi_mode=True`), but it changes the entire editing experience. Most users don't need it.

**If added:** Single line: `PromptSession(vi_mode=True)`. Could toggle with `/vim` command.

---

### 17. Prompt Suggestions (Ghost Text)

**What Claude Code does:** After each response, shows a grayed-out suggestion derived from context. Tab to accept.

**Why low priority:** Requires a background LLM call after each turn (extra cost/latency). The suggestion quality depends heavily on conversation context. Complex to implement well.

**If added:** After each response, fire a background Haiku call with: "Suggest a short follow-up prompt the user might want to send next." Display as prompt_toolkit auto-suggestion.

---

### 18. Session Forking

**What Claude Code does:** `/fork [name]` creates a branch of the current conversation.

**Why low priority:** Depends on session persistence (gap #2) being implemented first. Useful for exploring alternative approaches but rarely needed in daily use.

**If added:** Copy current session JSONL to a new file, continue from there.

---

### 19. IDE Integration

**What Claude Code does:** VS Code and JetBrains extensions with inline diffs, `@`-mentions with line ranges, conversation history UI.

**Why not applicable:** YAPOC is a fundamentally different architecture — it has its own FastAPI backend, multi-agent hierarchy, and file-based communication. IDE integration would mean building a VS Code extension that talks to YAPOC's API, which is a separate project entirely.

**Alternative:** YAPOC's backend API already exposes endpoints (`POST /task`, `GET /agents`, etc.) that a future IDE extension could consume. The API is the integration point, not the CLI.

---

### 20. Plugins

**What Claude Code does:** Installable bundles of skills, subagents, MCP servers, hooks.

**Why not applicable (yet):** YAPOC's extension model is the agent hierarchy itself — Builder creates new agents, Keeper configures them. Plugins would be redundant with the agent creation system. Once Builder is implemented, "installing a plugin" = "asking Builder to create a new agent with specific capabilities."

---

### 21. MCP Servers

**What Claude Code does:** Connects to any MCP server (stdio/HTTP/SSE). Dynamic tool loading, OAuth support.

**Why deferred:** MCP is a protocol for extending tool capabilities. YAPOC already has a tool registry that agents access through CONFIG.md. Adding MCP support would mean:
1. New MCP client in `app/utils/mcp.py`
2. Auto-registering MCP tools into the tool registry
3. Permission handling for external tools

This is feasible but large. The tool registry would need to support dynamic tools (currently static).

---

### 22. Output Styles

**What Claude Code does:** Configurable response formatting (Default, Explanatory, Learning, custom).

**Why low priority:** YAPOC already has smart markdown detection + plain text rendering. Custom styles would mean adding system prompt suffixes per style, which is trivial but low impact.

---

### 23. Remote / Teleport

**What Claude Code does:** `--remote` creates web sessions, `--teleport` resumes them locally, `/desktop` opens in desktop app.

**Why not applicable:** YAPOC doesn't have a web UI or desktop app. Its architecture is CLI + backend API. Remote capabilities would be a different product.

---

## Implementation Order

Based on impact vs effort:

| Phase | Features | Status |
|-------|----------|--------|
| **Phase 1** | Context management (#1), File write/edit tools (#3), Cost tracking (#4) | **DONE** |
| **Phase 2** | Session persistence (#2), Tab completion (#5), `@` mentions (#6), `!` bash (#7), Multiline (#14) | **DONE** |
| **Phase 3 (partial)** | /diff (#10), /copy + /export (#11) | **DONE** |
| **Phase 3 (remaining)** | Checkpoints (#8), Permission rules (#9) | Not started |
| **Phase 4** | Hooks (#12), Task display (#13), Custom skills (#15) | Not started |
| **Deferred** | Vim mode, prompt suggestions, session forking, MCP, IDE, plugins | Future |
