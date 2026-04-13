import asyncio
import os
import platform
import re as _re
import signal
import subprocess
import sys
import time

import httpx
import questionary
import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion, merge_completers
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from app.config import settings
from app.cli.renderer import AgentPollState, TurnRenderer, _make_toolbar, calc_cost, print_status_line
from app.cli.sessions import (
    append_message,
    latest_session_id,
    list_sessions,
    load_session,
    new_session_id,
)
from app.utils.adapters import CompactEvent, Message, TextDelta, ToolDone, ToolStart, UsageStats
from app.utils.crash import server_exit_watcher

app = typer.Typer(help="YAPOC \u2014 Yet Another Python OpenClaw CLI", no_args_is_help=False)
agents_app = typer.Typer(help="Agent management commands", no_args_is_help=True)
models_app = typer.Typer(help="Model configuration commands", no_args_is_help=True)
cron_app = typer.Typer(help="Cron task commands (not yet implemented)", no_args_is_help=True)

app.add_typer(agents_app, name="agents")
app.add_typer(models_app, name="models")
app.add_typer(cron_app, name="cron")

console = Console()

_PID_FILE = settings.project_root / ".yapoc.pid"
_ENV_FILE = settings.project_root / ".env"

from app.utils.adapters.models import PROVIDER_MODELS as _PROVIDER_MODELS


def _fetch_openrouter_models_sync() -> list[str]:
    """Fetch models from OpenRouter API synchronously. Returns model IDs or empty list."""
    key = settings.openrouter_api_key
    if not key:
        return []
    try:
        resp = httpx.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        # Filter to models that support tool use, take top 50
        models = [
            m["id"] for m in data
            if m.get("id")
        ]
        return models[:50]
    except (httpx.HTTPError, KeyError, ValueError):
        return []


# -- Helpers -------------------------------------------------------------------

def _client() -> httpx.Client:
    return httpx.Client(base_url=settings.base_url, timeout=120)


def _async_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=settings.base_url, timeout=120)


def _read_pid() -> int | None:
    if _PID_FILE.exists():
        try:
            return int(_PID_FILE.read_text().strip())
        except ValueError:
            return None
    return None


def _write_pid(pid: int) -> None:
    _PID_FILE.write_text(str(pid))


def _remove_pid() -> None:
    if _PID_FILE.exists():
        _PID_FILE.unlink()


# -- Server helpers (shared by CLI commands) -----------------------------------

_SERVER_OUTPUT = settings.agents_dir / "master" / "SERVER_OUTPUT.MD"
_SERVER_CRASH = settings.agents_dir / "master" / "SERVER_CRASH.MD"


def _do_start(host: str = settings.host, port: int = settings.port) -> None:
    pid = _read_pid()
    if pid:
        console.print(f"[yellow]Server already running (PID {pid})[/yellow]")
        return
    _SERVER_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(_SERVER_OUTPUT, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.backend.main:app", "--host", host, "--port", str(port)],
        stdout=log_fh,
        stderr=log_fh,
    )
    _write_pid(proc.pid)
    server_exit_watcher(proc, _SERVER_OUTPUT, _SERVER_CRASH)
    console.print(f"[yellow]Server started[/yellow] (PID {proc.pid}) on http://{host}:{port}")


def _do_stop() -> None:
    pid = _read_pid()
    if not pid:
        console.print("[yellow]No running server found[/yellow]")
        return
    try:
        os.kill(pid, signal.SIGTERM)
        _remove_pid()
        console.print(f"[yellow]Server stopped[/yellow] (PID {pid})")
    except ProcessLookupError:
        console.print(f"[yellow]Process {pid} not found \u2014 cleaning up PID file[/yellow]")
        _remove_pid()


def _do_restart() -> None:
    _do_stop()
    time.sleep(1)
    _do_start()


def _do_ping() -> None:
    t0 = time.perf_counter()
    try:
        with _client() as client:
            resp = client.get("/health")
            resp.raise_for_status()
    except httpx.ConnectError:
        console.print("[magenta]Server is not running[/magenta]")
        return
    ms = (time.perf_counter() - t0) * 1000
    console.print(f"[yellow]pong[/yellow] \u2014 {ms:.1f}ms")


def _do_status() -> None:
    try:
        with _client() as client:
            health = client.get("/health").json()
            agents_data = client.get("/agents").json()
    except httpx.ConnectError:
        console.print("[magenta]Server is not running[/magenta]")
        return

    console.print(f"[yellow]Server OK[/yellow] \u2014 uptime {health.get('uptime', '?')}s")

    table = Table(title="Agents")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Process")
    table.add_column("PID")
    table.add_column("Model")
    table.add_column("Task")
    table.add_column("Memory")
    table.add_column("Errors")

    for ag in agents_data:
        status_color = {"ok": "yellow", "idle": "purple", "busy": "yellow", "error": "magenta"}.get(
            ag["status"], "white"
        )
        proc_state = ag.get("process_state", "")
        proc_color = {
            "running": "yellow", "idle": "purple", "spawning": "yellow", "terminated": "dim",
        }.get(proc_state, "dim")
        pid_str = str(ag["pid"]) if ag.get("pid") else "-"
        table.add_row(
            ag["name"],
            f"[{status_color}]{ag['status']}[/{status_color}]",
            f"[{proc_color}]{proc_state or '-'}[/{proc_color}]",
            pid_str,
            ag["model"],
            "yes" if ag["has_task"] else "no",
            str(ag["memory_entries"]),
            str(ag["health_errors"]),
        )
    console.print(table)


