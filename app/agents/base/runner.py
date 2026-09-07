"""AgentRunner — subprocess wrapper that watches TASK.MD and manages STATUS.json."""

import asyncio
import json
import os
import re
import signal
import tempfile
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger as _log
from watchdog.events import FileSystemEventHandler, FileModifiedEvent
from watchdog.observers import Observer

from app.config import settings
from app.agents.base import BaseAgent, TurnLimitReached
from app.agents.base.context import _parse_runner_config
from app.utils.adapters import ToolStart, UsageStats


# Stale task_result messages claimed from a Redis consumer group's pending
# list can replay multi-hour-old completions and overwrite a freshly-spawned
# agent's RESULT.MD with content from an obsolete session. When a claimed
# task_result's stream-ID timestamp is older than this threshold, the runner
# ACKs and skips it instead of writing a "process incoming result" trigger.
# Follow-up to docs/master-audit.md / claude-solution-design.md (option 1 —
# freshness gate). See the planning cross-up investigation for the failure
# mode this prevents.
_STALE_TASK_RESULT_THRESHOLD_S = 600  # 10 minutes
# task_assign messages older than this are stale replays from a previous agent
# lifetime. The inbox consumer group starts at id 0, and the watchdog/TASK.MD
# path runs tasks without acking the matching Redis message — so that message
# lingers unacked and gets reclaimed on the NEXT startup, where it no longer
# matches on-disk TASK.MD and produces a noisy "task_id mismatch" abort (and,
# pre-gate, a spurious parent error notification). A legitimate task_assign is
# consumed within seconds (active consumer + the spawn guard prevents queuing),
# so anything older than this bound is unambiguously a stale replay — drop it.
_STALE_TASK_ASSIGN_THRESHOLD_S = 120  # 2 minutes


