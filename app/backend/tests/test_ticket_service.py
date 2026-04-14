"""
Tests for the push-based ticket integration.

Covers:
  1. TestTicketServiceCore  — unit tests for ticket_service.py public API
  2. TestPushOnSpawn        — integration test: delegation.py push-on-spawn hook
  3. TestPushOnStatusChange — integration test: base/__init__.py push-on-status-change hook

Patching strategy
-----------------
ticket_service.py uses ``get_ticket_store_path()`` to locate the JSON store.
We monkeypatch that function (and the module-level ``get_ticket_store_path``
symbol) so every call inside the service redirects to a tmp_path file.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_ticket(
    *,
    ticket_id: str | None = None,
    agent_name: str = "test-agent",
    status: str = "in_progress",
    updated_at: str | None = None,
) -> dict:
    now = _now()
    return {
        "id": ticket_id or f"agent:{agent_name}:{now}",
        "type": "agent",
        "title": f"Task for {agent_name}",
        "description": f"Task for {agent_name}",
        "requirements": "",
        "status": status,
        "priority": "medium",
        "assigned_agent": agent_name,
        "parent_agent": None,
        "created_at": now,
        "updated_at": updated_at or now,
        "agent_name": agent_name,
        "task_text": f"Task for {agent_name}",
        "result_text": None,
        "error_text": None,
        "trace": [],
    }


def _write_store(path: Path, tickets: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tickets, indent=2), encoding="utf-8")


def _read_store(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Fixture: redirect ticket_service to a temp store
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_store(tmp_path) -> Path:
    """Return a temp path for tickets.json (does not create the file)."""
    return tmp_path / "tickets.json"


@pytest.fixture()
def svc(monkeypatch, tmp_store):
    """Import ticket_service with get_ticket_store_path redirected to tmp_store."""
    import app.backend.services.ticket_service as mod

    monkeypatch.setattr(mod, "get_ticket_store_path", lambda: tmp_store)
    return mod


# ===========================================================================
# 1. TestTicketServiceCore
# ===========================================================================

class TestTicketServiceCore:
    """Unit tests for the public API of ticket_service.py."""

    # ── load_tickets ────────────────────────────────────────────────────────

    def test_load_tickets_empty_nonexistent(self, svc, tmp_store):
        """load_tickets returns [] when the file does not exist."""
        assert not tmp_store.exists()
        result = svc.load_tickets()
        assert result == []

    def test_load_tickets_empty_file(self, svc, tmp_store):
        """load_tickets returns [] when the file contains invalid JSON."""
        tmp_store.parent.mkdir(parents=True, exist_ok=True)
        tmp_store.write_text("", encoding="utf-8")
        result = svc.load_tickets()
        assert result == []

    # ── save_tickets / load_tickets roundtrip ───────────────────────────────

    def test_save_and_load_roundtrip(self, svc, tmp_store):
        """save_tickets then load_tickets returns the same data."""
        tickets = [_make_ticket(ticket_id="t-001"), _make_ticket(ticket_id="t-002", agent_name="other")]
        svc.save_tickets(tickets)
        loaded = svc.load_tickets()
        assert len(loaded) == 2
        assert loaded[0]["id"] == "t-001"
        assert loaded[1]["id"] == "t-002"

    def test_save_tickets_creates_parent_dirs(self, svc, tmp_path):
        """save_tickets creates parent directories if they don't exist."""
        import app.backend.services.ticket_service as mod
        deep_path = tmp_path / "a" / "b" / "c" / "tickets.json"
        # Temporarily redirect to deep path
        original = mod.get_ticket_store_path
        mod.get_ticket_store_path = lambda: deep_path
        try:
            svc.save_tickets([_make_ticket(ticket_id="deep-001")])
            assert deep_path.exists()
            loaded = json.loads(deep_path.read_text())
            assert loaded[0]["id"] == "deep-001"
        finally:
            mod.get_ticket_store_path = original

    # ── find_ticket_by_agent ────────────────────────────────────────────────

    def test_find_ticket_by_agent_found(self, svc, tmp_store):
        """find_ticket_by_agent returns the matching ticket."""
        ticket = _make_ticket(ticket_id="agent:builder:2026-01-01T00:00:00Z", agent_name="builder")
        _write_store(tmp_store, [ticket])
        result = svc.find_ticket_by_agent("builder")
        assert result is not None
        assert result["id"] == "agent:builder:2026-01-01T00:00:00Z"
        assert result["assigned_agent"] == "builder"

    def test_find_ticket_by_agent_not_found(self, svc, tmp_store):
        """find_ticket_by_agent returns None when no ticket matches."""
        ticket = _make_ticket(ticket_id="agent:keeper:2026-01-01T00:00:00Z", agent_name="keeper")
        _write_store(tmp_store, [ticket])
        result = svc.find_ticket_by_agent("nonexistent-agent")
        assert result is None

    def test_find_ticket_by_agent_prefers_in_progress(self, svc, tmp_store):
        """find_ticket_by_agent prefers in_progress over done tickets."""
        done_ticket = _make_ticket(
            ticket_id="agent:builder:2026-01-01T00:00:00Z",
            agent_name="builder",
            status="done",
            updated_at="2026-01-01T00:00:00Z",
        )
        active_ticket = _make_ticket(
            ticket_id="agent:builder:2026-01-02T00:00:00Z",
            agent_name="builder",
            status="in_progress",
            updated_at="2026-01-02T00:00:00Z",
        )
        _write_store(tmp_store, [done_ticket, active_ticket])
        result = svc.find_ticket_by_agent("builder")
        assert result is not None
        assert result["status"] == "in_progress"

    def test_find_ticket_by_agent_empty_store(self, svc, tmp_store):
        """find_ticket_by_agent returns None on empty store."""
        _write_store(tmp_store, [])
        result = svc.find_ticket_by_agent("builder")
        assert result is None

    # ── create_ticket_for_agent ─────────────────────────────────────────────

    def test_create_ticket_for_agent(self, svc, tmp_store):
        """create_ticket_for_agent creates a ticket with correct fields."""
        assigned_at = "2026-04-13T12:00:00Z"
        ticket = svc.create_ticket_for_agent(
            "builder",
            "Build the widget",
            assigned_at=assigned_at,
            assigned_by="master",
            status="in_progress",
        )
        assert ticket is not None
        # ID is stable: agent:<name>:<assigned_at>
        assert ticket["id"] == f"agent:builder:{assigned_at}"
        assert ticket["title"] == "Build the widget"
        assert ticket["status"] == "in_progress"
        assert ticket["assigned_agent"] == "builder"
        assert ticket["agent_name"] == "builder"
        assert ticket["parent_agent"] == "master"
        assert ticket["type"] == "agent"
        assert ticket["task_text"] == "Build the widget"
        assert ticket["result_text"] is None
        assert ticket["error_text"] is None
        assert ticket["trace"] == []

    def test_create_ticket_persisted_to_store(self, svc, tmp_store):
        """create_ticket_for_agent writes the ticket to the JSON store."""
        svc.create_ticket_for_agent(
            "planning",
            "Plan the sprint",
            assigned_at="2026-04-13T12:00:00Z",
        )
        stored = _read_store(tmp_store)
        assert len(stored) == 1
        assert stored[0]["assigned_agent"] == "planning"

    def test_create_ticket_title_truncated_at_120(self, svc, tmp_store):
        """create_ticket_for_agent truncates title to 120 chars."""
        long_task = "A" * 200
        ticket = svc.create_ticket_for_agent(
            "builder",
            long_task,
            assigned_at="2026-04-13T12:00:00Z",
        )
        assert ticket is not None
        assert len(ticket["title"]) == 120
        # description is NOT truncated
        assert len(ticket["description"]) == 200

    def test_create_ticket_deduplicates(self, svc, tmp_store):
        """Calling create_ticket_for_agent twice with same args doesn't create duplicate."""
        kwargs = dict(
            agent_name="builder",
            task_description="Build the widget",
            assigned_at="2026-04-13T12:00:00Z",
            assigned_by="master",
        )
        first = svc.create_ticket_for_agent(**kwargs)
        second = svc.create_ticket_for_agent(**kwargs)
        # Both calls return a ticket
        assert first is not None
        assert second is not None
        # Same ticket ID
        assert first["id"] == second["id"]
        # Only one ticket in the store
        stored = _read_store(tmp_store)
        assert len(stored) == 1

    def test_create_ticket_skips_infra_agents(self, svc, tmp_store):
        """create_ticket_for_agent returns None for infra agents (e.g. 'base')."""
        result = svc.create_ticket_for_agent(
            "base",
            "Some infra task",
            assigned_at="2026-04-13T12:00:00Z",
        )
        assert result is None
        # Nothing written to store
        assert not tmp_store.exists() or _read_store(tmp_store) == []

    def test_create_ticket_skips_when_active_udt_exists(self, svc, tmp_store):
        """create_ticket_for_agent returns the existing UDT when one is active."""
        udt = {
            "id": "udt-001",
            "type": "user",
            "title": "User task",
            "description": "User task",
            "requirements": "",
            "status": "in_progress",
            "priority": "high",
            "assigned_agent": "builder",
            "parent_agent": None,
            "created_at": _now(),
            "updated_at": _now(),
            "agent_name": None,
            "task_text": None,
            "result_text": None,
            "error_text": None,
            "trace": [],
        }
        _write_store(tmp_store, [udt])
        result = svc.create_ticket_for_agent(
            "builder",
            "New agent task",
            assigned_at="2026-04-13T12:00:00Z",
        )
        # Returns the existing UDT, not a new ticket
        assert result is not None
        assert result["id"] == "udt-001"
        # Store still has only one ticket
        stored = _read_store(tmp_store)
        assert len(stored) == 1

    # ── update_ticket_status ────────────────────────────────────────────────

    def test_update_ticket_status(self, svc, tmp_store):
        """update_ticket_status updates the status of an existing ticket."""
        assigned_at = "2026-04-13T12:00:00Z"
        ticket = _make_ticket(
            ticket_id=f"agent:builder:{assigned_at}",
            agent_name="builder",
            status="in_progress",
        )
        _write_store(tmp_store, [ticket])

        result = svc.update_ticket_status(
            "builder",
            "done",
            assigned_at=assigned_at,
        )
        assert result is True
        stored = _read_store(tmp_store)
        assert stored[0]["status"] == "done"

    def test_update_ticket_status_sets_result_text(self, svc, tmp_store):
        """update_ticket_status stores result_text when provided."""
        assigned_at = "2026-04-13T12:00:00Z"
        ticket = _make_ticket(
            ticket_id=f"agent:builder:{assigned_at}",
            agent_name="builder",
            status="in_progress",
        )
        _write_store(tmp_store, [ticket])

        svc.update_ticket_status(
            "builder",
            "done",
            assigned_at=assigned_at,
            result_text="All done!",
        )
        stored = _read_store(tmp_store)
        assert stored[0]["result_text"] == "All done!"

    def test_update_ticket_status_sets_error_text(self, svc, tmp_store):
        """update_ticket_status stores error_text when provided."""
        assigned_at = "2026-04-13T12:00:00Z"
        ticket = _make_ticket(
            ticket_id=f"agent:builder:{assigned_at}",
            agent_name="builder",
            status="in_progress",
        )
        _write_store(tmp_store, [ticket])

        svc.update_ticket_status(
            "builder",
            "error",
            assigned_at=assigned_at,
            error_text="Something went wrong",
        )
        stored = _read_store(tmp_store)
        assert stored[0]["error_text"] == "Something went wrong"

    def test_update_ticket_status_no_ticket(self, svc, tmp_store):
        """update_ticket_status returns False gracefully when no ticket exists."""
        _write_store(tmp_store, [])
        result = svc.update_ticket_status("nonexistent-agent", "done")
        assert result is False

    def test_update_ticket_status_skips_infra_agents(self, svc, tmp_store):
        """update_ticket_status returns False for infra agents."""
        result = svc.update_ticket_status("base", "done")
        assert result is False

    def test_update_ticket_status_fallback_by_in_progress(self, svc, tmp_store):
        """update_ticket_status falls back to in_progress ticket when no assigned_at given."""
        ticket = _make_ticket(
            ticket_id="agent:builder:2026-01-01T00:00:00Z",
            agent_name="builder",
            status="in_progress",
        )
        _write_store(tmp_store, [ticket])
        # No assigned_at — should still find the in_progress ticket
        result = svc.update_ticket_status("builder", "done")
        assert result is True
        stored = _read_store(tmp_store)
        assert stored[0]["status"] == "done"

    # ── TASK_STATUS_MAP ─────────────────────────────────────────────────────

    def test_task_status_map_running(self, svc):
        assert svc.TASK_STATUS_MAP["running"] == "in_progress"

    def test_task_status_map_done(self, svc):
        assert svc.TASK_STATUS_MAP["done"] == "done"

    def test_task_status_map_error(self, svc):
        assert svc.TASK_STATUS_MAP["error"] == "error"

    def test_task_status_map_pending(self, svc):
        assert svc.TASK_STATUS_MAP["pending"] == "backlog"

    def test_task_status_map_consumed(self, svc):
        assert svc.TASK_STATUS_MAP["consumed"] == "done"


