"""
SpawnRegistry — tracks parent/child agent spawn relationships.

Persists to data/spawn_registry.json so relationships survive backend restarts.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path("data/spawn_registry.json")


class SpawnRegistry:
    """Thread-safe registry mapping child agent names to their parent agent names."""

    def __init__(self, path: Path = _REGISTRY_PATH) -> None:
        self._path = path
        self._lock = Lock()
        self._data: dict[str, str] = {}  # child_agent -> parent_agent

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load registry from disk (call once at startup)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            try:
                with self._path.open() as f:
                    self._data = json.load(f)
                logger.info("SpawnRegistry loaded %d entries from %s", len(self._data), self._path)
            except Exception as exc:
                logger.warning("SpawnRegistry: failed to load %s: %s — starting fresh", self._path, exc)
                self._data = {}
        else:
            self._data = {}

    def _save(self) -> None:
        """Persist registry to disk (must be called with lock held)."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2))
            tmp.replace(self._path)
        except Exception as exc:
            logger.error("SpawnRegistry: failed to save: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_spawn(self, parent_agent: str, child_agent: str) -> None:
        """Record that parent_agent spawned child_agent."""
        with self._lock:
            self._data[child_agent] = parent_agent
            self._save()
        logger.debug("SpawnRegistry: %s -> %s registered", parent_agent, child_agent)

    def get_parent(self, child_agent: str) -> Optional[str]:
        """Return the parent agent name for child_agent, or None if unknown."""
        with self._lock:
            return self._data.get(child_agent)

    def remove(self, child_agent: str) -> None:
        """Remove a child entry (e.g. after notification delivered)."""
        with self._lock:
            self._data.pop(child_agent, None)
            self._save()

    def all_entries(self) -> dict[str, str]:
        """Return a snapshot of all entries."""
        with self._lock:
            return dict(self._data)


# Module-level singleton
registry = SpawnRegistry()