def _redis_msg_age_seconds(msg_id: str) -> float | None:
    """Parse a Redis Stream ID (``"<ms-timestamp>-<seq>"``) and return age in seconds.

    Returns None when the ID can't be parsed — caller should treat that as
    "unknown age" and proceed (fail-open) rather than dropping the message.
    """
    if not msg_id or "-" not in msg_id:
        return None
    try:
        ms_str = msg_id.split("-", 1)[0]
        ms = int(ms_str)
        now_ms = int(time.time() * 1000)
        return max(0.0, (now_ms - ms) / 1000.0)
    except (ValueError, OverflowError):
        return None


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
        # Task-ids already executed in this process lifetime. Both the Redis
        # inbox path and the watchdog/TASK.MD path can deliver the SAME task
        # (the consumer group starts at id 0, and SpawnAgentTool both writes
        # TASK.MD and publishes task_assign). Recording each id the moment we
        # commit to running it lets the second delivery skip cleanly instead
        # of double-executing or aborting with a noisy "task_id mismatch".
        self._recent_task_ids: deque[str] = deque(maxlen=64)
        # child-task-ids that have already produced a "[Process incoming result]"
        # trigger TASK.MD in this process lifetime. Parallel to _recent_task_ids
        # but keyed on the CHILD's task_id carried by a task_result inbox message
        # (which lives in a different id-space than the parent's own tasks).
        #
        # Why this exists (deep-chain echo bug): a sub-agent ALWAYS publishes a
        # task_result to its parent's inbox, even when the parent consumed the
        # result inline via wait_for_agent. That message then sits unread while
        # the parent is mid-turn, and after the parent goes idle its runner reads
        # the inbox, sees the stale task_result, and writes a spurious
        # "[Process incoming result]" trigger — making the parent run a redundant
        # second task that echoes content already folded into its own result.
        # Recording each child task_id the moment we write a trigger for it lets
        # a re-delivered duplicate (Redis PEL replay, double-publish, or watchdog
        # re-scan of a still-final TASK.MD) skip cleanly instead of echoing.
        self._recent_child_task_ids: deque[str] = deque(maxlen=128)

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

        # Light the live topology on real state transitions. The runner runs
        # in a subprocess, so the in-memory bus is unreachable — but the bus's
        # Redis fanout relays the event to the backend's /ws/graph clients.
        self._emit_status_changed(state)

    def _emit_status_changed(self, new_state: str) -> None:
        """Fire-and-forget a ``status_changed`` graph event on a real transition.

        Best-effort: a missing event loop or a downed bus must never break the
        runner's status bookkeeping. The graph already tracks busy state via
        task_assigned/task_completed; this only sharpens idle↔running edges.
        """
        old_state = getattr(self, "_last_state", None)
        self._last_state = new_state
        if old_state == new_state:
            return
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return

        async def _emit() -> None:
            try:
                from app.backend.services.graph_events import graph_event_bus
                await graph_event_bus.emit_status_changed(
                    source=self._name,
                    old_status=old_state or "",
                    new_status=new_state,
                )
            except Exception:
                pass  # non-fatal — never break status writes

        try:
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(_emit()))
        except Exception:
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

    async def _run_task(self, task_body: str, expected_task_id: str = "") -> None:
        """Execute a single task, updating TASK.MD frontmatter on completion.

        ``expected_task_id`` is the task_id from the Redis task_assign
        message (or empty when called from the polling/watchdog path).
        When non-empty, we re-read the on-disk frontmatter and abort if
        it doesn't match — that's how we catch the "spawn A landed first,
        spawn B overwrote TASK.MD before this runner read it" race that
        produced the user-reported "agent continued the previous task and
        reported the wrong result" bug.
        """
        _fm = self._parse_task_frontmatter()
        # Cross-path dedup: the same task can be delivered by BOTH the Redis
        # inbox and the TASK.MD watchdog. The effective id is the Redis
        # message's task_id (authoritative) or, for the watchdog path, the
        # on-disk task_id. If we already ran it, skip cleanly — this is what
        # eliminates the double-execution and the "task_id mismatch" abort
        # spam without dropping any genuinely new task.
        effective_task_id = expected_task_id or str(_fm.get("task_id", "") or "")
        if effective_task_id and effective_task_id in self._recent_task_ids:
            _log.bind(agent=self._name, task_id=effective_task_id[:8]).info(
                "task_id already executed via the other delivery path — skipping duplicate"
            )
            return
        self._write_status("running", task_summary=task_body)
        # Task-id consistency check (only when we have one to compare):
        # detects the spawn-vs-spawn race + partial-write contamination
        # window. If they differ, the on-disk TASK.MD may belong to a
        # newer spawn that hasn't finished writing yet (race between Redis
        # delivery and atomic file write). Wait up to 2s with 100ms polls
        # for the correct task_id to appear before aborting.
        if expected_task_id:
            on_disk_id = str(_fm.get("task_id", "") or "")
            if on_disk_id and on_disk_id != expected_task_id:
                _log.bind(
                    agent=self._name,
                    expected=expected_task_id[:8],
                    on_disk=on_disk_id[:8],
                ).info(
                    "task_id mismatch (expected={}, on_disk={}) — "
                    "waiting for atomic write...",
                    expected_task_id[:8], on_disk_id[:8],
                )
                for _ in range(20):
                    await asyncio.sleep(0.1)
                    _fm2 = self._parse_task_frontmatter()
                    on_disk_id2 = str(_fm2.get("task_id", "") or "")
                    if on_disk_id2 == expected_task_id:
                        _log.bind(agent=self._name).info(
                            "task_id resolved after retry — atomic write completed"
                        )
                        break
                else:
                    _log.bind(
                        agent=self._name,
                        expected=expected_task_id[:8],
                        on_disk=on_disk_id[:8],
                    ).warning(
                        "task_id mismatch persisted after 2s wait — "
                        "Redis msg said {}, TASK.MD says {}. "
                        "A newer spawn overwrote our task; aborting.",
                        expected_task_id[:8], on_disk_id[:8],
                    )
                    # Best-effort signal back to the parent so they don't sit
                    # on a stale ## Result (the newer spawn's runner invocation
                    # will fill that in for the newer task).
                    try:
                        health_path = self._agent._memory_dir / "HEALTH.MD"
                        health_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(health_path, "a", encoding="utf-8") as _hf:
                            _hf.write(
                                f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}] "
                                f"task_id mismatch: expected {expected_task_id[:8]}, "
                                f"on-disk {on_disk_id2[:8]}. Aborting stale spawn.\n"
                            )
                    except Exception:
                        pass
                    # This task_id genuinely never ran (not in the dedup set)
                    # and a newer spawn has taken over TASK.MD. Signal the
                    # parent so a blocking wait_for_agent doesn't sit until
                    # timeout. We do NOT call set_task_status here — the
                    # on-disk TASK.MD belongs to the newer task and must not
                    # be clobbered with this older task's error.
                    try:
                        await self._notify_parent_via_bus(
                            f"aborted: task superseded by a newer spawn "
                            f"(task_id {expected_task_id[:8]} was overwritten)",
                            "error",
                        )
                    except Exception:
                        pass
                    return
        # Committed to running this task — record its id so a duplicate
        # delivery from the other path skips cleanly at the dedup guard above.
        if effective_task_id:
            self._recent_task_ids.append(effective_task_id)
        # Opening balance for this task's cost attribution.
        _spend_before = self._spend_snapshot()
        # Verification gate: every mutating tool call this task makes, in order.
        _mutations: list[str] = []
        _checkpoint = self._checkpoint_sha()
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

        # Snapshot pending notifications; acknowledge only after persisted success
        notifications_context = ""
        pending = []
        try:
            from app.backend.services.notification_queue import notification_queue as _nq
            pending = [n for n in _nq.pending_entries(self._agent._name)
                       if n.get("session_id", "") == (self._agent._session_id or "")]
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
            last_tps: float | None = None
            last_input: int | None = None
            last_output: int | None = None

            # Notification tasks: block destructive tools for ALL agents
            _blocked = (
                {"server_restart", "process_restart", "spawn_agent", "kill_agent", "shell_exec"}
                if task_body.startswith("[Process incoming")
                else None
            )
            # Stream events flow to the UI via BaseAgent._emit_event ->
            # Redis (session:{id}:events + agent:{name}:activity) -> relay ->
            # WebSocket. The runner no longer writes LIVE.MD; the only
            # turn-level side-effect it owns is refreshing STATUS.json on
            # each UsageStats event.
            async for event in self._agent.run_stream_with_tools(
                manage_task_file=False,
                notifications_context=notifications_context,
                blocked_tools=_blocked,
            ):
                if isinstance(event, ToolStart):
                    record = self._mutation_from_event(event)
                    if record and record not in _mutations:
                        _mutations.append(record)
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

            # Read the full response from RESULT.MD (written by _write_result).
            # This decouples result transport from MEMORY.MD, which only stores
            # short 1-sentence summaries to prevent the "double message" bug.
            result_text = await self._agent._read_file("RESULT.MD")
            result_text = result_text.strip()

            await self._agent.set_task_status("done", result=result_text or "Task completed.")
            if pending:
                try:
                    _nq.acknowledge(pending)
                except Exception as exc:
                    _log.bind(agent=self._name).warning("Notification acknowledgment failed; input retained: {}", exc)
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
                    changed_files=json.dumps(_mutations),
                    checkpoint_sha=_checkpoint,
                    verification=self._verification_verdict(_mutations, _checkpoint),
                    cost_usd=self._spend_snapshot() - _spend_before,
                    continuation=self._continuation_count(_done_fm),
                )
            except Exception as _db_exc:
                _log.bind(agent=self._name).warning(
                    "DB insert_task(done) failed (task still completed): {}", _db_exc
                )

            # ── Evaluator signal-ledger refresh (roadmap 3.2) ───────────
            # `update_ledger()` was only ever called from `propose_goals()`,
            # which only runs when a human types `yapoc propose-goals`. So the
            # ledger drifted behind REPORT.MD — it sat at round 93 against a
            # round-103 report, and a signal the evaluator had already raised
            # ("observability error counters still blind to task-level
            # failures") stayed open long after the underlying bug was fixed.
            # Refreshing here means a finished evaluation always reconciles
            # its own findings. Never allowed to fail the task.
            if self._name == "evaluator":
                try:
                    from app.utils.signal_ledger import update_ledger
                    await asyncio.to_thread(update_ledger)
                except Exception as _ledger_exc:
                    _log.bind(agent=self._name).warning(
                        "signal ledger refresh failed (non-fatal): {}", _ledger_exc
                    )

            # Publish result to parent's Redis inbox (non-blocking)
            await self._notify_parent_via_bus(result_text, "done")

            # Mark notification tasks as consumed so the poller skips them
            if task_body.startswith("[Process incoming"):
                await self._agent.mark_task_consumed()

        except TimeoutError:
            # Salvage, same principle as turn exhaustion: BaseAgent's `finally`
            # has already written whatever the agent produced to RESULT.MD, so
            # read it back rather than discarding it. A timed-out task ran for
            # its full budget (librarian's was 900s) and used to be recorded
            # with nothing but the string "Task timed out" — no way to see how
            # far it got, or whether the work was nearly done.
            _timeout_partial = ""
            try:
                _timeout_partial = (await self._agent._read_file("RESULT.MD")).strip()
            except Exception:
                _timeout_partial = ""
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
                    result_summary=_timeout_partial,
                    error_summary="Task timed out",
                    changed_files=json.dumps(_mutations),
                    checkpoint_sha=_checkpoint,
                    verification=self._verification_verdict(_mutations, _checkpoint),
                    cost_usd=self._spend_snapshot() - _spend_before,
                    continuation=self._continuation_count(_err_fm),
                )
            except Exception as _db_exc:
                _log.bind(agent=self._name).warning(
                    "DB insert_task(timeout) failed: {}", _db_exc
                )
            await self._notify_parent_via_bus("Task timed out", "error")
            if task_body.startswith("[Process incoming"):
                await self._agent.mark_task_consumed()
        except TurnLimitReached as exc:
            # Turn exhaustion is a budget event, not a failed task. Salvage the
            # work and hand it back as `partial`, then re-enqueue a continuation
            # so the agent resumes from its own progress instead of restarting.
            #
            # Before this, `except Exception` below caught it: the task became
            # `error`, the parent got only the message, and every turn of work
            # was discarded. Turn-limit errors were 19 of the 28 failures in the
            # current release and 100% of them lost their work.
            await self._handle_turn_limit(
                exc, task_body, _fm, self._spend_snapshot() - _spend_before,
                _mutations, _checkpoint,
            )
            if task_body.startswith("[Process incoming"):
                await self._agent.mark_task_consumed()
        except Exception as exc:
            _exc_partial = ""
            try:
                _exc_partial = (await self._agent._read_file("RESULT.MD")).strip()
            except Exception:
                _exc_partial = ""
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
                    result_summary=_exc_partial,
                    error_summary=str(exc),
                    changed_files=json.dumps(_mutations),
                    checkpoint_sha=_checkpoint,
                    verification=self._verification_verdict(_mutations, _checkpoint),
                    cost_usd=self._spend_snapshot() - _spend_before,
                    continuation=self._continuation_count(_exc_fm),
                )
            except Exception as _db_exc:
                _log.bind(agent=self._name).warning(
                    "DB insert_task(error) failed: {}", _db_exc
                )
            await self._notify_parent_via_bus(str(exc), "error")
            if task_body.startswith("[Process incoming"):
                await self._agent.mark_task_consumed()
        finally:
            # Stop the heartbeat coroutine so it cannot keep rewriting
            # STATUS.json (state="running", idle_since=None) after the task
            # has finished. Without this, the orphaned heartbeat clobbers
            # the post-task _write_status("idle") every 30s, which keeps
            # idle_since=None and prevents the idle-timeout branch in run()
            # from ever firing — agents would stay alive indefinitely.
            _hb_stop.set()
            try:
                await asyncio.wait_for(_hb_task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                _hb_task.cancel()
            except Exception:
                _hb_task.cancel()

    # ── Verification gate (roadmap 2.5) ────────────────────────────────

    # Tools that mutate the working tree. The agent's own calls to these are
    # the authoritative record of what a task changed — better than diffing
    # `git status`, which is global and would cross-attribute between agents
    # running concurrently.
    _MUTATING_TOOLS: dict[str, tuple[str, ...]] = {
        "file_write": ("path",),
        "file_edit": ("path",),
        "file_delete": ("path",),
        "create_skill": ("name",),
        "update_skill": ("name",),
        "delete_skill": ("name",),
    }
    # Mutations we can see happened but cannot enumerate: a shell command may
    # touch anything. Recorded so a task is never reported as "changed nothing"
    # when it in fact ran opaque commands.
    _OPAQUE_TOOLS: frozenset[str] = frozenset({"shell_exec", "execute_code"})

    @classmethod
    def _mutation_from_event(cls, event: "ToolStart") -> str | None:
        """Return a record of one mutating tool call, or None if not mutating."""
        name = getattr(event, "name", "") or ""
        params = getattr(event, "input", None) or {}
        keys = cls._MUTATING_TOOLS.get(name)
        if keys:
            for key in keys:
                value = params.get(key)
                if value:
                    return f"{name}:{value}"
            return f"{name}:<unknown>"
        if name in cls._OPAQUE_TOOLS:
            return f"{name}:<opaque>"
        return None

    def _checkpoint_sha(self) -> str:
        """SHA this task can be rolled back to, or '' when checkpointing is off."""
        try:
            from app.backend import git_safety
            handle = git_safety.read_checkpoint(self._name)
            if handle and handle.enabled and handle.sha:
                return handle.sha
        except Exception:
            pass
        return ""

    @staticmethod
    def _verification_verdict(mutations: list[str], checkpoint: str) -> str:
        """Classify a task's verifiability. Recorded on the task row.

        - `none`       the task changed nothing
        - `verified`   changes are enumerable AND a rollback point exists
        - `unanchored` changes are enumerable but there is no checkpoint
        - `opaque`     the task ran shell/code, so the change set is unknown
        """
        if not mutations:
            return "none"
        if any(m.endswith(":<opaque>") for m in mutations):
            return "opaque" if not checkpoint else "opaque+checkpoint"
        return "verified" if checkpoint else "unanchored"

    # ── Per-task cost attribution ──────────────────────────────────────

    def _spend_snapshot(self) -> float:
        """This agent's lifetime spend from USAGE.json, or 0.0 if unreadable.

        An agent runs exactly one task at a time, so the delta of this value
        across a task IS that task's cost — no cross-task overlap to untangle.
        That is what makes `tasks.cost_usd` exact, unlike `task_queue.cost_usd`
        which spans a whole delegation tree.
        """
        try:
            return float(self._agent._usage.snapshot().get("total_cost_usd", 0.0) or 0.0)
        except Exception:
            return 0.0

    # ── Turn-exhaustion salvage + continuation ─────────────────────────

    # Marker line prefixed to a continuation's ## Task body. Used to detect an
    # already-continued task on re-entry and to keep the original instruction
    # visible to the agent alongside what it already achieved.
    _CONTINUATION_HEADER = "[CONTINUATION]"
    # Section markers inside the continuation body. These deliberately do NOT
    # start with "## ": `BaseAgent.get_task_body` extracts the `## Task` section
    # with `(?=\n## |\Z)`, so a "## "-prefixed subheader here would terminate
    # the section early and the agent would receive the preamble with neither
    # the original instruction nor its own progress.
    _ORIGINAL_MARKER = "=== ORIGINAL TASK ==="
    _PROGRESS_MARKER = "=== PROGRESS SO FAR ==="

    @staticmethod
    def _neutralize_headers(text: str) -> str:
        """Blockquote line-leading markdown headers in salvaged agent output.

        Same hazard as the markers above, but from the other direction: a
        partial result that happens to contain a line like "## Findings" would
        truncate the rebuilt `## Task` section at exactly that line, silently
        cutting the agent's own progress in half. Prefixing with "> " keeps the
        text readable and valid markdown while ensuring no line starts with "#".
        """
        return re.sub(r"^(#{1,6} )", r"> \1", text, flags=re.MULTILINE)

    def _continuation_count(self, fm: dict[str, str]) -> int:
        """Read the continuation counter from TASK.MD frontmatter (0 when absent)."""
        try:
            return max(0, int(str(fm.get("continuation", "0")).strip() or "0"))
        except (TypeError, ValueError):
            return 0

    async def _handle_turn_limit(
        self,
        exc: TurnLimitReached,
        task_body: str,
        fm: dict[str, str],
        cost_usd: float = 0.0,
        mutations: list[str] | None = None,
        checkpoint_sha: str = "",
    ) -> None:
        """Record an out-of-turns task as `partial` and re-enqueue a continuation.

        Three things happen here, in order, each independently guarded so a
        failure in one does not lose the others:

        1. Salvage — RESULT.MD already holds the partial text (BaseAgent's
           `finally` writes it on every exit path), so the text is read back
           rather than reconstructed. `exc.partial_text` is the fallback.
        2. Record — a `partial` row in `tasks` carrying BOTH result_summary and
           error_summary, so the reliability scorecard can count continuations
           without mistaking them for either successes or hard failures.
        3. Continue — rewrite TASK.MD as `pending` with an incremented
           `continuation` counter; the runner's own poll loop picks it up.

        Exhausting the continuation budget is a LOUDER failure than the old
        turn-limit error, not a quieter one: the task finalizes as `error`, which
        feeds the consecutive-failure alert that `partial` deliberately does not.
        """
        partial = ""
        try:
            partial = (await self._agent._read_file("RESULT.MD")).strip()
        except Exception as _read_exc:
            _log.bind(agent=self._name).warning(
                "could not read RESULT.MD for turn-limit salvage: {}", _read_exc
            )
        if not partial:
            partial = (exc.partial_text or "").strip()

        used = self._continuation_count(self._parse_task_frontmatter() or fm)
        budget = int(getattr(settings, "max_task_continuations", 0) or 0)
        can_continue = bool(partial) and used < budget

        _log.bind(agent=self._name, continuation=used, budget=budget).info(
            "turn limit reached ({} turns), salvaged {} chars, continuing={}",
            exc.max_turns, len(partial), can_continue,
        )

        status = "partial" if can_continue else "error"
        note = (
            f"Reached the {exc.max_turns}-turn limit "
            f"(continuation {used}/{budget})."
        )
        if not can_continue:
            note += (
                " Continuation budget exhausted."
                if partial
                else " No partial output to continue from."
            )

        try:
            if status == "partial":
                await self._agent.set_task_status("partial", result=partial)
            else:
                await self._agent.set_task_status("error", error=note)
        except Exception as _st_exc:
            _log.bind(agent=self._name).warning(
                "failed to write turn-limit task status: {}", _st_exc
            )

        _tl_fm = self._parse_task_frontmatter()
        try:
            from app.utils.db import init_schema, insert_task
            init_schema()
            insert_task(
                agent=self._name,
                task_id=_tl_fm.get("task_id", "") or fm.get("task_id", ""),
                status=status,
                assigned_by=_tl_fm.get("assigned_by", "") or fm.get("assigned_by", ""),
                assigned_at=_tl_fm.get("assigned_at", "") or fm.get("assigned_at", ""),
                task_summary=task_body,
                result_summary=partial,
                error_summary=note,
                cost_usd=cost_usd,
                # `used` is the attempt this row IS, not the next one.
                continuation=used,
                changed_files=json.dumps(mutations or []),
                checkpoint_sha=checkpoint_sha,
                verification=self._verification_verdict(mutations or [], checkpoint_sha),
            )
        except Exception as _db_exc:
            _log.bind(agent=self._name).warning(
                "DB insert_task({}) failed: {}", status, _db_exc
            )

        if not can_continue:
            # Terminal: tell the parent it failed, exactly as before.
            await self._notify_parent_via_bus(note, "error")
            return

        # Re-enqueue. The parent is intentionally NOT notified — from its point
        # of view the task is still in flight, which is true.
        try:
            await self._enqueue_continuation(task_body, partial, used + 1, exc.max_turns)
        except Exception as _cont_exc:
            _log.bind(agent=self._name).warning(
                "continuation enqueue failed; finalizing as error: {}", _cont_exc
            )
            await self._agent.set_task_status("error", error=note)
            await self._notify_parent_via_bus(note, "error")

    async def _enqueue_continuation(
        self, task_body: str, partial: str, attempt: int, max_turns: int
    ) -> None:
        """Rewrite TASK.MD as a pending continuation of the same task.

        The task_id is preserved so the whole continuation chain stays one task
        to the parent, to `wait_for_agent`, and in the DB. Only `status`,
        `continuation` and the body change.
        """
        task_id = str(self._parse_task_frontmatter().get("task_id", "") or "")

        original = task_body
        marker = self._CONTINUATION_HEADER
        if original.startswith(marker):
            # Already a continuation — recover the original instruction so the
            # body does not grow by one nested copy per attempt.
            _, _, rest = original.partition(self._ORIGINAL_MARKER + "\n")
            if rest:
                original = rest.split("\n" + self._PROGRESS_MARKER)[0].strip()

        body = (
            f"{marker} attempt {attempt} of "
            f"{int(getattr(settings, 'max_task_continuations', 0) or 0)}.\n"
            f"You previously ran out of turns ({max_turns}) on this task. "
            f"Your own progress is below — continue from it, do not start over, "
            f"and do not repeat work already done.\n\n"
            f"{self._ORIGINAL_MARKER}\n{original}\n\n"
            f"{self._PROGRESS_MARKER}\n{self._neutralize_headers(partial)}\n"
        )

        content = await self._agent._read_file("TASK.MD")
        content = self._agent._update_frontmatter(
            content, status="pending", continuation=str(attempt)
        )
        # Replace the ## Task section with the continuation body. Callable
        # replacement so the partial text is treated as literal, never as a
        # regex template (same hazard set_task_status documents).
        _body = body
        content = re.sub(
            r"(## Task\n).*?(?=\n## |\Z)",
            lambda m: m.group(1) + _body,
            content,
            flags=re.DOTALL,
        )
        await self._agent._write_file("TASK.MD", content)

        # A continuation deliberately keeps the ORIGINAL task_id so the parent,
        # `wait_for_agent` and the DB all still see one task. But `_run_task`
        # records every executed id in `_recent_task_ids` and skips repeats as
        # cross-path duplicate deliveries — which would silently swallow this
        # continuation. Retire the id from that window so the re-run is allowed.
        try:
            while self._recent_task_ids and task_id in self._recent_task_ids:
                self._recent_task_ids.remove(task_id)
        except ValueError:
            pass

        _log.bind(agent=self._name, attempt=attempt).info(
            "re-enqueued task as continuation {}", attempt
        )

    async def _check_task(self) -> bool:
        """Check TASK.MD for pending status. Returns True if a task was executed."""
        status = await self._agent.get_task_status()
        if status == "pending":
            task_body = await self._agent.get_task_body()
            if task_body:
                # Write task body into TASK.MD for the agent's run loop to pick up
                await self._run_task(task_body)
                return True
            # status: pending with an empty ## Task section — a truncated or
            # half-written spawn. Leaving it pending means every later poll
            # re-reads the same unusable file forever and the agent looks
            # permanently assigned. Retire it so the next spawn starts clean.
            _log.bind(agent=self._name).warning(
                "TASK.MD is pending with an empty body — retiring the stale task"
            )
            try:
                await self._agent.set_task_status(
                    "error", error="Task was pending with an empty ## Task section."
                )
                await self._agent.mark_task_consumed()
            except Exception as _clear_exc:
                _log.bind(agent=self._name).warning(
                    "failed to retire empty pending task: {}", _clear_exc
                )
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
            # Carry task_id from the Redis message into _run_task. Without
            # this, _run_task re-reads TASK.MD's frontmatter and a second
            # spawn that landed between the message and the read would
            # silently switch the agent's perceived task. Verified at the
            # head of _run_task — mismatch = abort with a clear log line.
            expected_task_id = str(data.get("task_id", "") or "")
            # Freshness gate: drop stale task_assign replays from a previous
            # agent lifetime (reclaimed from the consumer group's PEL on
            # startup). They no longer match on-disk TASK.MD and would only
            # produce a "task_id mismatch" abort + a spurious parent error
            # notification. Fail-open when age is unknown.
            _assign_age = _redis_msg_age_seconds(msg_id)
            if _assign_age is not None and _assign_age > _STALE_TASK_ASSIGN_THRESHOLD_S:
                _log.bind(agent=self._name, task_id=expected_task_id[:8]).warning(
                    "Discarding stale task_assign (age={:.0f}s > {}s) — likely a "
                    "replay from a previous instance; not running.",
                    _assign_age, _STALE_TASK_ASSIGN_THRESHOLD_S,
                )
                await self._ack_inbox(msg_id)
                return False
            _log.bind(agent=self._name, task_id=expected_task_id[:8]).info(
                "Redis inbox: task_assign — running task ({} chars)", len(task_text)
            )
            # Mark running BEFORE acking/executing so SpawnAgentTool's
            # state=="running" guard (delegation.py) rejects a concurrent
            # spawn during the window between ACK and _run_task's own
            # status write. Closes the spawn-vs-spawn race at the source.
            self._write_status("running", task_summary=task_text)
            await self._ack_inbox(msg_id)
            await self._run_task(task_text, expected_task_id=expected_task_id)
            # Drop STATUS.json back to idle. _run_task wrote "running" at
            # entry, but only the polling-driven path (run() main loop)
            # writes "idle" after — the Redis path was leaving STATUS stuck
            # at "running" with the just-completed task_summary frozen.
            # Symptom: keeper showed state=running indefinitely after a
            # successful Redis-driven task, blocking subsequent spawn_agent
            # calls that check status before reassigning. Temporary agents
            # bypass this — they self-shutdown inside _run_task.
            if not self._temporary:
                self._write_status("idle")
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
            # Freshness gate: discard task_result messages older than the
            # threshold. These can arrive in the claimed-pending batch when a
            # previous incarnation of this agent died without ACKing — replaying
            # them now writes a stale trigger TASK.MD that ends up running
            # AFTER the agent's current task and clobbers its RESULT.MD.
            # See the planning cross-up note in claude-solution-design.md.
            _age = _redis_msg_age_seconds(msg_id)
            if _age is not None and _age > _STALE_TASK_RESULT_THRESHOLD_S:
                _log.bind(agent=self._name).warning(
                    "Discarding stale task_result from Redis (age={:.0f}s > {}s threshold): "
                    "child={} status={} msg_id={}",
                    _age,
                    _STALE_TASK_RESULT_THRESHOLD_S,
                    str(data.get("child_agent", "unknown")),
                    str(data.get("status", "done")),
                    msg_id,
                )
                await self._ack_inbox(msg_id)
                return False

            child = str(data.get("child_agent", "unknown"))
            status = str(data.get("status", "done"))
            result = str(data.get("result", ""))
            session_id = str(data.get("session_id", ""))
            # The child's task_id (NOT the parent's). Dedup on this so a
            # re-delivered task_result — Redis PEL replay, double-publish, or a
            # slow producer re-scanning a still-final TASK.MD — cannot write a
            # second "[Process incoming result]" trigger for the same completion.
            # This is the deep-chain echo shield: without it, a child result the
            # parent already folded in via wait_for_agent (or already surfaced)
            # gets re-surfaced as a spurious extra task after the parent idles.
            _child_task_id = str(data.get("task_id", "") or "")
            if _child_task_id:
                if _child_task_id in self._recent_child_task_ids:
                    _log.bind(
                        agent=self._name,
                        child=child,
                        child_task_id=_child_task_id[:8],
                        msg_id=msg_id,
                    ).info(
                        "task_result for child task {} already surfaced — "
                        "acking and skipping duplicate trigger",
                        _child_task_id[:8],
                    )
                    await self._ack_inbox(msg_id)
                    return False
                self._recent_child_task_ids.append(_child_task_id)

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
                f"task_id: {_child_task_id}\n"
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
        task_id = str(fm.get("task_id", "") or "")

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
                            "task_id": task_id,
                            "parent_task_id": fm.get("parent_task_id", ""),
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
                    task_id=task_id,
                    parent_task_id=fm.get("parent_task_id", ""),
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
        # Daemon so a stuck Observer cannot block process exit if
        # observer.stop()/join(timeout=5) in the finally block times out.
        observer.daemon = True
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
                    # Wrap _check_task so any uncaught exception (e.g. a
                    # compaction failure that escaped the inner try/except)
                    # cannot leave STATUS.json stuck at state=running.
                    # We treat the run as "ran" so the idle write below
                    # fires, then log to HEALTH.MD so the issue is visible.
                    try:
                        ran = await self._check_task()
                    except Exception as _check_exc:
                        _log.bind(agent=self._name).error(
                            "_check_task raised — forcing idle write: {}",
                            _check_exc,
                        )
                        try:
                            health_path = self._agent._memory_dir / "HEALTH.MD"
                            health_path.parent.mkdir(parents=True, exist_ok=True)
                            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                            with open(health_path, "a", encoding="utf-8") as f:
                                f.write(
                                    f"[{stamp}] ERROR: _check_task raised: "
                                    f"{type(_check_exc).__name__}: {_check_exc}\n"
                                )
                        except Exception:
                            pass
                        ran = True  # so the idle-write branch below fires
                if ran and self._temporary:
                    await self._shutdown("task complete")
                    break
                if ran:
                    self._write_status("idle")
                    # Strip task_id from TASK.MD so it cannot trigger a stale
                    # "task_id mismatch" abort on the next spawn. The task is
                    # finished — its result lives in RESULT.MD / notification_queue.
                    try:
                        fm = self._parse_task_frontmatter()
                        if fm.get("task_id"):
                            content = self._task_path.read_text(encoding="utf-8")
                            content = re.sub(
                                r"^task_id:\s*.*\n?", "", content, flags=re.MULTILINE
                            )
                            self._task_path.write_text(content, encoding="utf-8")
                    except Exception:
                        pass

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
