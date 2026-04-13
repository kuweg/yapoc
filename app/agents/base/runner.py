"""AgentRunner — subprocess wrapper that watches TASK.MD and manages STATUS.json."""

import asyncio
import json
import os
import signal
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from watchdog.events import FileSystemEventHandler, FileModifiedEvent
from watchdog.observers import Observer

from app.config import settings
from app.agents.base import BaseAgent
from app.agents.base.context import _parse_runner_config
from app.utils.adapters import StreamEvent, TextDelta, UsageStats


class _TaskFileHandler(FileSystemEventHandler):
    """Watchdog handler that sets an asyncio event when TASK.MD changes."""

    def __init__(self, task_path: Path, loop: asyncio.AbstractEventLoop, event: asyncio.Event):
        self._task_path = str(task_path)
        self._loop = loop
        self._event = event

    def on_modified(self, event: FileModifiedEvent) -> None:  # type: ignore[override]
        if not event.is_directory and str(event.src_path) == self._task_path:
            self._loop.call_soon_threadsafe(self._event.set)


class AgentRunner:
    """Run a single agent as a long-lived process.

    Watches TASK.MD for ``status: pending`` tasks, executes them via
    ``BaseAgent.run_stream_with_tools(manage_task_file=False)``, and
    self-terminates after idle timeout.
    """

    def __init__(self, agent_name: str) -> None:
        self._name = agent_name
        self._agent_dir = settings.agents_dir / agent_name
        self._agent = BaseAgent(self._agent_dir)
        self._status_path = self._agent_dir / "STATUS.json"
        self._task_path = self._agent_dir / "TASK.MD"
        self._idle_timeout = settings.agent_idle_timeout
        self._poll_interval = settings.runner_poll_interval
        self._shutting_down = False
        self._temporary = self._load_temporary_flag()

    def _load_temporary_flag(self) -> bool:
        """Check CONFIG.md for lifecycle.temporary flag."""
        config_path = self._agent_dir / "CONFIG.md"
        if not config_path.exists():
            return False
        cfg = _parse_runner_config(config_path.read_text(encoding="utf-8"))
        return bool(cfg.get("lifecycle_temporary", False))

    # ── STATUS.json ──────────────────────────────────────────────────────

    def _write_status(
        self,
        state: str,
        task_summary: str = "",
        *,
        tokens_per_second: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        """Atomic write STATUS.json (write to tmp then rename)."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = {
            "state": state,
            "pid": os.getpid(),
            "task_summary": task_summary,
            "started_at": getattr(self, "_started_at", now),
            "updated_at": now,
            "idle_since": now if state == "idle" else None,
            "tokens_per_second": tokens_per_second,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        # Store started_at on first call
        if not hasattr(self, "_started_at"):
            self._started_at = now

        fd, tmp = tempfile.mkstemp(dir=self._agent_dir, suffix=".tmp")
        try:
            os.write(fd, json.dumps(data, indent=2).encode())
            os.close(fd)
            os.replace(tmp, self._status_path)
        except Exception:
            os.close(fd) if not os.get_inheritable(fd) else None
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _write_live(self, text: str) -> None:
        """Overwrite LIVE.MD with current model output buffer (best-effort)."""
        live_path = self._agent_dir / "LIVE.MD"
        try:
            live_path.write_text(text, encoding="utf-8")
        except OSError:
            pass

    # ── Signal handling ──────────────────────────────────────────────────

    def _setup_signals(self) -> None:
        loop = asyncio.get_event_loop()

        def _handler(signum: int, frame) -> None:
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._shutdown("signal")))

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)

    # ── Task execution ───────────────────────────────────────────────────

    def _parse_task_frontmatter(self) -> dict[str, str]:
        """Read TASK.MD and extract YAML frontmatter fields."""
        try:
            raw = self._task_path.read_text(encoding="utf-8")
            import re as _re
            m = _re.match(r"^---\n(.*?)\n---", raw, _re.DOTALL)
            if not m:
                return {}
            result: dict[str, str] = {}
            for line in m.group(1).splitlines():
                kv = line.split(":", 1)
                if len(kv) == 2:
                    result[kv[0].strip()] = kv[1].strip()
            return result
        except Exception:
            return {}

    async def _run_task(self, task_body: str) -> None:
        """Execute a single task, updating TASK.MD frontmatter on completion."""
        self._write_status("running", task_summary=task_body[:120])
        _fm = self._parse_task_frontmatter()
        await self._agent.set_task_status("running")

        # Drain pending notifications and inject into the LLM system prompt
        notifications_context = ""
        try:
            from app.backend.services.notification_queue import notification_queue as _nq
            pending = _nq.drain(self._agent._name)
            if pending:
                lines = ["[SYSTEM NOTIFICATION] The following child agents have completed:"]
                for n in pending:
                    if n["status"] == "done":
                        summary = (n["result"] or "(no result)")[:500]
                        lines.append(f'- {n["child_agent"]} (completed): "{summary}"')
                    else:
                        summary = (n["error"] or "(no error)")[:200]
                        lines.append(f'- {n["child_agent"]} (error): "{summary}"')
                notifications_context = "\n".join(lines)
        except Exception:
            pass  # never let queue drain break task execution

        try:
            live_buf: list[str] = []
            last_live_flush = time.monotonic()
            last_tps: float | None = None
            last_input: int | None = None
            last_output: int | None = None

            async for event in self._agent.run_stream_with_tools(
                manage_task_file=False,
                notifications_context=notifications_context,
            ):
                if isinstance(event, TextDelta):
                    live_buf.append(event.text)
                    # Flush live output at most every 0.5s to avoid hammering FS
                    now = time.monotonic()
                    if now - last_live_flush >= 0.5:
                        self._write_live("".join(live_buf))
                        last_live_flush = now
                elif isinstance(event, UsageStats):
                    last_tps = event.tokens_per_second
                    last_input = event.input_tokens
                    last_output = event.output_tokens
                    self._write_status(
                        "running",
                        task_summary=task_body[:120],
                        tokens_per_second=last_tps,
                        input_tokens=last_input,
                        output_tokens=last_output,
                    )

            # Final flush of live output
            if live_buf:
                self._write_live("".join(live_buf))

            # Read the full response from RESULT.MD (written by _write_result).
            # This decouples result transport from MEMORY.MD, which only stores
            # short 1-sentence summaries to prevent the "double message" bug.
            result_text = await self._agent._read_file("RESULT.MD")
            result_text = result_text.strip()

            await self._agent.set_task_status("done", result=result_text or "Task completed.")
            try:
                from app.utils.db import init_schema, insert_task
                init_schema()
                insert_task(
                    agent=self._name,
                    task_id=_fm.get("task_id", ""),
                    status="done",
                    assigned_by=_fm.get("assigned_by", ""),
                    assigned_at=_fm.get("assigned_at", ""),
                    task_summary=task_body[:500],
                    result_summary=result_text[:2000],
                )
            except Exception:
                pass  # never let DB errors break the runner

        except TimeoutError:
            await self._agent.set_task_status("error", error="Task timed out (exceeded configured timeout)")
            try:
                from app.utils.db import init_schema, insert_task
                init_schema()
                insert_task(
                    agent=self._name,
                    task_id=_fm.get("task_id", ""),
                    status="error",
                    assigned_by=_fm.get("assigned_by", ""),
                    assigned_at=_fm.get("assigned_at", ""),
                    task_summary=task_body[:500],
                    error_summary="Task timed out",
                )
            except Exception:
                pass
        except Exception as exc:
            await self._agent.set_task_status("error", error=str(exc) or repr(exc))
            try:
                from app.utils.db import init_schema, insert_task
                init_schema()
                insert_task(
                    agent=self._name,
                    task_id=_fm.get("task_id", ""),
                    status="error",
                    assigned_by=_fm.get("assigned_by", ""),
                    assigned_at=_fm.get("assigned_at", ""),
                    task_summary=task_body[:500],
                    error_summary=str(exc)[:2000],
                )
            except Exception:
                pass
        finally:
            # Clear live buffer so UI shows nothing when idle
            self._write_live("")

    async def _check_task(self) -> bool:
        """Check TASK.MD for pending status. Returns True if a task was executed."""
        status = await self._agent.get_task_status()
        if status == "pending":
            task_body = await self._agent.get_task_body()
            if task_body:
                # Write task body into TASK.MD for the agent's run loop to pick up
                await self._run_task(task_body)
                return True
        return False

    # ── Shutdown ─────────────────────────────────────────────────────────

    async def _shutdown(self, reason: str) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._write_status("terminated", task_summary=f"shutdown: {reason}")

    # ── Main loop ────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Main runner loop: watch TASK.MD, execute pending tasks, idle-timeout."""
        self._setup_signals()
        self._write_status("spawning")

        loop = asyncio.get_event_loop()
        task_changed = asyncio.Event()

        # Set up watchdog observer for TASK.MD
        handler = _TaskFileHandler(self._task_path, loop, task_changed)
        observer = Observer()
        observer.schedule(handler, str(self._agent_dir), recursive=False)
        observer.start()

        self._write_status("idle")

        # Check for task written before this process started
        # (SpawnAgentTool writes TASK.MD first, then spawns subprocess)
        ran = await self._check_task()
        if ran and self._temporary:
            await self._shutdown("task complete")
        if ran:
            self._write_status("idle")

        try:
            while not self._shutting_down:
                # Wait for file change or poll timeout
                try:
                    await asyncio.wait_for(
                        task_changed.wait(),
                        timeout=self._poll_interval,
                    )
                except TimeoutError:
                    pass  # poll fallback
                task_changed.clear()

                if self._shutting_down:
                    break

                ran = await self._check_task()
                if ran and self._temporary:
                    await self._shutdown("task complete")
                    break
                if ran:
                    self._write_status("idle")

                # Check notification queue for pending notifications.
                # With the cross-process-safe NotificationQueue, subprocesses
                # can read notifications enqueued by the server or other agents.
                if not ran:
                    try:
                        from app.backend.services.notification_queue import notification_queue as _nq
                        if _nq.pending_count(self._name) > 0:
                            # Write a notification trigger TASK.MD so _check_task picks it up
                            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                            trigger = (
                                f"---\nstatus: pending\nassigned_by: notification\n"
                                f"assigned_at: {ts}\n---\n\n## Task\n"
                                f"[Process incoming notifications from sub-agents]\n\n"
                                f"## Result\n\n## Error\n"
                            )
                            self._task_path.write_text(trigger, encoding="utf-8")
                            # Next loop iteration will pick up the pending task
                            continue
                    except Exception:
                        pass  # never let notification check break the runner

                # Check idle timeout
                status_data = self._read_current_status()
                if status_data and status_data.get("idle_since"):
                    idle_since = datetime.fromisoformat(status_data["idle_since"].replace("Z", "+00:00"))
                    elapsed = (datetime.now(timezone.utc) - idle_since).total_seconds()
                    if elapsed >= self._idle_timeout:
                        await self._shutdown("idle timeout")
                        break
        finally:
            observer.stop()
            observer.join(timeout=5)
            if not self._shutting_down:
                self._write_status("terminated", task_summary="shutdown: unexpected exit")

    def _read_current_status(self) -> dict | None:
        """Read STATUS.json synchronously (from the same process)."""
        try:
            return json.loads(self._status_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return None
