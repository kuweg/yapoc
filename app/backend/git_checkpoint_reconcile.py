"""Attempt safe checkpoint reconciliation after interrupted execution.

The current shared-workspace backend refuses automatic rollback. Retain those
checkpoints for deliberate recovery; never clear a handle after a refusal.
"""
from __future__ import annotations

import re
from typing import Iterable

from loguru import logger as _log

from app.backend.git_safety import (
    clear_checkpoint,
    read_checkpoint,
    rollback_to,
)
from app.config import settings

# Agent names are simple slugs (e.g. builder, planning-doctor-2). Reject
# anything that could traverse paths or isn't slug-shaped before we touch
# files under app/agents/.
_AGENT_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


async def reconcile_stale_checkpoints(
    stale_agent_names: Iterable[str],
    reason: str = "backend crash mid-task; stale checkpoint auto-reconciled at startup",
) -> list[str]:
    """Clear a checkpoint only when rollback confirms it actually succeeded."""
    reconciled: list[str] = []
    for name in stale_agent_names or ():
        if not isinstance(name, str) or not _AGENT_SLUG_RE.match(name):
            _log.warning(
                "git_checkpoint_reconcile: skipping invalid agent name {!r}",
                name,
            )
            continue
        agent_dir = settings.agents_dir / name
        if not agent_dir.is_dir():
            _log.debug(
                "git_checkpoint_reconcile: agent dir missing for {!r}; skipping",
                name,
            )
            continue
        try:
            handle = read_checkpoint(name)
            if handle is None:
                # No orphaned checkpoint; nothing to reconcile.
                continue
            _log.bind(agent=name, sha=handle.sha[:12]).info(
                "git_checkpoint_reconcile: checking stale checkpoint for {}",
                name,
            )
            if await rollback_to(handle, reason):
                clear_checkpoint(name)
                reconciled.append(name)
        except Exception:
            _log.exception(
                "git_checkpoint_reconcile: reconcile failed for agent {}",
                name,
            )

    if reconciled:
        _log.info(
            "git_checkpoint_reconcile: reconciled stale checkpoints for {} agents: {}",
            len(reconciled), reconciled,
        )
    return reconciled