def _do_agents_list() -> None:
    try:
        with _client() as client:
            data = client.get("/agents").json()
    except httpx.ConnectError:
        console.print("[yellow]Server is not running[/yellow]")
        return

    table = Table(show_header=True, box=None)
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Process")
    table.add_column("PID")
    table.add_column("Model")
    table.add_column("Task")
    for ag in data:
        status_color = {"idle": "purple", "busy": "yellow", "error": "magenta"}.get(ag["status"], "white")
        proc_state = ag.get("process_state", "")
        proc_color = {
            "running": "yellow", "idle": "purple", "spawning": "yellow", "terminated": "dim",
        }.get(proc_state, "dim")
        pid_str = str(ag["pid"]) if ag.get("pid") else "-"
        table.add_row(
            ag["name"],
            f"[{status_color}]{ag['status']}[/{status_color}]",
            f"[{proc_color}]{proc_state or '-'}[/{proc_color}]",
            pid_str,
            ag["model"],
            "yes" if ag["has_task"] else "-",
        )
    console.print(table)


def _do_models_info() -> None:
    console.print(f"Adapter: [bold]{settings.default_adapter}[/bold]")
    console.print(f"Model:   [bold]{settings.default_model}[/bold]")


# -- Interactive REPL ----------------------------------------------------------

def _handle_repl_slash(
    cmd: str, args: str, history: list[Message], session_id: str
) -> bool | tuple[str, str | None] | None:
    """Handle slash commands. Returns False=exit, True=handled, tuple=special action."""
    if cmd in ("/exit", "/quit"):
        return False
    if cmd == "/help":
        console.print(
            "\n[bold]Commands:[/bold]\n"
            "  (any text)   Chat with the Master Agent\n"
            "  !command     Run a shell command (not sent to agent)\n"
            "  @path        Inline file contents into your message\n"
            "\n"
            "  /help        Show this help\n"
            "  /start       Start the backend server\n"
            "  /stop        Stop the backend server\n"
            "  /restart     Restart the backend server\n"
            "  /status      Server & agent status\n"
            "  /ping        Ping the server\n"
            "  /agents      List all agents\n"
            "  /model        Show current adapter/model\n"
            "  /sessions     List recent sessions\n"
            "  /continue     Resume the latest session\n"
            "  /resume [id]  Resume a specific session\n"
            "  /compact [f]  Compact context (optional focus)\n"
            "  /cost         Show session cost breakdown\n"
            "  /diff         Show git diff\n"
            "  /copy         Copy last response to clipboard\n"
            "  /export [f]   Export conversation to file\n"
            "  /clear        Clear conversation history\n"
            "  /exit         Quit\n"
            "\n"
            "  [dim]Ctrl+J or Esc+Enter to insert a newline[/dim]\n"
        )
    elif cmd == "/clear":
        history.clear()
        console.print("[dim]Conversation history cleared[/dim]")
    elif cmd == "/model":
        _do_models_info()
    elif cmd == "/start":
        _do_start()
    elif cmd == "/stop":
        _do_stop()
    elif cmd == "/restart":
        _do_restart()
    elif cmd == "/status":
        _do_status()
    elif cmd == "/ping":
        _do_ping()
    elif cmd == "/agents":
        _do_agents_list()
    elif cmd == "/sessions":
        sessions = list_sessions()
        if not sessions:
            console.print("[dim]No sessions found[/dim]")
        else:
            table = Table(show_header=True, box=None)
            table.add_column("ID", style="bold")
            table.add_column("Name")
            table.add_column("Messages")
            table.add_column("Created")
            for s in sessions:
                table.add_row(s.id, s.name, str(s.message_count), s.created_at)
            console.print(table)
    elif cmd == "/continue":
        return ("resume", None)
    elif cmd == "/resume":
        return ("resume", args.strip() or None)
    elif cmd == "/compact":
        return ("compact", args.strip())
    elif cmd == "/cost":
        console.print(
            f"\n[bold]Session Cost[/bold]\n"
            f"  Input tokens:  {_session_input:,}\n"
            f"  Output tokens: {_session_output:,}\n"
            f"  Total cost:    ${_session_cost:.4f}\n"
        )
    elif cmd == "/diff":
        try:
            result = subprocess.run(
                ["git", "diff"], capture_output=True, text=True, timeout=10,
                cwd=str(settings.project_root),
            )
            if result.stdout.strip():
                console.print(Syntax(result.stdout, "diff", theme="monokai"))
            else:
                console.print("[dim]No changes[/dim]")
        except Exception as exc:
            console.print(f"[magenta]Error running git diff: {exc}[/magenta]")
    elif cmd == "/copy":
        if not _last_response:
            console.print("[dim]No response to copy[/dim]")
        else:
            try:
                if platform.system() == "Darwin":
                    subprocess.run(["pbcopy"], input=_last_response, text=True, timeout=5)
                else:
                    subprocess.run(["xclip", "-selection", "clipboard"], input=_last_response, text=True, timeout=5)
                console.print("[dim]Copied to clipboard[/dim]")
            except Exception as exc:
                console.print(f"[magenta]Copy failed: {exc}[/magenta]")
    elif cmd == "/export":
        filename = args.strip() or "conversation.txt"
        try:
            lines = []
            for msg in history:
                lines.append(f"[{msg.role}]\n{msg.content}\n")
            (settings.project_root / filename).write_text("\n".join(lines), encoding="utf-8")
            console.print(f"[dim]Exported {len(history)} messages to {filename}[/dim]")
        except Exception as exc:
            console.print(f"[magenta]Export failed: {exc}[/magenta]")
    else:
        console.print(f"[yellow]Unknown command: {cmd} \u2014 type /help[/yellow]")
    return True