# ===========================================================================
# 2. TestPushOnSpawn
# ===========================================================================

class TestPushOnSpawn:
    """Integration tests for the push-on-spawn hook in delegation.py.

    We isolate the ticket-creation side-effect by:
    1. Monkeypatching get_ticket_store_path → tmp_store
    2. Calling create_ticket_for_agent directly (simulating what the hook does)
       rather than spawning a real subprocess — the hook code is a thin wrapper
       around create_ticket_for_agent, so testing that function with the same
       arguments is equivalent.
    """

    def test_spawn_creates_ticket(self, svc, tmp_store):
        """Simulated spawn hook: create_ticket_for_agent is called and ticket appears in store."""
        agent_name = "builder"
        task = "Build the feature"
        assigned_at = "2026-04-13T15:00:00Z"
        caller = "master"

        # This is exactly what the push-on-spawn hook does:
        ticket = svc.create_ticket_for_agent(
            agent_name,
            task,
            assigned_at=assigned_at,
            assigned_by=caller,
            status="in_progress",
        )

        assert ticket is not None
        assert ticket["status"] == "in_progress"
        assert ticket["assigned_agent"] == agent_name
        assert ticket["parent_agent"] == caller

        # Verify it's in the store
        stored = _read_store(tmp_store)
        assert len(stored) == 1
        assert stored[0]["id"] == f"agent:{agent_name}:{assigned_at}"

    def test_spawn_hook_is_idempotent(self, svc, tmp_store):
        """Calling the spawn hook twice for the same task doesn't duplicate tickets."""
        kwargs = dict(
            agent_name="planning",
            task_description="Plan the sprint",
            assigned_at="2026-04-13T15:00:00Z",
            assigned_by="master",
            status="in_progress",
        )
        svc.create_ticket_for_agent(**kwargs)
        svc.create_ticket_for_agent(**kwargs)

        stored = _read_store(tmp_store)
        assert len(stored) == 1

    def test_spawn_hook_does_not_create_for_infra_agent(self, svc, tmp_store):
        """Spawn hook skips ticket creation for infra agents."""
        result = svc.create_ticket_for_agent(
            "base",
            "Internal task",
            assigned_at="2026-04-13T15:00:00Z",
            assigned_by="master",
            status="in_progress",
        )
        assert result is None
        assert not tmp_store.exists() or _read_store(tmp_store) == []

    def test_spawn_ticket_has_correct_stable_id(self, svc, tmp_store):
        """Ticket ID follows the agent:<name>:<assigned_at> pattern."""
        assigned_at = "2026-04-13T15:30:00Z"
        ticket = svc.create_ticket_for_agent(
            "keeper",
            "Keep the config",
            assigned_at=assigned_at,
        )
        assert ticket is not None
        assert ticket["id"] == f"agent:keeper:{assigned_at}"

    def test_spawn_ticket_title_from_task(self, svc, tmp_store):
        """Ticket title is derived from the task description."""
        task = "Deploy the application to production"
        ticket = svc.create_ticket_for_agent(
            "builder",
            task,
            assigned_at="2026-04-13T15:00:00Z",
        )
        assert ticket is not None
        assert ticket["title"] == task

    def test_spawn_hook_in_delegation_module(self, monkeypatch, tmp_store):
        """Verify the push-on-spawn hook exists in delegation.py source code."""
        import inspect
        import app.utils.tools.delegation as delegation_mod

        source = inspect.getsource(delegation_mod.SpawnAgentTool.execute)
        assert "create_ticket_for_agent" in source, (
            "SpawnAgentTool.execute should call create_ticket_for_agent (push-on-spawn hook)"
        )


