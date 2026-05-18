import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from app.agents.base import BaseAgent
from app.utils import AGENTS_DIR
from app.utils.adapters import Message, StreamEvent


class MasterAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(AGENTS_DIR / "master")
        self._run_lock = asyncio.Lock()
        self._started_at: str | None = None
        # Mark master as idle immediately (it runs in-process, not via AgentRunner)
        self._write_status("idle")

    # ── Lifecycle accessors ──────────────────────────────────────────────

    def is_busy(self) -> bool:
        """True if master is currently inside handle_task / handle_task_stream.

        This is the authoritative concurrency check. STATUS.json is a UI
        denormalization and may be stale (file write fails, race with lock,
        etc.) — use this method for routing decisions.
        """
        return self._run_lock.locked()

    # ── STATUS.json helpers ──────────────────────────────────────────────

    def _write_status(self, state: str, task_summary: str = "") -> None:
        """Write STATUS.json atomically so the UI can track master's state.

        Master runs in-process (embedded in the FastAPI server), so it never
        goes through AgentRunner. We write STATUS.json manually here using the
        same format AgentRunner uses, with os.getpid() as the PID (the server
        process PID — always alive while master is alive).
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if self._started_at is None:
            self._started_at = now
        data = {
            "state": state,
            "pid": os.getpid(),
            "task_summary": task_summary,
            "started_at": self._started_at,
            "updated_at": now,
            "idle_since": now if state == "idle" else None,
        }
        status_path = self._dir / "STATUS.json"
        try:
            fd, tmp = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
            try:
                os.write(fd, json.dumps(data, indent=2).encode())
                os.close(fd)
                os.replace(tmp, status_path)
            except Exception:
                try:
                    os.close(fd)
                except OSError:
                    pass
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
        except Exception:
            # Best-effort — don't crash the server if STATUS.json can't be written
            pass

    # ── Proactive delegation polling ─────────────────────────────────────

    def _outstanding_delegations(self, max_entries: int = 6) -> list[dict]:
        """Scan agents/* for tasks master spawned that are still in flight.

        Returns a list of dicts: {agent, state, task_summary, status, age_s}.
        Bounded by `max_entries` so context doesn't bloat when many agents
        are running. Pure file I/O — no network, no Redis. Tolerates
        missing/malformed STATUS.json + TASK.MD silently (best-effort).

        Used by handle_task_stream to surface in-flight work to master at
        the start of each turn — closes the "blind between notifications"
        gap without changing the async delivery model.
        """
        out: list[dict] = []
        agents_root = self._dir.parent
        if not agents_root.exists():
            return out
        now = datetime.now(timezone.utc)
        for agent_dir in sorted(agents_root.iterdir()):
            if not agent_dir.is_dir() or agent_dir.name in {"base", "master", "shared", "security"}:
                continue
            status_path = agent_dir / "STATUS.json"
            task_path = agent_dir / "TASK.MD"
            if not status_path.exists() or not task_path.exists():
                continue
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            state = status.get("state", "")
            if state not in {"running", "spawning"}:
                continue
            try:
                task_body = task_path.read_text(encoding="utf-8")
            except OSError:
                continue
            # Frontmatter scan — cheap, no YAML lib needed
            assigned_by = ""
            task_status = ""
            if task_body.startswith("---"):
                end = task_body.find("---", 3)
                if end > 0:
                    header = task_body[3:end]
                    for line in header.splitlines():
                        if ":" not in line:
                            continue
                        k, v = line.split(":", 1)
                        k = k.strip()
                        v = v.strip()
                        if k == "assigned_by":
                            assigned_by = v
                        elif k == "status":
                            task_status = v
            if assigned_by != "master":
                continue
            # Compute age from STATUS.json updated_at if present
            age_s: float | None = None
            updated = status.get("updated_at") or status.get("started_at")
            if updated:
                try:
                    started = datetime.strptime(updated, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    age_s = (now - started).total_seconds()
                except ValueError:
                    age_s = None
            out.append({
                "agent": agent_dir.name,
                "state": state,
                "status": task_status or state,
                "task_summary": status.get("task_summary", "") or "",
                "age_s": age_s,
            })
            if len(out) >= max_entries:
                break
        return out

    @staticmethod
    def _format_outstanding(entries: list[dict]) -> str:
        if not entries:
            return ""
        lines = ["[OUTSTANDING DELEGATIONS — sub-agents you spawned that are still running]"]
        for e in entries:
            age = f"{int(e['age_s'])}s ago" if e.get("age_s") is not None else "unknown age"
            summary = (e.get("task_summary") or "").strip().splitlines()
            summary_line = summary[0][:120] if summary else "(no summary)"
            lines.append(f"- {e['agent']}: state={e['state']} status={e['status']} ({age}) — {summary_line}")
        lines.append("(These have NOT completed yet. Use `check_task_status` or `wait_for_agent` if you need their result now.)")
        return "\n".join(lines)

    # ── Task handling ────────────────────────────────────────────────────

    async def handle_task(
        self, task: str, history: list[Message] | None = None,
        source: str | None = None,
        session_id: str | None = None,
    ) -> str:
        async with self._run_lock:
            previous_session_id = self._session_id
            if session_id is not None:
                self._session_id = session_id
            self._write_status("running", task_summary=task)
            try:
                await self.set_task(task)
                return await self.run(history=history)
            finally:
                self._session_id = previous_session_id
                self._write_status("idle")

    async def handle_task_stream(
        self,
        task: str,
        history: list[Message] | None = None,
        source: str | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        from app.backend.services.notification_queue import notification_queue
        async with self._run_lock:
            previous_session_id = self._session_id
            if session_id is not None:
                self._session_id = session_id

            # Drain any results pushed by sub-agents via notify_parent.
            # When session_id is bound, only consume that session's notifications.
            pending = notification_queue.drain("master", session_id=self._session_id)
            notifications_context = ""
            if pending:
                lines = ["[SYSTEM NOTIFICATION — sub-agent results]"]
                for n in pending:
                    label = "DONE" if n["status"] == "done" else "ERROR"
                    content = n["result"] if n["status"] == "done" else n["error"]
                    lines.append(f"\n### Agent: {n['child_agent']} — {label}\n{content}")
                notifications_context = "\n".join(lines)

            # Hydrate history from a persisted compaction checkpoint when
            # the session was previously compacted. Re-doing the compact on
            # every resume is wasteful — the SUMMARY.json sidecar already
            # holds the anchor + facts + narrative summary from the last
            # auto-compact. We splice: [anchor, synth, ...recent tail] so
            # master immediately sees the prior state without an LLM call.
            #
            # Match criterion: incoming history's first user message must
            # equal the persisted anchor. If they diverge (new session that
            # happens to reuse an id), we skip hydration rather than mix
            # unrelated conversations.
            if history and self._session_id:
                try:
                    from app.cli.sessions import read_summary as _read_summary
                    _summary_data = _read_summary(self._session_id)
                except Exception:
                    _summary_data = None
                if _summary_data:
                    _anchor = _summary_data.get("anchor") or {}
                    _synth = _summary_data.get("synth") or {}
                    _anchor_content = str(_anchor.get("content", ""))
                    # Find first user message in incoming history
                    _first_user_idx = next(
                        (i for i, m in enumerate(history) if m.role == "user"),
                        -1,
                    )
                    if (
                        _first_user_idx >= 0
                        and _anchor_content
                        and history[_first_user_idx].content == _anchor_content
                    ):
                        # How many recent messages to keep verbatim during
                        # hydration. Use the same tail size as the compact —
                        # if user has added new turns since the checkpoint,
                        # those are all preserved (we only ever drop the
                        # already-compacted middle).
                        from app.config import settings as _s
                        _tail_n = getattr(_s, "compact_preserve_tail_n", 8)
                        _saved_count = int(_summary_data.get("msg_count_at_compact", 0))
                        # Anything past the saved compact-point is new and
                        # must be preserved verbatim. Anything before is
                        # already in the synth msg, so drop it.
                        if _saved_count > 0 and len(history) > _saved_count:
                            new_since_compact = history[_saved_count:]
                        else:
                            # No new turns since compact — preserve at most
                            # the last K to seed continuity.
                            new_since_compact = history[-_tail_n:] if len(history) > _tail_n else history[1:]
                        # Build hydrated history: anchor + synth + new tail.
                        from app.utils.adapters import Message as _Message
                        hydrated: list[_Message] = [
                            _Message(role="user", content=_anchor_content),
                            _Message(role=_synth.get("role", "user"), content=str(_synth.get("content", ""))),
                        ]
                        hydrated.extend(new_since_compact)
                        history = hydrated

            # Inject user source so the LLM knows where the message came from
            source_line = f"[User source: {source}]" if source else ""
            # Proactive polling: list any sub-agents master spawned that are
            # still in flight. Without this, master sits blind between
            # notifications — it knows what completed but not what's still
            # working. Surfacing this each turn lets master decide whether
            # to wait, ping, or move on. Pure file I/O — no LLM call.
            outstanding_context = self._format_outstanding(self._outstanding_delegations())
            combined_context = "\n\n".join(
                filter(None, [source_line, notifications_context, outstanding_context])
            )

            self._write_status("running", task_summary=task)
            # Thread task source through so run_stream_with_tools can gate
            # autonomous-source runs on the daily budget + stuck detector.
            self._task_source = source
            try:
                await self.set_task(task)
                # Block destructive tools during notification processing
                _blocked = (
                    {"server_restart", "process_restart", "spawn_agent", "kill_agent", "shell_exec"}
                    if source == "notification"
                    else None
                )
                async for event in self.run_stream_with_tools(
                    history=history,
                    notifications_context=combined_context,
                    blocked_tools=_blocked,
                ):
                    yield event
            finally:
                # Belt-and-suspenders morning report — the system:tasks Redis
                # subscriber (app/backend/morning_report_listener.py) is the
                # primary trigger; this fallback always fires. Wrap in
                # asyncio.to_thread + create_task so the report writer's
                # synchronous I/O can't starve the event loop or delay the
                # finally block from completing.
                _src_lower = (source or "").lower()
                if _src_lower in ("cron", "goal", "doctor", "webhook"):
                    try:
                        import asyncio as _asyncio
                        from app.backend.morning_report import write_morning_report
                        _asyncio.create_task(_asyncio.to_thread(
                            write_morning_report, "goal_completed", {
                                "source": _src_lower,
                                "task_preview": (task or "")[:160],
                                "via": "master.handle_task_stream",
                            },
                        ))
                    except Exception:
                        pass  # never let report writes break the task path
                self._task_source = None
                self._session_id = previous_session_id
                self._write_status("idle")


# Module-level singleton
master_agent = MasterAgent()