# ── Completers ────────────────────────────────────────────────────────────────

_SLASH_COMMANDS: dict[str, str] = {
    "/help": "Show available commands",
    "/start": "Start the backend server",
    "/stop": "Stop the backend server",
    "/restart": "Restart the backend server",
    "/status": "Server & agent status",
    "/ping": "Ping the server",
    "/agents": "List all agents",
    "/model": "Show current adapter/model",
    "/sessions": "List recent sessions",
    "/continue": "Resume the latest session",
    "/resume": "Resume a specific session",
    "/compact": "Compact context (optional focus)",
    "/clear": "Clear conversation history",
    "/cost": "Show session cost breakdown",
    "/diff": "Show git diff",
    "/copy": "Copy last response to clipboard",
    "/export": "Export conversation to file",
    "/exit": "Quit",
}


class SlashCompleter(Completer):
    """Tab-complete slash commands."""

    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor.lstrip()
        if not text.startswith("/"):
            return
        for cmd, desc in _SLASH_COMMANDS.items():
            if cmd.startswith(text):
                yield Completion(cmd, start_position=-len(text), display_meta=desc)


class FileCompleter(Completer):
    """Tab-complete @file mentions with fuzzy project-relative paths."""

    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor
        # Find the last @ that starts a file mention
        idx = text.rfind("@")
        if idx < 0:
            return
        # Don't trigger if @ is in the middle of a word (e.g., email)
        if idx > 0 and text[idx - 1] not in (" ", "\t", "\n"):
            return
        partial = text[idx + 1:]
        if not partial:
            return
        try:
            root = settings.project_root
            # Glob for matching files, cap results
            matches = sorted(root.glob(f"**/{partial}*"))[:30]
            for p in matches:
                if p.is_file():
                    rel = str(p.relative_to(root))
                    yield Completion(
                        f"@{rel}",
                        start_position=-(len(partial) + 1),
                    )
        except Exception:
            return


def _expand_file_mentions(text: str) -> str:
    """Replace @path mentions with @path + file content inline."""
    root = settings.project_root

    def _replace(m):
        path_str = m.group(1)
        full = root / path_str
        if full.is_file():
            try:
                content = full.read_text(encoding="utf-8", errors="replace")
                if len(content) > 18000:
                    content = content[:18000] + "\n... (truncated)"
                return f"@{path_str}\n```\n{content}\n```"
            except Exception:
                pass
        return m.group(0)

    return _re.sub(r"@([\w./_-]+)", _replace, text)


# ── Last response buffer (for /copy) ─────────────────────────────────────────
_last_response: str = ""


# ── Async sub-agent result collection ────────────────────────────────────────

from app.backend.services.agent_results import (
    build_result_injection as _build_result_injection,
    collect_agent_results as _collect_agent_results,
)


def _show_agent_completions(results: list[tuple[str, str, bool]]) -> None:
    """Print brief notices about completed agent tasks to the console."""
    for agent_name, _result_text, is_error in results:
        if is_error:
            console.print(f"  [magenta]Agent {agent_name} finished with error[/magenta]")
        else:
            console.print(f"  [yellow]Agent {agent_name} finished[/yellow]")


_RESUME_PATH = settings.agents_dir / "master" / "RESUME.MD"


def _rebuild_resume_md() -> str:
    """Scan agent TASK.MD files for in-flight work assigned by master.

    Returns structured markdown summary for RESUME.MD, or empty string if nothing pending.
    """
    from app.agents.base import BaseAgent

    sections: list[str] = []
    for agent_dir in settings.agents_dir.iterdir():
        if not agent_dir.is_dir() or agent_dir.name == "master":
            continue
        task_path = agent_dir / "TASK.MD"
        if not task_path.exists():
            continue
        try:
            content = task_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not content.strip():
            continue

        fm = BaseAgent._parse_frontmatter(content)
        if fm.get("assigned_by") != "master":
            continue
        status = fm.get("status", "")
        # Include pending, running tasks; done tasks only if not consumed
        if status in ("pending", "running"):
            pass
        elif status == "done" and not fm.get("consumed_at"):
            pass
        else:
            continue

        # Extract ## Task section
        import re as _re_mod
        m = _re_mod.search(r"## Task\n(.*?)(?=\n## |\Z)", content, _re_mod.DOTALL)
        task_body = m.group(1).strip() if m else "(no task body)"

        section = f"### {agent_dir.name} — status: {status}\n{task_body}"

        # If done, include result
        if status == "done":
            m = _re_mod.search(r"## Result\n(.*?)(?=\n## |\Z)", content, _re_mod.DOTALL)
            if m and m.group(1).strip():
                section += f"\n\n**Result:**\n{m.group(1).strip()}"

        sections.append(section)

    if not sections:
        return ""

    return "# Pending Agent Tasks\n\n" + "\n\n".join(sections) + "\n"