# ===========================================================================
# 3. TestPushOnStatusChange
# ===========================================================================

class TestPushOnStatusChange:
    """Integration tests for the push-on-status-change hook in base/__init__.py.

    We test the hook by:
    1. Creating a BaseAgent instance pointed at a temp directory
    2. Writing a TASK.MD with frontmatter
    3. Calling set_task_status() — which triggers the hook
    4. Verifying the ticket store was updated
    """

    @pytest.fixture()
    def agent_dir(self, tmp_path) -> Path:
        """Create a minimal agent directory with a TASK.MD."""
        agent_d = tmp_path / "test-agent"
        agent_d.mkdir()
        return agent_d

    def _write_task_md(self, agent_dir: Path, status: str = "running") -> None:
        assigned_at = "2026-04-13T12:00:00Z"
        content = (
            f"---\n"
            f"status: {status}\n"
            f"assigned_by: master\n"
            f"assigned_at: {assigned_at}\n"
            f"completed_at:\n"
            f"---\n\n"
            f"## Task\nDo something\n\n"
            f"## Context\n\n\n"
            f"## Result\n\n\n"
            f"## Error\n\n"
        )
        (agent_dir / "TASK.MD").write_text(content, encoding="utf-8")

    def _seed_ticket(self, store_path: Path, agent_name: str, assigned_at: str) -> None:
        ticket = _make_ticket(
            ticket_id=f"agent:{agent_name}:{assigned_at}",
            agent_name=agent_name,
            status="in_progress",
        )
        _write_store(store_path, [ticket])

    def test_status_change_updates_ticket_done(self, monkeypatch, tmp_path, agent_dir):
        """set_task_status('done') updates ticket to 'done' in the store."""
        store_path = tmp_path / "tickets.json"
        import app.backend.services.ticket_service as svc_mod
        monkeypatch.setattr(svc_mod, "get_ticket_store_path", lambda: store_path)

        assigned_at = "2026-04-13T12:00:00Z"
        self._write_task_md(agent_dir, status="running")
        self._seed_ticket(store_path, "test-agent", assigned_at)

        from app.agents.base import BaseAgent
        agent = BaseAgent(agent_dir)
        asyncio.run(agent.set_task_status("done", result="All done!"))

        stored = _read_store(store_path)
        assert len(stored) == 1
        assert stored[0]["status"] == "done"
        assert stored[0]["result_text"] == "All done!"

    def test_status_change_updates_ticket_error(self, monkeypatch, tmp_path, agent_dir):
        """set_task_status('error') updates ticket to 'error' in the store."""
        store_path = tmp_path / "tickets.json"
        import app.backend.services.ticket_service as svc_mod
        monkeypatch.setattr(svc_mod, "get_ticket_store_path", lambda: store_path)

        assigned_at = "2026-04-13T12:00:00Z"
        self._write_task_md(agent_dir, status="running")
        self._seed_ticket(store_path, "test-agent", assigned_at)

        from app.agents.base import BaseAgent
        agent = BaseAgent(agent_dir)
        asyncio.run(agent.set_task_status("error", error="Something broke"))

        stored = _read_store(store_path)
        assert stored[0]["status"] == "error"
        assert stored[0]["error_text"] == "Something broke"

    def test_status_change_updates_ticket_running_to_in_progress(
        self, monkeypatch, tmp_path, agent_dir
    ):
        """set_task_status('running') maps to 'in_progress' in the ticket store."""
        store_path = tmp_path / "tickets.json"
        import app.backend.services.ticket_service as svc_mod
        monkeypatch.setattr(svc_mod, "get_ticket_store_path", lambda: store_path)

        assigned_at = "2026-04-13T12:00:00Z"
        self._write_task_md(agent_dir, status="pending")
        self._seed_ticket(store_path, "test-agent", assigned_at)

        from app.agents.base import BaseAgent
        agent = BaseAgent(agent_dir)
        asyncio.run(agent.set_task_status("running"))

        stored = _read_store(store_path)
        assert stored[0]["status"] == "in_progress"

    def test_status_change_does_not_crash_when_no_ticket(
        self, monkeypatch, tmp_path, agent_dir
    ):
        """set_task_status does NOT raise even if no ticket exists in the store."""
        store_path = tmp_path / "tickets.json"
        import app.backend.services.ticket_service as svc_mod
        monkeypatch.setattr(svc_mod, "get_ticket_store_path", lambda: store_path)

        self._write_task_md(agent_dir, status="running")
        # No ticket seeded — store is empty
        _write_store(store_path, [])

        from app.agents.base import BaseAgent
        agent = BaseAgent(agent_dir)
        # Should not raise
        asyncio.run(agent.set_task_status("done", result="Completed"))
        # TASK.MD should still be updated correctly
        task_content = (agent_dir / "TASK.MD").read_text(encoding="utf-8")
        assert "status: done" in task_content

    def test_status_change_hook_in_base_agent_source(self):
        """Verify the push-on-status-change hook exists in base/__init__.py source."""
        import inspect
        from app.agents.base import BaseAgent

        source = inspect.getsource(BaseAgent.set_task_status)
        assert "update_ticket_status" in source, (
            "BaseAgent.set_task_status should call update_ticket_status (push-on-status-change hook)"
        )
        assert "TASK_STATUS_MAP" in source, (
            "BaseAgent.set_task_status should use TASK_STATUS_MAP for status translation"
        )

    def test_status_mapping_running_to_in_progress(self, monkeypatch, tmp_path, agent_dir):
        """TASK_STATUS_MAP: 'running' → 'in_progress'."""
        from app.backend.services.ticket_service import TASK_STATUS_MAP
        assert TASK_STATUS_MAP.get("running") == "in_progress"

    def test_status_mapping_done_to_done(self):
        """TASK_STATUS_MAP: 'done' → 'done'."""
        from app.backend.services.ticket_service import TASK_STATUS_MAP
        assert TASK_STATUS_MAP.get("done") == "done"

    def test_status_mapping_error_to_error(self):
        """TASK_STATUS_MAP: 'error' → 'error'."""
        from app.backend.services.ticket_service import TASK_STATUS_MAP
        assert TASK_STATUS_MAP.get("error") == "error"
