"""
ticket_service.py — Shared ticket store service for YAPOC.

Pure utility module with NO FastAPI dependencies — safe to import from
agent utilities (delegation.py, base/__init__.py) without circular imports.

Uses fcntl file locking (same pattern as NotificationQueue) to prevent
race conditions when multiple processes read/write tickets.json.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def get_ticket_store_path() -> Path:
    """Return the canonical path to the ticket JSON store."""
    # Resolve relative to this file: app/backend/services/ -> app/ -> data/
    return Path(__file__).parent.parent.parent / "data" / "tickets.json"


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------

# Maps TASK.MD frontmatter status → ticket board status
TASK_STATUS_MAP: dict[str, str] = {
    "pending":  "backlog",
    "running":  "in_progress",
    "done":     "done",
    "error":    "error",
    "consumed": "done",
}

# Agents that are infrastructure only — skip ticket creation for them
_INFRA_AGENTS = {"base"}


# ---------------------------------------------------------------------------
# File-locking context manager
# ---------------------------------------------------------------------------

@contextmanager
def _locked_store(path: Path, *, readonly: bool = False):
    """Acquire an exclusive cross-process file lock on the ticket store.

    Yields the loaded list[dict]. On exit (unless readonly), saves back to disk.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        # Load current state from disk
        if path.exists():
            try:
                tickets: list[dict] = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                tickets = []
        else:
            tickets = []

        yield tickets

        if not readonly:
            # Atomic write via temp file + rename
            tmp = path.with_suffix(".tmp")
            try:
                tmp.write_text(
                    json.dumps(tickets, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                os.replace(tmp, path)
            except Exception as exc:
                logger.error("ticket_service: failed to save tickets: %s", exc)
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_tickets() -> list[dict]:
    """Load tickets from the JSON store. Returns empty list on error."""
    path = get_ticket_store_path()
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("ticket_service: failed to load tickets: %s", exc)
    return []


def save_tickets(tickets: list[dict]) -> None:
    """Save tickets to the JSON store using an atomic write."""
    path = get_ticket_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(tickets, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except Exception as exc:
        logger.error("ticket_service: save_tickets failed: %s", exc)
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _agent_ticket_id(agent_name: str, assigned_at: str) -> str:
    """Stable ticket ID for an agent task run."""
    if assigned_at:
        safe_ts = re.sub(r"[^0-9TZ\-:]", "", assigned_at)
        return f"agent:{agent_name}:{safe_ts}"
    return f"agent:{agent_name}"


def find_ticket_by_agent(agent_name: str) -> Optional[dict]:
    """Find the most recent ticket for a given agent (by assigned_agent field).

    Returns the ticket dict or None if not found.
    Prefers in_progress tickets; falls back to the most recently updated.
    """
    tickets = load_tickets()
    candidates = [
        t for t in tickets
        if t.get("assigned_agent") == agent_name
    ]
    if not candidates:
        return None
    # Prefer in_progress, then most recently updated
    in_progress = [t for t in candidates if t.get("status") == "in_progress"]
    if in_progress:
        return sorted(in_progress, key=lambda t: t.get("updated_at", ""), reverse=True)[0]
    return sorted(candidates, key=lambda t: t.get("updated_at", ""), reverse=True)[0]


def create_ticket_for_agent(
    agent_name: str,
    task_description: str,
    *,
    assigned_at: str = "",
    assigned_by: str = "",
    status: str = "in_progress",
) -> Optional[dict]:
    """Create a new agent ticket with the given status.

    Returns the created ticket dict, or None if creation was skipped/failed.

    Skips creation if:
    - agent_name is in _INFRA_AGENTS
    - A ticket with the same stable ID already exists (idempotent)
    """
    if agent_name in _INFRA_AGENTS:
        return None

    ticket_id = _agent_ticket_id(agent_name, assigned_at)
    now = _now()

    path = get_ticket_store_path()
    try:
        with _locked_store(path) as tickets:
            # Idempotency: skip if ticket already exists
            existing_ids = {t["id"] for t in tickets}
            if ticket_id in existing_ids:
                logger.debug(
                    "ticket_service: ticket %s already exists, skipping create", ticket_id
                )
                return next(t for t in tickets if t["id"] == ticket_id)

            # Check if there's an active UDT assigned to this agent — update it instead
            active_udt = next(
                (t for t in tickets
                 if t.get("type") == "user"
                 and t.get("assigned_agent") == agent_name
                 and t.get("status") == "in_progress"),
                None,
            )
            if active_udt is not None:
                # Don't create a duplicate — the UDT already tracks this agent
                logger.debug(
                    "ticket_service: active UDT %s found for agent %s, skipping create",
                    active_udt["id"],
                    agent_name,
                )
                return active_udt

            ticket: dict = {
                "id": ticket_id,
                "type": "agent",
                "title": task_description[:120],
                "description": task_description,
                "requirements": "",
                "status": status,
                "priority": "medium",
                "assigned_agent": agent_name,
                "parent_agent": assigned_by or None,
                "created_at": assigned_at or now,
                "updated_at": now,
                "agent_name": agent_name,
                "task_text": task_description,
                "result_text": None,
                "error_text": None,
                "trace": [],
            }
            tickets.append(ticket)
            logger.info(
                "ticket_service: created ticket %s for agent %s (status=%s)",
                ticket_id,
                agent_name,
                status,
            )
            return ticket
    except Exception as exc:
        logger.warning("ticket_service: create_ticket_for_agent failed: %s", exc)
        return None


def update_ticket_status(
    agent_name: str,
    new_status: str,
    *,
    assigned_at: str = "",
    result_text: str = "",
    error_text: str = "",
) -> bool:
    """Update the ticket status for a given agent.

    Looks up the ticket by stable ID (agent_name + assigned_at) first,
    then falls back to find_ticket_by_agent() for legacy tickets.

    Returns True if a ticket was found and updated, False otherwise.
    """
    if agent_name in _INFRA_AGENTS:
        return False

    path = get_ticket_store_path()
    try:
        with _locked_store(path) as tickets:
            # Try stable ID first
            ticket_id = _agent_ticket_id(agent_name, assigned_at) if assigned_at else None
            target: Optional[dict] = None

            if ticket_id:
                target = next((t for t in tickets if t["id"] == ticket_id), None)

            # Fallback: find by assigned_agent + in_progress status
            if target is None:
                target = next(
                    (t for t in tickets
                     if t.get("assigned_agent") == agent_name
                     and t.get("status") == "in_progress"),
                    None,
                )

            # Last resort: most recently updated ticket for this agent
            if target is None:
                candidates = [t for t in tickets if t.get("assigned_agent") == agent_name]
                if candidates:
                    target = sorted(
                        candidates,
                        key=lambda t: t.get("updated_at", ""),
                        reverse=True,
                    )[0]

            if target is None:
                logger.debug(
                    "ticket_service: no ticket found for agent %s, skipping update",
                    agent_name,
                )
                return False

            now = _now()
            target["status"] = new_status
            target["updated_at"] = now
            if result_text:
                target["result_text"] = result_text
            if error_text:
                target["error_text"] = error_text

            logger.info(
                "ticket_service: updated ticket %s for agent %s → %s",
                target["id"],
                agent_name,
                new_status,
            )
            return True
    except Exception as exc:
        logger.warning("ticket_service: update_ticket_status failed: %s", exc)
        return False