def _load_session_history(session_id: str) -> list[Message]:
    """Load messages from a persisted session into Message objects."""
    raw = load_session(session_id)
    return [Message(role=m["role"], content=m["content"]) for m in raw]


async def _compact_history(
    history: list[Message], focus: str = ""
) -> tuple[list[Message], int, int]:
    """Compact history via the master agent. Returns (new_history, tokens_before, tokens_after)."""
    from app.agents.base import _estimate_tokens
    from app.agents.master.agent import master_agent

    messages_dicts = [{"role": m.role, "content": m.content} for m in history]
    tokens_before = _estimate_tokens(messages_dicts)

    config = await master_agent._load_config()
    system_prompt = await master_agent._read_file("PROMPT.MD")
    new_messages = await master_agent._compact_messages(
        messages_dicts, system_prompt, config, focus=focus
    )
    tokens_after = _estimate_tokens(new_messages)

    new_history = [Message(role=m["role"], content=m["content"]) for m in new_messages]
    return new_history, tokens_before, tokens_after


async def _repl(
    session_id: str | None = None, resume: bool = False
) -> None:
    """Interactive REPL: prompt -> stream response -> repeat."""
    global _session_input, _session_output, _session_cost
    _session_input = 0
    _session_output = 0
    _session_cost = 0.0

    from app.agents.master.agent import master_agent

    model = settings.default_model

    # ── Session setup ────────────────────────────────────────────────────
    history: list[Message] = []

    if resume and session_id:
        # Resume a specific session
        history = _load_session_history(session_id)
    elif resume and not session_id:
        # Resume latest session
        session_id = latest_session_id()
        if session_id:
            history = _load_session_history(session_id)
        else:
            console.print("[dim]No previous session found — starting new[/dim]")

    if not session_id:
        session_id = new_session_id()

    banner_extra = ""
    if resume and history:
        banner_extra = f"  \u2502  resumed {session_id} ({len(history)} msgs)"

    console.print(
        f"\n [bold yellow]YAPOC[/bold yellow] [dim]\u2014 Pretty Autonomous Python OpenClaw[/dim]"
        f"\n [dim]{model}  \u2502  /help for commands  \u2502  /exit to quit{banner_extra}[/dim]\n"
    )

    # ── Agent poll state (shared between toolbar and TurnRenderer) ────
    poll_state = AgentPollState()
    poll_task = asyncio.create_task(poll_state.run_loop())

    # ── RESUME.md check ──────────────────────────────────────────────────
    # Auto-populate RESUME.MD from in-flight agent tasks (code-enforced)
    auto_resume = _rebuild_resume_md()
    if auto_resume:
        _RESUME_PATH.write_text(auto_resume, encoding="utf-8")

    if _RESUME_PATH.exists() and _RESUME_PATH.read_text().strip():
        console.print("[dim]Resuming after restart\u2026[/dim]\n")
        msg = "You have just been restarted. Read your RESUME.MD file for context and pending task, then execute it. Do NOT call process_restart again."
        history, resp, _ = await _send_to_agent(master_agent, msg, history, poll_state=poll_state)
        append_message(session_id, "user", msg)
        if resp:
            append_message(session_id, "assistant", resp)
        # Clear resume state so it doesn't re-trigger on next startup
        _RESUME_PATH.write_text("")

    # Multiline input: Enter sends, Escape+Enter / Alt+Enter / Ctrl+J / Shift+Enter inserts newline
    kb = KeyBindings()

    @kb.add("escape", "enter")
    def _newline(event):
        event.current_buffer.insert_text("\n")

    @kb.add("c-j")
    def _newline_ctrlj(event):
        event.current_buffer.insert_text("\n")

    _history_file = settings.agents_dir / "master" / ".repl_history"
    _history_file.parent.mkdir(parents=True, exist_ok=True)

    completer = merge_completers([SlashCompleter(), FileCompleter()])

    toolbar = _make_toolbar(poll_state)

    session: PromptSession = PromptSession(
        key_bindings=kb,
        multiline=False,
        history=FileHistory(str(_history_file)),
        completer=completer,
        complete_while_typing=False,
        bottom_toolbar=toolbar,
    )

    try:
        while True:
            try:
                text = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: session.prompt(
                        HTML("<b><cyan>\u276f</cyan></b> "),
                        multiline=False,
                    ),
                )
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Bye![/dim]")
                break

            text = text.strip()
            if not text:
                continue

            # ! bash mode — run shell command, print dimmed output, don't add to context
            if text.startswith("!"):
                shell_cmd = text[1:].strip()
                if shell_cmd:
                    try:
                        result = subprocess.run(
                            shell_cmd, shell=True, capture_output=True, text=True,
                            timeout=30, cwd=str(settings.project_root),
                        )
                        output = (result.stdout + result.stderr).strip()
                        if output:
                            console.print(f"[dim]{output}[/dim]")
                        if result.returncode != 0:
                            console.print(f"[dim](exit code {result.returncode})[/dim]")
                    except subprocess.TimeoutExpired:
                        console.print("[magenta]Command timed out (30s)[/magenta]")
                    except Exception as exc:
                        console.print(f"[magenta]Error: {exc}[/magenta]")
                continue

            if text.startswith("/"):
                parts = text.split(maxsplit=1)
                cmd = parts[0].lower()
                cmd_args = parts[1] if len(parts) > 1 else ""
                result = _handle_repl_slash(cmd, cmd_args, history, session_id)
                if result is False:
                    console.print("[dim]Bye![/dim]")
                    break
                if isinstance(result, tuple):
                    action, payload = result
                    if action == "resume":
                        rid = payload or latest_session_id()
                        if rid:
                            session_id = rid
                            history = _load_session_history(session_id)
                            console.print(f"[dim]Resumed session {session_id} ({len(history)} messages)[/dim]")
                        else:
                            console.print("[dim]No session to resume[/dim]")
                    elif action == "compact":
                        if not history:
                            console.print("[dim]Nothing to compact[/dim]")
                        else:
                            history, tb, ta = await _compact_history(history, focus=payload or "")
                            console.print(f"[dim]Context compacted: {tb:,} \u2192 {ta:,} tokens[/dim]")
                continue

            # Expand @file mentions before sending
            original_text = text
            text = _expand_file_mentions(text)

            # Collect completed sub-agent results and inject as system context
            finished = await _collect_agent_results()
            if finished:
                _show_agent_completions(finished)
                notifications_text = _build_result_injection(finished)
                history = history + [Message(role="user", content=notifications_text)]

            history, resp, _ = await _send_to_agent(master_agent, text, history, poll_state=poll_state)
            # Track last response for /copy
            global _last_response
            if resp:
                _last_response = resp
            # Persist original text (not injected version) to session
            append_message(session_id, "user", original_text)
            if resp:
                append_message(session_id, "assistant", resp)
    finally:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    continue_: bool = typer.Option(False, "--continue", "-c", help="Resume the latest session"),
    resume: str = typer.Option("", "--resume", "-r", help="Resume a specific session by ID"),
):
    """YAPOC \u2014 Pretty Autonomous Python OpenClaw. Run with no command to enter interactive REPL."""
    if ctx.invoked_subcommand is None:
        if resume:
            asyncio.run(_repl(session_id=resume, resume=True))
        elif continue_:
            asyncio.run(_repl(resume=True))
        else:
            asyncio.run(_repl())


