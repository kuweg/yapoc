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

            # Inject user source so the LLM knows where the message came from
            source_line = f"[User source: {source}]" if source else ""
            combined_context = "\n\n".join(
                filter(None, [source_line, notifications_context])
            )

            self._write_status("running", task_summary=task)
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
                self._session_id = previous_session_id
                self._write_status("idle")


# Module-level singleton
master_agent = MasterAgent()
