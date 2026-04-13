"""
NotificationPoller — background asyncio task that polls agent TASK.MD files
and enqueues completion notifications for parent agents.

Poll interval: 30 seconds (matches runner_poll_interval in settings).
"""
from __future__ import annotations

import asyncio
import logging
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
    """Extract the ## Result section from TASK.MD."""
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
    """Extract the ## Error section from TASK.MD."""
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
        # to avoid duplicate notifications on repeated polls
        self._notified: set[tuple[str, str]] = set()

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
                for parent_name in parents_to_wake:
                    try:
                        from app.utils.tools.delegation import _wake_agent_if_idle
                        await _wake_agent_if_idle(parent_name)
                    except Exception:
                        pass  # best-effort wake
            except asyncio.CancelledError:
                logger.info("NotificationPoller: poll loop cancelled")
                break
            except Exception as exc:
                logger.error("NotificationPoller: unexpected error in poll loop: %s", exc, exc_info=True)
                # Continue polling despite errors

    def _poll_once(self) -> list[str]:
        """Synchronous poll — called in executor to avoid blocking event loop.

        Returns list of parent agent names that were notified (for wake-up).
        """
        if not self._agents_dir.exists():
            return []

        parents_to_wake: list[str] = []
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

            completed_at = str(fm.get("completed_at", ""))
            dedup_key = (agent_name, completed_at)
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
                continue

            result = _read_result_section(task_md) if status == "done" else ""
            error = _read_error_section(task_md) if status == "error" else ""

            self._queue.enqueue(
                parent_agent=parent,
                child_agent=agent_name,
                status=status,
                result=result,
                error=error,
            )
            self._notified.add(dedup_key)
            parents_to_wake.append(parent)
            logger.info(
                "NotificationPoller: %s completed (%s) → notifying parent %s",
                agent_name,
                status,
                parent,
            )

        # Periodically purge old consumed notifications
        self._queue.purge_consumed(keep_last=200)
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