# -- One-shot chat (non-TUI) --------------------------------------------------

def _build_approval_gate(renderer: TurnRenderer):
    """Build an approval gate based on the current safety_mode setting."""
    mode = settings.safety_mode

    if mode == "auto_approve":
        return None

    if mode == "strict":
        async def _strict_gate(tool_name: str, tool_input: dict) -> bool:
            return False
        return _strict_gate

    async def _interactive_gate(tool_name: str, tool_input: dict) -> bool:
        if renderer._live:
            renderer._live.stop()

        args_preview = ", ".join(f"{k}={v!r}" for k, v in tool_input.items())
        if len(args_preview) > 120:
            args_preview = args_preview[:117] + "..."

        console.print()
        console.print(
            f"  [bold yellow]? Allow[/bold yellow] [bold]{tool_name}[/bold]"
            f"[dim]({args_preview})[/dim] [yellow][y/n][/yellow] ",
            end="",
        )
        try:
            answer = await asyncio.get_event_loop().run_in_executor(None, input)
            approved = answer.strip().lower() in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            approved = False

        if approved:
            console.print("  [yellow]Approved[/yellow]")
        else:
            console.print("  [magenta]Denied[/magenta]")

        if renderer._live:
            renderer._live.start()

        return approved

    return _interactive_gate


def _is_overloaded(exc: Exception) -> bool:
    err = str(exc).lower()
    return "overloaded" in err or "529" in err


async def _stream_once(
    agent, message: str, history: list[Message],
    poll_state: AgentPollState | None = None,
):
    """Single streaming attempt. Returns (response, renderer) or raises."""
    renderer = TurnRenderer(console, poll_state=poll_state)
    approval_gate = _build_approval_gate(renderer)

    async with renderer:
        async for event in agent.handle_task_stream(
            message, history=history, approval_gate=approval_gate, source="cli"
        ):
            if isinstance(event, TextDelta):
                renderer.on_text_delta(event.text)
            elif isinstance(event, ToolStart):
                renderer.on_tool_start(event.name, event.input)
            elif isinstance(event, ToolDone):
                renderer.on_tool_done(event.name, event.result, event.is_error)
            elif isinstance(event, UsageStats):
                renderer.on_usage(event)
            elif isinstance(event, CompactEvent):
                renderer.on_compact(event)

    return renderer.get_response(), renderer


