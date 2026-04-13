"""
NotificationQueue — persists pending task-completion notifications.

Cross-process safe: every operation reloads from disk under a file lock,
so subprocess agents and the main server share one authoritative queue.

Each notification is a dict with:
  - parent_agent: str   — agent to notify
  - child_agent: str    — agent that completed
  - status: str         — "done" or "error"
  - result: str         — result text (may be empty)
  - error: str          — error text (may be empty)
  - completed_at: str   — ISO timestamp
  - consumed: bool      — True once injected into parent's context
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import TypedDict

logger = logging.getLogger(__name__)

_QUEUE_PATH = Path("data/notification_queue.json")


class Notification(TypedDict):
    parent_agent: str
    child_agent: str
    status: str
    result: str
    error: str
    completed_at: str
    consumed: bool


class NotificationQueue:
    """Thread-safe, cross-process-safe persistent queue of task-completion notifications.

    Uses fcntl.flock for cross-process file locking and reloads from disk on
    every operation so that subprocess agents and the main server process share
    the same authoritative queue state.
    """

    def __init__(self, path: Path = _QUEUE_PATH) -> None:
        self._path = path
        self._lock = Lock()
        self._items: list[Notification] = []

    # ------------------------------------------------------------------
    # Disk-authoritative transaction
    # ------------------------------------------------------------------

    @contextmanager
    def _disk_transaction(self, *, readonly: bool = False):
        """Acquire cross-process file lock, reload from disk, yield, save on exit.

        If readonly=True, skip the save on exit (used by pending_count).
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.with_suffix(".lock")
        lock_fd = open(lock_path, "w")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            # Reload from disk
            if self._path.exists():
                try:
                    self._items = json.loads(self._path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    self._items = []
            else:
                self._items = []
            yield self._items
            # Save back to disk (unless readonly)
            if not readonly:
                try:
                    tmp = self._path.with_suffix(".tmp")
                    tmp.write_text(json.dumps(self._items, indent=2), encoding="utf-8")
                    os.replace(tmp, self._path)
                except Exception as exc:
                    logger.error("NotificationQueue: failed to save: %s", exc)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Ensure data directory exists (called at startup for compatibility).

        Every operation now reads from disk, so no one-time load is needed.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Log current state for startup diagnostics
        if self._path.exists():
            try:
                items = json.loads(self._path.read_text(encoding="utf-8"))
                unconsumed = sum(1 for n in items if not n.get("consumed"))
                logger.info(
                    "NotificationQueue loaded %d items (%d unconsumed) from %s",
                    len(items),
                    unconsumed,
                    self._path,
                )
            except Exception as exc:
                logger.warning("NotificationQueue: failed to read %s: %s", self._path, exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(
        self,
        parent_agent: str,
        child_agent: str,
        status: str,
        result: str = "",
        error: str = "",
    ) -> None:
        """Add a new notification to the queue."""
        notification: Notification = {
            "parent_agent": parent_agent,
            "child_agent": child_agent,
            "status": status,
            "result": result,
            "error": error,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "consumed": False,
        }
        with self._lock:
            with self._disk_transaction() as items:
                # Dedup: skip if an unconsumed notification for this (parent, child) pair exists.
                # Prevents double-delivery when notify_parent tool and NotificationPoller both fire.
                for existing in items:
                    if (
                        existing["parent_agent"] == parent_agent
                        and existing["child_agent"] == child_agent
                        and not existing["consumed"]
                    ):
                        return
                items.append(notification)
        logger.info(
            "NotificationQueue: enqueued notification for %s (child=%s, status=%s)",
            parent_agent,
            child_agent,
            status,
        )

    def drain(self, parent_agent: str) -> list[Notification]:
        """Return all unconsumed notifications for parent_agent and mark them consumed."""
        with self._lock:
            with self._disk_transaction() as items:
                pending = [n for n in items if n["parent_agent"] == parent_agent and not n["consumed"]]
                for n in pending:
                    n["consumed"] = True
        return pending

    def pending_count(self, parent_agent: str) -> int:
        """Return count of unconsumed notifications for parent_agent."""
        with self._lock:
            with self._disk_transaction(readonly=True):
                return sum(
                    1 for n in self._items
                    if n["parent_agent"] == parent_agent and not n["consumed"]
                )

    def purge_consumed(self, keep_last: int = 100) -> None:
        """Remove old consumed notifications, keeping the most recent keep_last."""
        with self._lock:
            with self._disk_transaction() as items:
                consumed = [n for n in items if n["consumed"]]
                unconsumed = [n for n in items if not n["consumed"]]
                trimmed_consumed = consumed[-keep_last:] if len(consumed) > keep_last else consumed
                self._items[:] = trimmed_consumed + unconsumed


# Module-level singleton
notification_queue = NotificationQueue()
