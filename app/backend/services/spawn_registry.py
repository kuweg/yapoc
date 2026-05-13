"""
SpawnRegistry — tracks parent/child agent spawn relationships.

Persists to data/spawn_registry.json so relationships survive backend restarts.

Cross-process safe: every write reloads from disk under an fcntl file lock
and merges before saving. Without this, a subprocess agent calling
``register_spawn(builder, planning)`` would silently wipe the server
process's ``register_spawn(planning, master)`` entry (each process holds
its own in-memory dict; ``_save()`` previously dumped only what *that*
process had registered, so the last writer won the entire file).
"""
from __future__ import annotations

import fcntl
import json
import logging
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Absolute path anchored to project root so subprocess agents launched
# from arbitrary CWDs all read/write the same file.
_REGISTRY_PATH = settings.project_root / "data" / "spawn_registry.json"


class SpawnRegistry:
    """Cross-process-safe registry mapping child agent names to their parent
    agent names.
    """

    def __init__(self, path: Path = _REGISTRY_PATH) -> None:
        self._path = path
        self._lock = Lock()
        self._data: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Disk-authoritative transaction
    # ------------------------------------------------------------------

    @contextmanager
    def _disk_transaction(self, *, readonly: bool = False):
        """Acquire cross-process file lock, reload from disk, yield, save on exit.

        Mirrors the NotificationQueue pattern. Critical: ``yield self._data``
        gives the caller the *freshly-reloaded* dict so any mutation it
        performs is layered on top of other processes' writes, not on top
        of stale local state.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.with_suffix(".lock")
        lock_fd = open(lock_path, "w")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            # Reload from disk
            if self._path.exists():
                try:
                    self._data = json.loads(self._path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    self._data = {}
            else:
                self._data = {}
            yield self._data
            if not readonly:
                try:
                    tmp = self._path.with_suffix(".tmp")
                    tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
                    tmp.replace(self._path)
                except Exception as exc:
                    logger.error("SpawnRegistry: failed to save: %s", exc)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Ensure data directory exists and seed in-memory dict from disk.

        Every other operation now reloads under the file lock, so this is
        primarily a startup logging hook.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
                logger.info(
                    "SpawnRegistry loaded %d entries from %s",
                    len(self._data),
                    self._path,
                )
            except Exception as exc:
                logger.warning(
                    "SpawnRegistry: failed to load %s: %s — starting fresh",
                    self._path,
                    exc,
                )
                self._data = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_spawn(self, parent_agent: str, child_agent: str) -> None:
        """Record that parent_agent spawned child_agent. Cross-process safe."""
        with self._lock:
            with self._disk_transaction() as data:
                data[child_agent] = parent_agent
        logger.debug("SpawnRegistry: %s -> %s registered", parent_agent, child_agent)

    def get_parent(self, child_agent: str) -> Optional[str]:
        """Return the parent agent name for child_agent, or None if unknown.

        Reads through the file lock so we see writes from other processes.
        """
        with self._lock:
            with self._disk_transaction(readonly=True) as data:
                return data.get(child_agent)

    def remove(self, child_agent: str) -> None:
        """Remove a child entry (e.g. after notification delivered)."""
        with self._lock:
            with self._disk_transaction() as data:
                data.pop(child_agent, None)

    def all_entries(self) -> dict[str, str]:
        """Return a snapshot of all entries."""
        with self._lock:
            with self._disk_transaction(readonly=True) as data:
                return dict(data)


# Module-level singleton
registry = SpawnRegistry()