_MAX_RETRIES = 4
_RETRY_DELAYS = [5, 15, 30, 60]

# Session-level token accumulators
_session_input = 0
_session_output = 0
_session_cost = 0.0


async def _send_to_agent(
    agent, message: str, history: list[Message],
    poll_state: AgentPollState | None = None,
) -> tuple[list[Message], str, dict]:
    """Stream a message to the agent, display output, return updated history + response."""
    global _session_input, _session_output, _session_cost

    history.append(Message(role="user", content=message))
    console.print()

    for attempt in range(_MAX_RETRIES + 1):
        try:
            response, renderer = await _stream_once(agent, message, history, poll_state=poll_state)

            # Reprint compact notice (Live was transient)
            if renderer._compact_notice:
                console.print(f"  [dim]{renderer._compact_notice}[/dim]")

            # Print completed tools (they were in transient Live, so reprint)
            for ct in renderer.completed_tools:
                if ct.is_error:
                    console.print(f"  [purple]\u2717 {ct.name} \u2192 {ct.result}[/purple]")
                elif ct.is_delegation:
                    # Short status line first
                    console.print(f"  [yellow]\u2713 {ct.name}[/yellow]")
                    # Full result in a Panel
                    title = ct.agent_name or ct.name
                    console.print(Panel(ct.result, title=f"[bold]{title}[/bold]", border_style="yellow", padding=(0, 1)))
                else:
                    console.print(f"  [yellow]\u2713 {ct.name} \u2192 {ct.result}[/yellow]")

            if response:
                # Blank line between tool list (if any) and the response body
                console.print()
                # Detect whether response is markdown (has headers/bullets/code fences)
                # or plain text, and render accordingly.
                _md_markers = ("# ", "## ", "### ", "- ", "* ", "```", "**", "__", "> ")
                _is_markdown = any(response.lstrip().startswith(m) for m in _md_markers) or "\n#" in response or "\n-" in response or "\n*" in response
                if _is_markdown:
                    console.print(Markdown(response))
                else:
                    from app.cli.renderer import _render_plain_text
                    for _line in _render_plain_text(response):
                        console.print(_line)

            # Update session totals and print status line
            turn_cost = 0.0
            if renderer.usage:
                _session_input += renderer.usage.input_tokens
                _session_output += renderer.usage.output_tokens
                turn_cost = calc_cost(
                    settings.default_model,
                    renderer.usage.input_tokens,
                    renderer.usage.output_tokens,
                    cache_creation_tokens=renderer.usage.cache_creation_tokens,
                    cache_read_tokens=renderer.usage.cache_read_tokens,
                )
                _session_cost += turn_cost

            console.print()
            print_status_line(
                console,
                model=settings.default_model,
                usage=renderer.usage,
                session_input=_session_input,
                session_output=_session_output,
                turn_cost=turn_cost,
                session_cost=_session_cost,
            )

            history.append(Message(role="assistant", content=response))
            return history, response, {}

        except KeyboardInterrupt:
            console.print("[dim]Interrupted[/dim]")
            history.pop()
            return history, "", {}

        except Exception as exc:
            if _is_overloaded(exc) and attempt < _MAX_RETRIES:
                delay = _RETRY_DELAYS[attempt]
                console.print(
                    f"[yellow]API overloaded \u2014 retrying in {delay}s "
                    f"(attempt {attempt + 1}/{_MAX_RETRIES})...[/yellow]"
                )
                await asyncio.sleep(delay)
                continue

            if _is_overloaded(exc):
                console.print("[magenta]API is overloaded after multiple retries. Try again later.[/magenta]")
            else:
                console.print(f"\n[magenta]Error:[/magenta] {exc}")
            history.pop()
            return history, "", {}


async def _oneshot(message: str) -> None:
    """Single-shot: stream response, render markdown, exit."""
    from app.agents.master.agent import master_agent

    await _send_to_agent(master_agent, message, [])


# -- CLI subcommands -----------------------------------------------------------

@app.command()
def start(
    host: str = typer.Option(settings.host, help="Host to bind"),
    port: int = typer.Option(settings.port, help="Port to listen on"),
):
    """Start the YAPOC backend server."""
    _do_start(host, port)


@app.command()
def stop():
    """Stop the YAPOC backend server."""
    _do_stop()


@app.command()
def restart(
    host: str = typer.Option(settings.host, help="Host to bind"),
    port: int = typer.Option(settings.port, help="Port to listen on"),
):
    """Restart the YAPOC backend server."""
    _do_stop()
    time.sleep(1)
    _do_start(host, port)


@app.command()
def status():
    """Show server and agent status."""
    _do_status()


@app.command()
def ping():
    """Ping the backend and show round-trip time."""
    _do_ping()


