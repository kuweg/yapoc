"""TurnRenderer — Rich Live display for agent response streaming.

Manages a state machine that shows spinners, streaming text, and tool status
inside a single Rich Live context, producing a clean Claude Code-like CLI.

Color palette: Yellow
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from app.utils.adapters import CompactEvent, UsageStats

def _read_agent_status(agent_name: str) -> dict | None:
    """Read STATUS.json for a sub-agent (sync, tiny file, OS-cached)."""
    from app.config import settings

    path = settings.agents_dir / agent_name / "STATUS.json"
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


# ── Shared Agent Poll State ──────────────────────────────────────────────────

class AgentPollState:
    """Thread-safe shared state for agent polling.

    Used by both TurnRenderer (during Live display) and the prompt_toolkit
    bottom toolbar (between turns). A background asyncio task calls poll_once()
    periodically; the toolbar callback reads .agents under a lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.agents: dict[str, dict] = {}
        self._done_at: dict[str, float] = {}

    def poll_once(self) -> None:
        """Read agents_dir/*/STATUS.json, filter by 5min window + 3s grace."""
        from app.config import settings

        now = time.monotonic()
        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc.timestamp() - 300  # 5 minutes

        new_agents: dict[str, dict] = {}
        new_done_at: dict[str, float] = dict(self._done_at)
        seen: set[str] = set()

        for status_path in settings.agents_dir.glob("*/STATUS.json"):
            agent_name = status_path.parent.name
            try:
                data = json.loads(status_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            updated = data.get("updated_at", "")
            if updated:
                try:
                    ts = datetime.fromisoformat(updated.replace("Z", "+00:00")).timestamp()
                except (ValueError, TypeError):
                    ts = 0
                if ts < cutoff:
                    continue

            seen.add(agent_name)
            state = data.get("state", "unknown")

            if state == "terminated":
                if agent_name not in new_done_at:
                    new_done_at[agent_name] = now
                elif now - new_done_at[agent_name] > 3:
                    new_done_at.pop(agent_name, None)
                    continue
            else:
                new_done_at.pop(agent_name, None)

            new_agents[agent_name] = data

        # Remove agents whose STATUS.json disappeared
        for name in list(new_done_at):
            if name not in seen:
                new_done_at.pop(name, None)

        with self._lock:
            self.agents = new_agents
            self._done_at = new_done_at

    def get_snapshot(self) -> dict[str, dict]:
        """Return a thread-safe deep copy of current agent data."""
        with self._lock:
            return {k: dict(v) for k, v in self.agents.items()}

    async def run_loop(self, interval: float = 2.0) -> None:
        """Background asyncio task that calls poll_once() periodically."""
        while True:
            try:
                self.poll_once()
            except Exception:
                pass  # Never crash the poll loop
            await asyncio.sleep(interval)


def _make_toolbar(poll_state: AgentPollState):
    """Return a callable for prompt_toolkit's bottom_toolbar.

    Shows compact one-line agent status. Returns empty string when no agents
    are active (hides toolbar). Called synchronously from prompt_toolkit's
    rendering thread — reads from poll_state under its lock.
    """
    _STATE_LABELS = {
        "running": "running",
        "spawning": "spawning",
        "idle": "idle",
        "terminated": "done",
    }

    def _toolbar():
        snapshot = poll_state.get_snapshot()
        # Filter out terminated agents for display
        active = {
            name: data for name, data in snapshot.items()
            if data.get("state") != "terminated"
        }
        if not active:
            return ""

        parts = []
        for name, data in sorted(active.items()):
            state = _STATE_LABELS.get(data.get("state", ""), "?")
            summary = (data.get("task_summary", "") or "")[:40]
            if summary:
                parts.append(f"{name}:{state}  {summary}")
            else:
                parts.append(f"{name}:{state}")

        return " Agents: " + "  |  ".join(parts)

    return _toolbar


# ── Color Palette ─────────────────────────────────────────────────────────────
COLOR_PRIMARY   = "yellow"            # main accent
COLOR_SUCCESS   = "bright_yellow"      # tool success
COLOR_ERROR     = "red"               # tool error / high usage
COLOR_THINKING  = "yellow"             # spinner
COLOR_TOOL_RUN  = "bright_yellow"      # running tool spinner
COLOR_WARN      = "yellow"            # medium usage warning
COLOR_OK        = "yellow"              # low usage / ok state
COLOR_TOKENS_IN = "yellow"              # input token count
COLOR_TOKENS_OUT= "bright_yellow"      # output token count
COLOR_MODEL     = "bold dim"        # model name (unchanged)
COLOR_SPEED     = "yellow dim"          # tokens/s
COLOR_WRITING   = "bright_yellow"      # writing/streaming indicator
# ──────────────────────────────────────────────────────────────────────────────

# Paragraph indent applied to non-markdown plain text blocks
_PARA_INDENT = "  "   # 2-space soft indent for paragraph lines


def _format_tool_input(inp: dict) -> str:
    """Format tool input dict for inline display."""
    if not inp:
        return ""
    parts = [f"{k}={v!r}" for k, v in inp.items()]
    preview = ", ".join(parts)
    if len(preview) > 80:
        preview = preview[:77] + "..."
    return preview


# Tool name → spinner label mapping
_TOOL_STATUS: dict[str, str] = {
    "file_read": "Reading…",
    "file_write": "Writing file…",
    "file_edit": "Editing file…",
    "file_delete": "Deleting file…",
    "file_list": "Reading…",
    "read_agent_logs": "Reading…",
    "notes_read": "Reading…",
    "shell_exec": "Running command…",
    "web_search": "Searching…",
    "memory_append": "Writing…",
    "notes_write": "Writing…",
    "health_log": "Writing…",
    "server_restart": "Restarting server…",
    "process_restart": "Restarting…",
    "spawn_agent": "Spawning agent…",
    "ping_agent": "Pinging agent…",
    "kill_agent": "Stopping agent…",
    "check_task_status": "Checking task…",
    "read_task_result": "Reading result…",
    "create_agent": "Creating agent…",
    "delete_agent": "Deleting agent…",
    "wait_for_agent": "Waiting for agent…",
    "update_config": "Updating config…",
}


def _render_plain_text(raw: str) -> list[Text]:
    """
    Convert a plain-text agent response into a list of Rich Text objects,
    preserving:
      - Blank lines between paragraphs (rendered as empty Text lines)
      - Tab characters at the start of a line → 4-space indent
      - Leading spaces preserved as-is
      - Each non-empty paragraph line gets a soft 2-space indent
    """
    lines = raw.split("\n")
    rendered: list[Text] = []
    for line in lines:
        # Expand leading tabs to 4 spaces each
        expanded = re.sub(r"^\t+", lambda m: "    " * len(m.group()), line)
        if expanded.strip() == "":
            # Blank / paragraph-separator line
            rendered.append(Text(""))
        else:
            # Preserve any existing leading whitespace; add soft indent on top
            rendered.append(Text(_PARA_INDENT + expanded))
    return rendered


_DELEGATION_TOOLS = {"wait_for_agent", "read_task_result"}

_MAX_TOOL_LINES = 12  # max visible collapsed groups before summarizing


@dataclass
class _CompletedTool:
    name: str
    result: str
    is_error: bool
    is_delegation: bool = False
    agent_name: str = ""


def _collapse_tools(tools: list[_CompletedTool]) -> list[tuple[_CompletedTool, int]]:
    """Group consecutive tool calls with the same name into (representative, count) pairs."""
    if not tools:
        return []
    groups: list[tuple[_CompletedTool, int]] = []
    current = tools[0]
    count = 1
    for ct in tools[1:]:
        if ct.name == current.name:
            count += 1
            current = ct  # keep the latest as representative
        else:
            groups.append((current, count))
            current = ct
            count = 1
    groups.append((current, count))
    return groups


class TurnRenderer:
    """Rich-renderable that drives a Live display through thinking -> streaming -> tool phases."""

    def __init__(self, console: Console, poll_state: AgentPollState | None = None) -> None:
        self._console = console
        self._poll_state = poll_state
        self._state: str = "thinking"  # thinking | streaming | tool_running
        self._text_buf: list[str] = []
        self._completed_tools: list[_CompletedTool] = []
        self._current_tool: tuple[str, str] | None = None  # (name, args_preview)
        self._current_tool_input: dict = {}
        self._usage: UsageStats | None = None
        self._compact_notice: str | None = None
        self._live: Live | None = None
        self._t0 = time.monotonic()
        # Agent panel state (used only when no shared poll_state)
        self._watched_agents: dict[str, dict] = {}
        self._agent_done_at: dict[str, float] = {}
        self._poll_task: asyncio.Task | None = None

    # -- Async context manager -------------------------------------------------

    async def __aenter__(self) -> TurnRenderer:
        self._state = "thinking"
        self._text_buf.clear()
        self._completed_tools.clear()
        self._current_tool = None
        self._usage = None
        self._compact_notice = None
        self._t0 = time.monotonic()
        self._watched_agents.clear()
        self._agent_done_at.clear()
        self._live = Live(
            self._build(),
            console=self._console,
            refresh_per_second=12,
            transient=True,
        )
        self._live.start()
        # Only start own poll task when no shared AgentPollState is provided
        if self._poll_state is None:
            self._poll_task = asyncio.create_task(self._poll_agents())
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        if self._live:
            self._live.stop()

    # -- Event handlers --------------------------------------------------------

    def on_text_delta(self, text: str) -> None:
        self._state = "streaming"
        self._text_buf.append(text)
        self._refresh()

    def on_tool_start(self, name: str, inp: dict) -> None:
        self._state = "tool_running"
        self._current_tool_input = inp
        args_preview = _format_tool_input(inp)
        self._current_tool = (name, args_preview)
        self._refresh()

    def on_tool_done(self, name: str, result: str, is_error: bool = False) -> None:
        is_delegation = name in _DELEGATION_TOOLS
        agent_name = self._current_tool_input.get("agent_name", "")

        if is_delegation:
            # Store full result for delegation tools — no truncation
            stored = result
        else:
            stored = result[:120].replace("\n", " ")
            if len(result) > 120:
                stored += "..."

        self._completed_tools.append(_CompletedTool(
            name=name, result=stored, is_error=is_error,
            is_delegation=is_delegation, agent_name=agent_name,
        ))
        self._current_tool = None
        self._current_tool_input = {}
        self._state = "thinking"
        self._refresh()

    def on_usage(self, stats: UsageStats) -> None:
        self._usage = stats
        self._refresh()

    def on_compact(self, event: CompactEvent) -> None:
        self._compact_notice = (
            f"Context compacted ({event.reason}): "
            f"{event.tokens_before:,} \u2192 {event.tokens_after:,} tokens"
        )
        self._refresh()

    # -- Public getters --------------------------------------------------------

    def get_response(self) -> str:
        return "".join(self._text_buf)

    @property
    def usage(self) -> UsageStats | None:
        return self._usage

    @property
    def completed_tools(self) -> list[_CompletedTool]:
        return self._completed_tools

    # -- Agent polling ---------------------------------------------------------

    async def _poll_agents(self) -> None:
        """Poll agents_dir/*/STATUS.json every 2s to discover active agents."""
        from app.config import settings

        while True:
            try:
                now = time.monotonic()
                now_utc = datetime.now(timezone.utc)
                cutoff = now_utc.timestamp() - 300  # 5 minutes

                seen: set[str] = set()
                for status_path in settings.agents_dir.glob("*/STATUS.json"):
                    agent_name = status_path.parent.name
                    try:
                        data = json.loads(status_path.read_text())
                    except (json.JSONDecodeError, OSError):
                        continue

                    # Filter to recently active agents
                    updated = data.get("updated_at", "")
                    if updated:
                        try:
                            ts = datetime.fromisoformat(updated.replace("Z", "+00:00")).timestamp()
                        except (ValueError, TypeError):
                            ts = 0
                        if ts < cutoff:
                            continue

                    seen.add(agent_name)
                    state = data.get("state", "unknown")

                    if state == "terminated":
                        # Track termination for 3s grace period
                        if agent_name not in self._agent_done_at:
                            self._agent_done_at[agent_name] = now
                        elif now - self._agent_done_at[agent_name] > 3:
                            self._watched_agents.pop(agent_name, None)
                            continue
                    else:
                        self._agent_done_at.pop(agent_name, None)

                    self._watched_agents[agent_name] = data

                # Remove agents whose STATUS.json disappeared
                for name in list(self._watched_agents):
                    if name not in seen:
                        self._watched_agents.pop(name, None)
                        self._agent_done_at.pop(name, None)

                self._refresh()
            except Exception:
                pass  # Never crash the poll loop

            await asyncio.sleep(2)

    def _build_agent_panel(self) -> Panel | None:
        """Build a Rich Panel showing active agents, or None if <=1 active."""
        # Use shared poll state when available, otherwise own watched_agents
        if self._poll_state is not None:
            watched = self._poll_state.get_snapshot()
        else:
            watched = self._watched_agents

        # Filter to non-terminated agents for the "active" count
        active = {
            name: data for name, data in watched.items()
            if data.get("state") != "terminated"
        }
        if len(active) <= 1:
            return None

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("name", style="bold", width=14, no_wrap=True)
        table.add_column("state", width=12, no_wrap=True)
        table.add_column("summary", style="dim", no_wrap=True, overflow="ellipsis")

        state_styles = {
            "running": "yellow",
            "spawning": "bright_yellow",
            "idle": "dim",
            "terminated": "dim",
        }

        items = sorted(watched.items())
        shown = items[:8]
        overflow = len(items) - 8

        for name, data in shown:
            state = data.get("state", "unknown")
            summary = data.get("task_summary", "") or ""
            style = state_styles.get(state, "dim")
            table.add_row(
                Text(name, style="bold"),
                Text(state, style=style),
                Text(summary[:60], style="dim"),
            )

        if overflow > 0:
            table.add_row(Text(""), Text(""), Text(f"(+{overflow} more)", style="dim"))

        return Panel(
            table,
            title="Active Agents",
            border_style="dim yellow",
            expand=True,
            padding=(0, 1),
        )

    # -- Rendering -------------------------------------------------------------

    def _refresh(self) -> None:
        if self._live:
            self._live.update(self._build())

    def _build(self) -> RenderableType:
        parts: list[RenderableType] = []

        # Compact notice
        if self._compact_notice:
            parts.append(Text(f"  {self._compact_notice}", style="dim"))
            parts.append(Text(""))

        # Completed tools — collapse consecutive runs of the same tool
        groups = _collapse_tools(self._completed_tools)
        # Cap visible groups: show last MAX_TOOL_LINES, summarize the rest
        if len(groups) > _MAX_TOOL_LINES:
            hidden = len(groups) - _MAX_TOOL_LINES
            hidden_count = sum(g[1] for g in groups[:hidden])
            parts.append(Text(f"  … {hidden_count} earlier tools", style="dim"))
            groups = groups[hidden:]
        for ct, count in groups:
            if ct.is_error:
                suffix = f" × {count}" if count > 1 else ""
                parts.append(Text(f"  ✗ {ct.name}{suffix} → {ct.result}", style=COLOR_ERROR))
            elif ct.is_delegation:
                label = "[result ready]"
                suffix = f" × {count}" if count > 1 else ""
                parts.append(Text(f"  ✓ {ct.name}{suffix} → {label}", style=COLOR_SUCCESS))
            else:
                suffix = f" × {count}" if count > 1 else ""
                parts.append(Text(f"  ✓ {ct.name}{suffix} → {ct.result}", style=COLOR_SUCCESS))

        # Blank line between tool list and streaming text
        text = "".join(self._text_buf)
        if text and self._completed_tools:
            parts.append(Text(""))

        # Streaming text — rendered with paragraph/tab support
        if text:
            parts.extend(_render_plain_text(text))

        # Agent panel (visible only when 2+ agents are active)
        agent_panel = self._build_agent_panel()
        if agent_panel is not None:
            parts.append(Text(""))
            parts.append(agent_panel)

        # Spinners with contextual status labels
        if self._state == "thinking" and not text and not self._completed_tools:
            parts.append(Spinner("dots", text=" Thinking…", style=COLOR_THINKING))
        elif self._state == "tool_running" and self._current_tool:
            name, _args = self._current_tool
            status = _TOOL_STATUS.get(name, f"Running {name}…")
            if name == "wait_for_agent":
                agent_name = self._current_tool_input.get("agent_name", "")
                if agent_name:
                    sub = _read_agent_status(agent_name)
                    if sub:
                        state = sub.get("state", "?")
                        summary = sub.get("task_summary", "")[:50]
                        if summary:
                            status = f"Waiting for {agent_name} [{state}]: {summary}…"
                        else:
                            status = f"Waiting for {agent_name} [{state}]"
            parts.append(Text(""))
            parts.append(Spinner("dots", text=f" {status}", style=COLOR_TOOL_RUN))
        elif self._state == "thinking" and self._completed_tools:
            parts.append(Text(""))
            parts.append(Spinner("dots", text=" Thinking…", style=COLOR_THINKING))
        elif self._state == "streaming":
            parts.append(Text(""))
            parts.append(Spinner("dots", text=" Writing…", style=COLOR_WRITING))

        return Group(*parts) if parts else Text("")


# -- Cost tracking -------------------------------------------------------------

from app.utils.adapters.models import ALL_PRICING

# Model name → (input_cost_per_1M_tokens, output_cost_per_1M_tokens)
_PRICING: dict[str, tuple[float, float]] = ALL_PRICING


def calc_cost(
    model: str, input_tokens: int, output_tokens: int,
    cache_creation_tokens: int = 0, cache_read_tokens: int = 0,
) -> float:
    """Calculate USD cost for a turn given model and token counts.

    Anthropic cache pricing: cache writes cost 1.25x input rate,
    cache reads cost 0.1x input rate. Non-cached input is at base rate.
    """
    pricing = _PRICING.get(model)
    if not pricing:
        return 0.0
    in_rate, out_rate = pricing
    # Subtract cached tokens from input (they're charged separately)
    base_input = max(0, input_tokens - cache_creation_tokens - cache_read_tokens)
    return (
        base_input * in_rate
        + cache_creation_tokens * in_rate * 1.25
        + cache_read_tokens * in_rate * 0.1
        + output_tokens * out_rate
    ) / 1_000_000


# -- Status line ---------------------------------------------------------------

def _make_bar(pct: float, width: int = 20) -> str:
    filled = round(pct / 100 * width)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def _pct_color(pct: float) -> str:
    if pct >= 80:
        return COLOR_ERROR   # red
    if pct >= 60:
        return COLOR_WARN    # yellow
    return COLOR_OK          # cyan


def print_status_line(
    console: Console,
    model: str,
    usage: UsageStats | None,
    *,
    session_input: int = 0,
    session_output: int = 0,
    turn_cost: float = 0.0,
    session_cost: float = 0.0,
) -> None:
    """Print a Claude Code-style status line after a response."""
    if not usage:
        return

    ctx = usage.context_window
    total = usage.input_tokens + usage.output_tokens
    pct = (total / ctx * 100) if ctx else 0
    bar = _make_bar(pct)
    color = _pct_color(pct)

    t = Text()
    t.append(f"  {model}", style=COLOR_MODEL)
    t.append(f"  {usage.tokens_per_second:.1f} t/s", style=COLOR_SPEED)

    # Cost display
    if turn_cost > 0:
        t.append(f"  ${turn_cost:.4f}", style="yellow dim")
    if session_cost > turn_cost:
        t.append(f" (${session_cost:.4f})", style="dim")

    t.append("  │  ", style="dim")
    t.append(f"↑{usage.input_tokens:,}", style=f"{COLOR_TOKENS_IN} dim")
    # Show cache stats if any
    if usage.cache_read_tokens > 0:
        t.append(f" (cached:{usage.cache_read_tokens:,})", style="green dim")
    t.append("  ", style="dim")
    t.append(f"↓{usage.output_tokens:,}", style=f"{COLOR_TOKENS_OUT} dim")
    t.append("  │  ", style="dim")
    t.append(f"{total:,}", style="dim")
    t.append(f" / {ctx:,}", style="dim")
    t.append(f"  ({pct:.1f}%)", style=f"{color} dim")
    t.append(f"  {bar}", style=f"{color} dim")

    # Session totals if more than one turn
    if session_input > usage.input_tokens or session_output > usage.output_tokens:
        t.append("  │  ", style="dim")
        t.append(f"session: ↑{session_input:,} ↓{session_output:,}", style="dim")

    console.print(t)
