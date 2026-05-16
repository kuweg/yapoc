"""AgentRunner — subprocess wrapper that watches TASK.MD and manages STATUS.json."""

import asyncio
import json
import os
import signal
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger as _log
from watchdog.events import FileSystemEventHandler, FileModifiedEvent
from watchdog.observers import Observer

from app.config import settings
from app.agents.base import BaseAgent
from app.agents.base.context import _parse_runner_config
from app.utils.adapters import TextDelta, ThinkingDelta, ToolStart, ToolDone, UsageStats


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
        # Per-agent idle_timeout via agent-settings.json; falls back to the
        # global settings.agent_idle_timeout default.
        try:
            from app.utils.agent_settings import resolve_runner_settings
            _runner_cfg = resolve_runner_settings(agent_name)
        except Exception as _rs_exc:
            _log.bind(agent=agent_name).warning(
                "resolve_runner_settings failed (using settings default): {}",
                _rs_exc,
            )
            _runner_cfg = {}
        self._idle_timeout = int(
            _runner_cfg.get("idle_timeout") or settings.agent_idle_timeout
        )
        self._poll_interval = settings.runner_poll_interval
        self._shutting_down = False
        self._temporary = self._load_temporary_flag()

    def _load_temporary_flag(self) -> bool:
        """Check CONFIG.yaml for lifecycle.temporary flag."""
        config_path = self._agent_dir / "CONFIG.yaml"
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
            from app.utils.frontmatter import parse_frontmatter_fields
            return parse_frontmatter_fields(self._task_path.read_text(encoding="utf-8"))
        except Exception as _fm_exc:
            _log.bind(agent=self._name).warning(
                "Frontmatter parse failed for {}: {}", self._task_path, _fm_exc
            )
            return {}

    async def _run_task(self, task_body: str) -> None:
        """Execute a single task, updating TASK.MD frontmatter on completion."""
        self._write_status("running", task_summary=task_body)
        _fm = self._parse_task_frontmatter()
        # Propagate session binding into this subprocess so turn-level
        # events from child agents stream back to the same UI session.
        self._agent._session_id = _fm.get("session_id") or None
        await self._agent.set_task_status("running")

        # Heartbeat: refresh STATUS.json every 30s while the task is running
        # so (a) idle_since stays None even if no UsageStats events fire for
        # long periods, and (b) the UI's /agents poll sees a fresh updated_at
        # and renders the agent as still-alive.
        _hb_summary = task_body
        _hb_stop = asyncio.Event()

        async def _heartbeat() -> None:
            try:
                while not _hb_stop.is_set():
                    try:
                        await asyncio.wait_for(_hb_stop.wait(), timeout=30.0)
                        return  # stop event fired
                    except asyncio.TimeoutError:
                        pass
                    try:
                        self._write_status("running", task_summary=_hb_summary)
                    except Exception as _hb_exc:
                        _log.bind(agent=self._name).warning(
                            "Heartbeat STATUS.json write failed: {}", _hb_exc
                        )
            except asyncio.CancelledError:
                return

        _hb_task = asyncio.create_task(_heartbeat())

        # Drain pending notifications and inject into the LLM system prompt
        notifications_context = ""
        try:
            from app.backend.services.notification_queue import notification_queue as _nq
            pending = _nq.drain(self._agent._name)
            if pending:
                lines = ["[SYSTEM NOTIFICATION] The following child agents have completed:"]
                for n in pending:
                    if n["status"] == "done":
                        summary = (n["result"] or "(no result)")
                        lines.append(f'- {n["child_agent"]} (completed): "{summary}"')
                    else:
                        summary = (n["error"] or "(no error)")
                        lines.append(f'- {n["child_agent"]} (error): "{summary}"')
                notifications_context = "\n".join(lines)
        except Exception as _queue_exc:
            _log.bind(agent=self._name).warning(
                "Notification queue drain failed (continuing): {}", _queue_exc
            )

        try:
            live_buf: list[str] = []
            last_live_flush = time.monotonic()
            last_thinking_marker = 0.0
            last_tps: float | None = None
            last_input: int | None = None
            last_output: int | None = None

            # Notification tasks: block destructive tools for ALL agents
            _blocked = (
                {"server_restart", "process_restart", "spawn_agent", "kill_agent", "shell_exec"}
                if task_body.startswith("[Process incoming")
                else None
            )
            async for event in self._agent.run_stream_with_tools(
                manage_task_file=False,
                notifications_context=notifications_context,
                blocked_tools=_blocked,
            ):
                if isinstance(event, TextDelta):
                    live_buf.append(event.text)
                    # Flush live output at most every 0.5s to avoid hammering FS
                    now = time.monotonic()
                    if now - last_live_flush >= 0.5:
                        self._write_live("".join(live_buf))
                        last_live_flush = now
                elif isinstance(event, ThinkingDelta):
                    # Keep LIVE.MD visibly active during long non-text reasoning/tool turns.
                    now = time.monotonic()
                    if now - last_thinking_marker >= 2.0:
                        live_buf.append("\n[thinking...]\n")
                        self._write_live("".join(live_buf))
                        last_live_flush = now
                        last_thinking_marker = now
                elif isinstance(event, ToolStart):
                    input_preview = str(event.input).replace("\n", " ")
                    live_buf.append(f"\n[tool:start] {event.name} {input_preview}\n")
                    now = time.monotonic()
                    self._write_live("".join(live_buf))
                    last_live_flush = now
                elif isinstance(event, ToolDone):
                    result_preview = (event.result or "").replace("\n", " ")
                    status_label = "error" if event.is_error else "done"
                    live_buf.append(f"\n[tool:{status_label}] {event.name} {result_preview}\n")
                    now = time.monotonic()
                    self._write_live("".join(live_buf))
                    last_live_flush = now
                elif isinstance(event, UsageStats):
                    last_tps = event.tokens_per_second
                    last_input = event.input_tokens
                    last_output = event.output_tokens
                    self._write_status(
                        "running",
                        task_summary=task_body,
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
            _done_fm = self._parse_task_frontmatter()
            try:
                from app.utils.db import init_schema, insert_task
                init_schema()
                insert_task(
                    agent=self._name,
                    task_id=_done_fm.get("task_id", "") or _fm.get("task_id", ""),
                    status="done",
                    assigned_by=_done_fm.get("assigned_by", "") or _fm.get("assigned_by", ""),
                    assigned_at=_done_fm.get("assigned_at", "") or _fm.get("assigned_at", ""),
                    task_summary=task_body,
                    result_summary=result_text,
                )
            except Exception as _db_exc:
                _log.bind(agent=self._name).warning(
                    "DB insert_task(done) failed (task still completed): {}", _db_exc
                )

            # Publish result to parent's Redis inbox (non-blocking)
            await self._notify_parent_via_bus(result_text, "done")

            # Mark notification tasks as consumed so the poller skips them
            if task_body.startswith("[Process incoming"):
                await self._agent.mark_task_consumed()

        except TimeoutError:
            await self._agent.set_task_status("error", error="Task timed out (exceeded configured timeout)")
            _err_fm = self._parse_task_frontmatter()
            try:
                from app.utils.db import init_schema, insert_task
                init_schema()
                insert_task(
                    agent=self._name,
                    task_id=_err_fm.get("task_id", "") or _fm.get("task_id", ""),
                    status="error",
                    assigned_by=_err_fm.get("assigned_by", "") or _fm.get("assigned_by", ""),
                    assigned_at=_err_fm.get("assigned_at", "") or _fm.get("assigned_at", ""),
                    task_summary=task_body,
                    error_summary="Task timed out",
                )
            except Exception as _db_exc:
                _log.bind(agent=self._name).warning(
                    "DB insert_task(timeout) failed: {}", _db_exc
                )
            await self._notify_parent_via_bus("Task timed out", "error")
            if task_body.startswith("[Process incoming"):
                await self._agent.mark_task_consumed()
        except Exception as exc:
            await self._agent.set_task_status("error", error=str(exc) or repr(exc))
            _exc_fm = self._parse_task_frontmatter()
            try:
                from app.utils.db import init_schema, insert_task
                init_schema()
                insert_task(
                    agent=self._name,
                    task_id=_exc_fm.get("task_id", "") or _fm.get("task_id", ""),
                    status="error",
                    assigned_by=_exc_fm.get("assigned_by", "") or _fm.get("assigned_by", ""),
                    assigned_at=_exc_fm.get("assigned_at", "") or _fm.get("assigned_at", ""),
                    task_summary=task_body,
                    error_summary=str(exc),
                )
            except Exception as _db_exc:
                _log.bind(agent=self._name).warning(
                    "DB insert_task(error) failed: {}", _db_exc
                )
            await self._notify_parent_via_bus(str(exc), "error")
            if task_body.startswith("[Process incoming"):
                await self._agent.mark_task_consumed()
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

    # ── Redis inbox ────────────────────────────────────────────────────

    async def _setup_redis(self) -> bool:
        """Connect to Redis, create consumer group, claim pending messages.

        Returns True if Redis is available, False otherwise.
        """
        try:
            from app.backend.message_bus import bus

            if not await bus.connect():
                _log.bind(agent=self._name).warning(
                    "Redis unavailable — falling back to TASK.MD watchdog only"
                )
                return False

            self._bus = bus
            self._consumer_name = f"{self._name}_{os.getpid()}"
            self._inbox_stream = f"agent:{self._name}:inbox"
            group = f"{self._name}_group"

            # Idempotent consumer group creation
            await bus.stream_create_group(self._inbox_stream, group)

            # Claim messages from a previous instance that crashed
            claimed = await bus.stream_claim_pending(
                self._inbox_stream, group, self._consumer_name
            )
            if claimed:
                _log.bind(agent=self._name).info(
                    "Claimed {} pending message(s) from previous instance", len(claimed)
                )
                for msg in claimed:
                    await self._process_inbox_message(msg)

            # Flush any outbox from a previous instance
            await bus.flush_outbox(self._name)

            _log.bind(agent=self._name).info(
                "Redis inbox ready (stream={}, consumer={})",
                self._inbox_stream,
                self._consumer_name,
            )
            return True
        except Exception as _exc:
            _log.bind(agent=self._name).warning(
                "Redis setup failed (continuing without Redis): {}", _exc
            )
            return False

    async def _read_inbox(self) -> list[dict[str, object]]:
        """Read one message from the agent's Redis inbox stream."""
        return await self._bus.stream_read_group(
            self._inbox_stream,
            f"{self._name}_group",
            self._consumer_name,
            block_ms=1000,
            count=1,
        )

    async def _ack_inbox(self, msg_id: str) -> None:
        await self._bus.stream_ack(
            self._inbox_stream, f"{self._name}_group", msg_id
        )

    async def _process_inbox_message(self, msg: dict[str, object]) -> bool:
        """Process a message from the Redis inbox. Returns True if a task was run."""
        data = msg.get("data", {})
        if not isinstance(data, dict):
            return False

        msg_type = data.get("type", "")
        msg_id = str(msg.get("id", ""))

        if msg_type == "task_assign":
            task_text = str(data.get("task", "") or data.get("payload", ""))
            if not task_text:
                await self._ack_inbox(msg_id)
                return False
            _log.bind(agent=self._name).info(
                "Redis inbox: task_assign — running task ({} chars)", len(task_text)
            )
            await self._ack_inbox(msg_id)
            await self._run_task(task_text)
            return True

        elif msg_type == "kill":
            reason = str(data.get("reason", "requested via Redis"))
            await self._ack_inbox(msg_id)
            await self._notify_parent_via_bus(f"killed: {reason}", "error")
            await self._shutdown(f"kill: {reason}")

        elif msg_type == "prepare_shutdown":
            # Server is restarting — save current task state (already in TASK.MD)
            # and ack. The runner continues; server SIGTERM kills it.
            await self._ack_inbox(msg_id)
            _log.bind(agent=self._name).info(
                "Redis inbox: prepare_shutdown acknowledged — TASK.MD preserved"
            )
            return False

        elif msg_type == "task_result":
            # Child agent completed — write a trigger TASK.MD so the next
            # iteration picks it up and processes it via the normal notification pipeline.
            child = str(data.get("child_agent", "unknown"))
            status = str(data.get("status", "done"))
            result = str(data.get("result", ""))
            session_id = str(data.get("session_id", ""))
            await self._ack_inbox(msg_id)
            fm = self._parse_task_frontmatter()
            parent = fm.get("assigned_by", "master")
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            task_body = (
                f"[Process incoming result from {child} ({status})]\n\n"
                f"Child agent '{child}' completed with status '{status}'. "
                f"Summarize the result for the user. Do NOT spawn, restart, or verify."
            )
            context = (
                f"Result from {child} ({status}):\n{result}"
                if result
                else f"Agent {child} completed ({status}) but produced no output."
            )
            trigger = (
                f"---\n"
                f"status: pending\n"
                f"session_id: {session_id or fm.get('session_id', '')}\n"
                f"assigned_by: {parent}\n"
                f"assigned_at: {ts}\n"
                f"---\n\n## Task\n{task_body}\n\n## Context\n{context}\n\n## Result\n\n## Error\n"
            )
            self._task_path.write_text(trigger, encoding="utf-8")
            _log.bind(agent=self._name).info(
                "Redis inbox: task_result from {} ({}) result_len={} — trigger written",
                child, status, len(result),
            )
            return False
            return False

        elif msg_type == "ping":
            await self._ack_inbox(msg_id)
            # Publish status response
            status_data = self._read_current_status()
            await self._bus.publish(
                f"agent:{self._name}:status",
                {
                    "type": "pong",
                    "agent": self._name,
                    "state": status_data.get("state", "unknown") if status_data else "unknown",
                    "pid": os.getpid(),
                },
                agent_name=self._name,
            )
            return False

        # Unknown message type — ack and ignore
        if msg_id:
            await self._ack_inbox(msg_id)
        return False

    async def _notify_parent_via_bus(self, result: str, status: str) -> None:
        """Publish task result to the parent via Redis, falling back to notification_queue."""
        fm = self._parse_task_frontmatter()
        parent = fm.get("assigned_by", "")
        if not parent or parent == self._name:
            return

        session_id = fm.get("session_id", "")

        # Try Redis first
        bus_ok = False
        if hasattr(self, '_bus') and self._bus is not None:
            try:
                async with asyncio.timeout(5):
                    await self._bus.stream_add(
                        f"agent:{parent}:inbox",
                        {
                            "type": "task_result",
                            "child_agent": self._name,
                            "status": status,
                            "result": result,
                            "session_id": session_id,
                        },
                        agent_name=self._name,
                    )
                bus_ok = True
                _log.bind(agent=self._name).info(
                    "Redis notify: parent={} result_len={} status={}", parent, len(result), status
                )
            except TimeoutError:
                _log.bind(agent=self._name).warning(
                    "Redis notify timed out ({}): falling back to notification_queue", parent
                )
            except Exception as _exc:
                _log.bind(agent=self._name).warning(
                    "Redis notify failed ({}): falling back to notification_queue — {}", parent, _exc
                )

        # Fall back to file-based notification_queue (always works cross-process)
        if not bus_ok:
            try:
                from app.backend.services.notification_queue import notification_queue as _nq
                _nq.enqueue(
                    parent_agent=parent,
                    child_agent=self._name,
                    status=status,
                    result=result if status == "done" else "",
                    error=result if status == "error" else "",
                    session_id=session_id,
                )
                _log.bind(agent=self._name).info(
                    "Queue notify: parent={} result_len={} status={}", parent, len(result), status
                )
            except Exception as _q_exc:
                _log.bind(agent=self._name).warning(
                    "Queue notify failed ({}): {}", parent, _q_exc
                )

    # ── Shutdown ─────────────────────────────────────────────────────────

    async def _shutdown(self, reason: str) -> None:
        if self._shutting_down:
            return
        # If there's an active task, notify parent before dying so the
        # parent doesn't hang waiting for a result that will never arrive.
        try:
            fm = self._parse_task_frontmatter()
            if fm.get("status") == "running":
                await self._notify_parent_via_bus("killed", "error")
        except Exception:
            pass  # best-effort: don't block shutdown on notification failure
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

        # Set up Redis inbox (non-fatal fallback to watchdog-only)
        _has_redis = await self._setup_redis()

        # Check for task written before this process started
        # (SpawnAgentTool writes TASK.MD first, then spawns subprocess)
        ran = await self._check_task()
        if ran and self._temporary:
            await self._shutdown("task complete")
        if ran:
            self._write_status("idle")

        try:
            while not self._shutting_down:
                if _has_redis:
                    # Run Redis inbox read and watchdog wait concurrently
                    inbox_task = asyncio.create_task(self._read_inbox())
                    wd_task = asyncio.create_task(
                        asyncio.wait_for(task_changed.wait(), timeout=self._poll_interval)
                    )
                    try:
                        done, pending = await asyncio.wait(
                            [inbox_task, wd_task], return_when=asyncio.FIRST_COMPLETED
                        )
                        for t in pending:
                            t.cancel()
                    except Exception:
                        await asyncio.sleep(0.1)
                        task_changed.clear()
                        continue
                else:
                    # Pure watchdog mode (no Redis)
                    try:
                        await asyncio.wait_for(
                            task_changed.wait(), timeout=self._poll_interval
                        )
                    except TimeoutError:
                        pass
                task_changed.clear()

                if self._shutting_down:
                    break

                ran = False

                # Process Redis inbox messages (if any)
                if _has_redis and inbox_task in done:
                    try:
                        for msg in inbox_task.result():
                            if await self._process_inbox_message(msg):
                                ran = True
                    except (asyncio.CancelledError, Exception):
                        pass

                if not ran:
                    ran = await self._check_task()
                if ran and self._temporary:
                    await self._shutdown("task complete")
                    break
                if ran:
                    self._write_status("idle")

                # Check notification queue for pending notifications.
                # Only needed when Redis is down (file-based fallback).
                # When Redis is available, task_assign and task_result
                # messages arrive via the inbox stream directly.
                if not ran and not _has_redis:
                    try:
                        from app.backend.services.notification_queue import notification_queue as _nq
                        if _nq.pending_count(self._name) > 0:
                            # Look up our real parent so that when WE complete
                            # this notification-processing task, the next
                            # notification_poller pass can route OUR result back
                            # up the chain. Previously this wrote a literal
                            # `assigned_by: notification`, which made our
                            # completion notification get enqueued for a
                            # nonexistent "notification" agent and silently
                            # dropped. SpawnRegistry is the authoritative
                            # source; fall back to whatever assigned_by the
                            # previous TASK.MD had, then default to "master".
                            from app.backend.services.spawn_registry import registry as _spawn_registry
                            real_parent = _spawn_registry.get_parent(self._name)
                            if not real_parent:
                                fm = self._parse_task_frontmatter()
                                prior = fm.get("assigned_by", "")
                                if prior and prior != "notification":
                                    real_parent = prior
                            if not real_parent:
                                real_parent = "master"

                            # Preserve session_id from the previous TASK.MD
                            # (was lost in the old inline template) so the
                            # user-session binding survives this re-entry.
                            prior_fm = self._parse_task_frontmatter()
                            prior_session_id = prior_fm.get("session_id", "")

                            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                            trigger = (
                                f"---\n"
                                f"status: pending\n"
                                f"session_id: {prior_session_id}\n"
                                f"assigned_by: {real_parent}\n"
                                f"assigned_at: {ts}\n"
                                f"---\n\n## Task\n"
                                f"[Process incoming notifications from sub-agents]\n\n"
                                f"## Result\n\n## Error\n"
                            )
                            self._task_path.write_text(trigger, encoding="utf-8")
                            # Next loop iteration will pick up the pending task
                            continue
                    except Exception as _wake_exc:
                        _log.bind(agent=self._name).warning(
                            "Self-trigger for pending notifications failed: {}",
                            _wake_exc,
                        )

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