@app.command()
def chat(
    message: str = typer.Argument(default=None, help="Message to send (one-shot)"),
    continue_: bool = typer.Option(False, "--continue", "-c", help="Resume the latest session"),
    resume: str = typer.Option("", "--resume", "-r", help="Resume a specific session by ID"),
):
    """Send a one-shot message, or enter interactive REPL."""
    if message:
        asyncio.run(_oneshot(message))
    elif resume:
        asyncio.run(_repl(session_id=resume, resume=True))
    elif continue_:
        asyncio.run(_repl(resume=True))
    else:
        asyncio.run(_repl())


@app.command()
def backend(
    host: str = typer.Option(settings.host, help="Host to bind"),
    port: int = typer.Option(settings.port, help="Port to listen on"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload (dev mode)"),
    log_level: str = typer.Option(settings.log_level, "--log-level", help="Log level: DEBUG|INFO|WARNING|ERROR"),
):
    """Run the backend server in the foreground (blocking). Ctrl+C to stop."""
    import os as _os
    pid = _read_pid()
    if pid:
        console.print(
            f"[yellow]A daemon instance is already running (PID {pid}).[/yellow] "
            "Stop it with [bold]yapoc stop[/bold] first."
        )
        return
    # Pass log level to the server process via env var so setup_logging() picks it up
    _os.environ["LOG_LEVEL"] = log_level.upper()
    args = [
        sys.executable, "-m", "uvicorn", "app.backend.main:app",
        "--host", host, "--port", str(port),
        "--log-level", log_level.lower(),
    ]
    if reload:
        args.append("--reload")
    console.print(f"[dim]Backend listening on http://{host}:{port} — Ctrl+C to stop[/dim]")
    _SERVER_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(args)  # stdout/stderr inherit → logs visible in terminal
    _write_pid(proc.pid)
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()
    finally:
        _remove_pid()


@app.command()
def run(
    host: str = typer.Option(settings.host, help="Host to bind"),
    port: int = typer.Option(settings.port, help="Port to listen on"),
    continue_: bool = typer.Option(False, "--continue", "-c", help="Resume the latest session"),
    resume: str = typer.Option("", "--resume", "-r", help="Resume a specific session by ID"),
):
    """Start the backend server (daemon) then enter the interactive REPL."""
    _do_start(host, port)
    if resume:
        asyncio.run(_repl(session_id=resume, resume=True))
    elif continue_:
        asyncio.run(_repl(resume=True))
    else:
        asyncio.run(_repl())


@app.command("deep-amnesia")
def deep_amnesia():
    """Clear all memory files for every agent. Irreversible."""
    confirmed = questionary.confirm(
        "WARNING: This will wipe MEMORY.MD, NOTES.MD, HEALTH.MD, TASK.MD, RESULT.MD, "
        "OUTPUT.MD, CRASH.MD, and RESUME.MD for every agent. Are you sure?",
        default=False,
    ).ask()
    if not confirmed:
        typer.echo("Aborted.")
        raise typer.Exit()

    _DEEP_AMNESIA_FILES = (
        "MEMORY.MD", "NOTES.MD", "HEALTH.MD",
        "TASK.MD", "RESULT.MD", "OUTPUT.MD", "CRASH.MD", "RESUME.MD",
    )
    cleared_count = 0
    for agent_dir in sorted(settings.agents_dir.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name == "base":
            continue
        for fname in _DEEP_AMNESIA_FILES:
            fpath = agent_dir / fname
            if fpath.exists():
                fpath.write_text("", encoding="utf-8")
                cleared_count += 1
    typer.echo(f"Done. Cleared {cleared_count} file(s) across all agents.")


# -- Agents sub-commands -------------------------------------------------------

@agents_app.command("list")
def agents_list():
    """List all agents and their status."""
    _do_agents_list()


@agents_app.command("status")
def agents_status(name: str = typer.Argument(..., help="Agent name")):
    """Show detailed status for a specific agent."""
    try:
        with _client() as client:
            agents_data = client.get("/agents").json()
            memory = client.get(f"/agents/{name}/memory").json()
            health = client.get(f"/agents/{name}/health").json()
    except httpx.ConnectError:
        console.print("[magenta]Server is not running[/magenta]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            console.print(f"[magenta]Agent '{name}' not found[/magenta]")
        else:
            console.print(f"[magenta]Error:[/magenta] {exc.response.text}")
        raise typer.Exit(1)

    agent = next((a for a in agents_data if a["name"] == name), None)
    if agent:
        console.print(f"\n[bold]{name}[/bold]")
        console.print(f"  Status:  {agent['status']}")
        console.print(f"  Model:   {agent['model']}")
        console.print(f"  Task:    {'pending' if agent['has_task'] else 'none'}")
        console.print(f"  Memory:  {agent['memory_entries']} entries")
        console.print(f"  Errors:  {agent['health_errors']}")

    if memory.get("content"):
        console.print("\n[bold]Memory:[/bold]")
        console.print(memory["content"])

    if health.get("content"):
        console.print("\n[bold]Health:[/bold]")
        console.print(health["content"])


@agents_app.command("model")
def agents_model(name: str = typer.Argument(..., help="Agent name")):
    """View or change the model for a specific agent."""
    config_path = settings.agents_dir / name / "CONFIG.md"
    if not config_path.parent.exists():
        console.print(f"[magenta]Agent '{name}' not found[/magenta]")
        raise typer.Exit(1)

    # Show current config
    from app.utils.adapters import parse_config_block

    content = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    cfg = parse_config_block(content) if content.strip() else {}
    current_adapter = cfg.get("adapter", settings.default_adapter)
    current_model = cfg.get("model", settings.default_model)
    console.print(f"[bold]{name}[/bold] — current: {current_adapter} / {current_model}")

    change = questionary.confirm("Change model?", default=False).ask()
    if not change:
        raise typer.Exit()

    provider = questionary.select(
        "Select provider:",
        choices=list(_PROVIDER_MODELS.keys()),
    ).ask()
    if not provider:
        raise typer.Exit()

    if provider == "openrouter":
        console.print("[dim]Fetching models from OpenRouter...[/dim]")
        dynamic = _fetch_openrouter_models_sync()
        model_choices = dynamic if dynamic else _PROVIDER_MODELS[provider]
    else:
        model_choices = _PROVIDER_MODELS[provider]

    model = questionary.select(
        "Select model:",
        choices=model_choices,
    ).ask()
    if not model:
        raise typer.Exit()

    # Update CONFIG.md
    import re as _config_re

    if content.strip():
        # Update existing keys
        if _config_re.search(r"^adapter\s*:", content, _config_re.MULTILINE):
            content = _config_re.sub(r"^adapter\s*:.*$", f"adapter: {provider}", content, flags=_config_re.MULTILINE)
        else:
            content += f"\nadapter: {provider}\n"
        if _config_re.search(r"^model\s*:", content, _config_re.MULTILINE):
            content = _config_re.sub(r"^model\s*:.*$", f"model: {model}", content, flags=_config_re.MULTILINE)
        else:
            content += f"model: {model}\n"
    else:
        content = f"adapter: {provider}\nmodel: {model}\n"

    config_path.write_text(content, encoding="utf-8")
    console.print(f"[yellow]Updated {name}:[/yellow] {provider} / {model}")


# -- Models sub-commands -------------------------------------------------------

@models_app.command("list")
def models_list():
    """Interactive provider + model picker \u2014 saves to .env."""
    provider = questionary.select(
        "Select provider:",
        choices=list(_PROVIDER_MODELS.keys()),
    ).ask()

    if not provider:
        raise typer.Exit()

    # For openrouter, try dynamic fetch first, fall back to static list
    if provider == "openrouter":
        console.print("[dim]Fetching models from OpenRouter...[/dim]")
        dynamic = _fetch_openrouter_models_sync()
        model_choices = dynamic if dynamic else _PROVIDER_MODELS[provider]
    else:
        model_choices = _PROVIDER_MODELS[provider]

    model = questionary.select(
        "Select model:",
        choices=model_choices,
    ).ask()

    if not model:
        raise typer.Exit()

    _update_env("DEFAULT_ADAPTER", provider)
    _update_env("DEFAULT_MODEL", model)
    console.print(f"[yellow]Saved:[/yellow] {provider} / {model}")


@models_app.command("info")
def models_info():
    """Show currently configured adapter and model."""
    _do_models_info()


def _update_env(key: str, value: str) -> None:
    """Set or update a key in .env file."""
    lines: list[str] = []
    if _ENV_FILE.exists():
        lines = _ENV_FILE.read_text().splitlines()

    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
            lines[i] = f"{key}={value}"
            updated = True
            break

    if not updated:
        lines.append(f"{key}={value}")

    _ENV_FILE.write_text("\n".join(lines) + "\n")


# -- Cron commands -------------------------------------------------------------

_CRON_NOTES = settings.agents_dir / "cron" / "NOTES.MD"


@cron_app.command("list")
def cron_list():
    """List scheduled cron tasks from the Cron agent's schedule."""
    if not _CRON_NOTES.exists() or not _CRON_NOTES.read_text().strip():
        console.print("[dim]No scheduled jobs. Use the REPL to ask master to add cron jobs.[/dim]")
        return
    content = _CRON_NOTES.read_text()
    from rich.markdown import Markdown
    console.print(Markdown(content))


@cron_app.command("trigger")
def cron_trigger():
    """Manually trigger the cron agent to run all due scheduled jobs."""
    import asyncio
    from app.utils.tools.delegation import SpawnAgentTool

    async def _run():
        spawn = SpawnAgentTool()
        result = await spawn.execute(
            agent_name="cron",
            task="run-schedule: Execute all due scheduled jobs from your NOTES.MD schedule.",
        )
        console.print(f"[yellow]{result}[/yellow]")

    asyncio.run(_run())


@cron_app.command("status")
def cron_status():
    """Show the cron agent's process status."""
    from app.utils.tools.delegation import PingAgentTool
    import asyncio

    async def _run():
        ping = PingAgentTool()
        result = await ping.execute(agent_name="cron")
        console.print(result)

    asyncio.run(_run())


if __name__ == "__main__":
    app()
