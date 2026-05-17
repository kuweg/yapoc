"""
NotificationPoller — background asyncio task that polls agent TASK.MD files
and enqueues completion notifications for parent agents.

Poll interval: 30 seconds (matches runner_poll_interval in settings).
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
from pathlib import Path
from typing import Optional

import yaml

from app.backend.services.spawn_registry import SpawnRegistry, registry as default_registry
from app.backend.services.notification_queue import NotificationQueue, notification_queue as default_queue

logger = logging.getLogger(__name__)

# Agents whose completions should NOT trigger notifications (they are top-level)
_TOP_LEVEL_AGENTS = frozenset({"master"})

# TASK.MD statuses that indicate completion
_TERMINAL_STATUSES = frozenset({"done", "error"})

# Fix 3.5: persistent dedup set so notifications already enqueued survive restart.
_NOTIFIED_PATH = Path("data/poller_notified.json")
_NOTIFIED_MAX_ENTRIES = 2000  # cap to prevent unbounded growth


def _load_notified() -> set[tuple[str, str]]:
    """Load the persistent _notified set from disk. Returns empty on failure."""
    try:
        if not _NOTIFIED_PATH.exists():
            return set()
        raw = json.loads(_NOTIFIED_PATH.read_text(encoding="utf-8"))
        return {(str(a), str(b)) for a, b in raw}
    except Exception as exc:
        logger.warning("NotificationPoller: failed to load %s: %s", _NOTIFIED_PATH, exc)
        return set()


def _save_notified(notified: set[tuple[str, str]]) -> None:
    """Persist the _notified set atomically with fcntl-protected write."""
    try:
        _NOTIFIED_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Cap size: keep most recent _NOTIFIED_MAX_ENTRIES entries.
        items = list(notified)
        if len(items) > _NOTIFIED_MAX_ENTRIES:
            items = items[-_NOTIFIED_MAX_ENTRIES:]
        lock_path = _NOTIFIED_PATH.with_suffix(".lock")
        with open(lock_path, "w") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                tmp = _NOTIFIED_PATH.with_suffix(".tmp")
                tmp.write_text(json.dumps([list(t) for t in items]), encoding="utf-8")
                os.replace(tmp, _NOTIFIED_PATH)
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
    except Exception as exc:
        logger.warning("NotificationPoller: failed to save %s: %s", _NOTIFIED_PATH, exc)


def _read_task_frontmatter(task_md_path: Path) -> Optional[dict]:
    """Read and parse YAML frontmatter from a TASK.MD file. Returns None on failure."""
    try:
        content = task_md_path.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return None
        # Extract frontmatter between first --- and second ---
        parts = content.split("---", 2)
        if len(parts) < 3:
            return None
        return yaml.safe_load(parts[1]) or {}
    except Exception as exc:
        logger.debug("NotificationPoller: failed to read %s: %s", task_md_path, exc)
        return None


def _read_result_section(task_md_path: Path) -> str:
    """Extract the ## Result section from TASK.MD.

    Kept for legacy UI/result-collection paths. Notification producers should
    use `_read_result_text` so dedup byte-comparison works across all paths.
    """
    try:
        content = task_md_path.read_text(encoding="utf-8")
        if "## Result" in content:
            result_part = content.split("## Result", 1)[1]
            # Stop at next ## section if present
            if "\n## " in result_part:
                result_part = result_part.split("\n## ", 1)[0]
            return result_part.strip()
    except Exception:
        pass
    return ""


def _read_error_section(task_md_path: Path) -> str:
    """Extract the ## Error section from TASK.MD.

    Kept for legacy UI/result-collection paths. Notification producers should
    use `_read_error_text` so dedup byte-comparison works across all paths.
    """
    try:
        content = task_md_path.read_text(encoding="utf-8")
        if "## Error" in content:
            error_part = content.split("## Error", 1)[1]
            if "\n## " in error_part:
                error_part = error_part.split("\n## ", 1)[0]
            return error_part.strip()
    except Exception:
        pass
    return ""


def _read_result_text(agent_dir: Path) -> str:
    """Fix 3.2: canonical notification payload source.

    All notification producers (runner._notify_parent_via_bus, NotifyParentTool,
    NotificationPoller) read result text from RESULT.MD so that dedup in
    notification_queue.enqueue can compare bytes correctly. TASK.MD's
    ## Result section is a denormalization written separately and may differ
    by whitespace / XML-stripping artifacts.

    Falls back to TASK.MD's ## Result when RESULT.MD is missing or empty.
    """
    result_md = agent_dir / "RESULT.MD"
    try:
        if result_md.exists():
            text = result_md.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception:
        pass
    # Fallback for agents that haven't written RESULT.MD yet
    return _read_result_section(agent_dir / "TASK.MD")


def _read_error_text(agent_dir: Path) -> str:
    """Fix 3.2: canonical error payload source. RESULT.MD is not written on
    error paths; the runner sets ## Error in TASK.MD via set_task_status.
    Falls back to ERROR.MD if present, otherwise TASK.MD's ## Error.
    """
    error_md = agent_dir / "ERROR.MD"
    try:
        if error_md.exists():
            text = error_md.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception:
        pass
    return _read_error_section(agent_dir / "TASK.MD")


class NotificationPoller:
    """
    Polls all agent TASK.MD files every poll_interval seconds.
    When a child agent completes (status: done/error), looks up its parent
    in the SpawnRegistry and enqueues a notification in the NotificationQueue.
    """

    def __init__(
        self,
        agents_dir: Path,
        registry: SpawnRegistry = default_registry,
        queue: NotificationQueue = default_queue,
        poll_interval: int = 30,
    ) -> None:
        self._agents_dir = agents_dir
        self._registry = registry
        self._queue = queue
        self._poll_interval = poll_interval
        self._task: Optional[asyncio.Task] = None
        # Track which (agent, completed_at) pairs we've already notified
        # to avoid duplicate notifications on repeated polls.
        # Fix 3.5: persisted to disk so it survives restart.
        self._notified: set[tuple[str, str]] = _load_notified()
        self._notified_dirty: bool = False

    def start(self) -> None:
        """Start the background polling task."""
        if self._task is not None and not self._task.done():
            logger.warning("NotificationPoller: already running")
            return
        self._task = asyncio.create_task(self._poll_loop(), name="notification_poller")
        logger.info(
            "NotificationPoller: started (interval=%ds, agents_dir=%s)",
            self._poll_interval,
            self._agents_dir,
        )

    def stop(self) -> None:
        """Cancel the background polling task."""
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("NotificationPoller: stopped")

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while True:
            try:
                await asyncio.sleep(self._poll_interval)
                parents_to_wake = await asyncio.get_event_loop().run_in_executor(
                    None, self._poll_once
                )
                # Wake idle parent agents so they process notifications promptly
                for parent_name, session_id in parents_to_wake:
                    try:
                        from app.utils.tools.delegation import _wake_agent_if_idle
                        await _wake_agent_if_idle(parent_name, session_id=session_id)
                    except Exception:
                        pass  # best-effort wake
            except asyncio.CancelledError:
                logger.info("NotificationPoller: poll loop cancelled")
                break
            except Exception as exc:
                logger.error("NotificationPoller: unexpected error in poll loop: %s", exc, exc_info=True)
                # Continue polling despite errors

    def _poll_once(self) -> list[tuple[str, str]]:
        """Synchronous poll — called in executor to avoid blocking event loop.

        Returns list of (parent_agent, session_id) pairs that were notified
        (for wake-up).
        """
        if not self._agents_dir.exists():
            return []

        parents_to_wake: list[tuple[str, str]] = []
        for agent_dir in self._agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            agent_name = agent_dir.name
            if agent_name in _TOP_LEVEL_AGENTS:
                continue  # master notifies itself via existing mechanism

            task_md = agent_dir / "TASK.MD"
            if not task_md.exists():
                continue

            fm = _read_task_frontmatter(task_md)
            if fm is None:
                continue

            status = fm.get("status", "")
            if status not in _TERMINAL_STATUSES:
                continue

            # Skip tasks already marked consumed (post-restart re-detection guard)
            consumed_at = fm.get("consumed_at", "")
            if consumed_at:
                continue

            completed_at = str(fm.get("completed_at", ""))
            task_id = str(fm.get("task_id", ""))
            dedup_marker = completed_at or task_id or status
            dedup_key = (agent_name, dedup_marker)
            if dedup_key in self._notified:
                continue  # Already processed this completion

            # Look up parent
            parent = self._registry.get_parent(agent_name)
            if parent is None:
                # Fall back to assigned_by field in frontmatter
                parent = fm.get("assigned_by")

            if parent is None or parent == agent_name:
                logger.debug(
                    "NotificationPoller: %s completed but no parent found — skipping",
                    agent_name,
                )
                self._notified.add(dedup_key)
                self._notified_dirty = True
                continue

            # Fix 3.2: read from RESULT.MD/ERROR.MD (canonical) rather than
            # TASK.MD's denormalized sections, so dedup byte-comparison works.
            result = _read_result_text(agent_dir) if status == "done" else ""
            error = _read_error_text(agent_dir) if status == "error" else ""

            self._queue.enqueue(
                parent_agent=parent,
                child_agent=agent_name,
                status=status,
                result=result,
                error=error,
                session_id=str(fm.get("session_id", "") or ""),
            )
            self._notified.add(dedup_key)
            self._notified_dirty = True
            parents_to_wake.append((parent, str(fm.get("session_id", "") or "")))
            logger.info(
                "NotificationPoller: %s completed (%s) → notifying parent %s",
                agent_name,
                status,
                parent,
            )

        # Periodically purge old consumed notifications
        self._queue.purge_consumed(keep_last=200)
        # Fix 3.5: persist dedup set if anything changed this poll.
        if self._notified_dirty:
            _save_notified(self._notified)
            self._notified_dirty = False
        return parents_to_wake


# Module-level singleton (configured at startup with actual agents_dir)
_poller: Optional[NotificationPoller] = None


def create_poller(agents_dir: Path, poll_interval: int = 30) -> NotificationPoller:
    """Create and store the module-level poller singleton."""
    global _poller
    _poller = NotificationPoller(agents_dir=agents_dir, poll_interval=poll_interval)
    return _poller


def get_poller() -> Optional[NotificationPoller]:
    """Return the module-level poller singleton."""
    return _poller
