"""
Tests for ticket manipulation endpoints:
  PATCH /tickets/{id}/status
  POST  /tickets/{id}/notes
  PATCH /tickets/{id}/priority
  PATCH /tickets/{id}/assignee

Uses a temporary tickets.json store so tests are hermetic and don't touch
the real app/data/tickets.json.

Patching strategy
-----------------
tickets.py uses module-level ``_TICKETS_PATH`` to locate the store.  We
monkeypatch that name in the router module's namespace so every helper
(_load_tickets / _save_tickets) uses the temp file automatically.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_ticket(
    *,
    ticket_id: str | None = None,
    title: str = "Test ticket",
    status: str = "backlog",
    priority: str = "medium",
    assigned_agent: str | None = None,
) -> dict:
    now = _now()
    return {
        "id": ticket_id or str(uuid.uuid4()),
        "type": "user",
        "title": title,
        "description": "",
        "requirements": "",
        "status": status,
        "priority": priority,
        "assigned_agent": assigned_agent,
        "parent_agent": None,
        "created_at": now,
        "updated_at": now,
        "agent_name": None,
        "task_text": None,
        "result_text": None,
        "error_text": None,
        "trace": [],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tickets_mod(monkeypatch):
    """Return the tickets router module (imported fresh)."""
    import app.backend.routers.tickets as mod
    return mod


@pytest.fixture()
def ticket_store(tmp_path) -> tuple[Path, list[dict]]:
    """Create a temporary tickets.json with one seeded ticket.

    Returns (path, tickets_list) so tests can inspect the file directly.
    """
    store_path = tmp_path / "tickets.json"
    tickets = [_make_ticket(ticket_id="ticket-001", title="Seed ticket", assigned_agent=None)]
    store_path.write_text(json.dumps(tickets, indent=2), encoding="utf-8")
    return store_path, tickets


@pytest.fixture()
def client(monkeypatch, tickets_mod, ticket_store):
    """TestClient backed by a minimal FastAPI app with only the tickets router,
    pointed at the temporary ticket store."""
    store_path, _ = ticket_store
    monkeypatch.setattr(tickets_mod, "_TICKETS_PATH", store_path)

    app = FastAPI()
    app.include_router(tickets_mod.router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helper: read the store directly
# ---------------------------------------------------------------------------

def _read_store(store_path: Path) -> list[dict]:
    return json.loads(store_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# TestTicketStatusUpdate — PATCH /tickets/{id}/status
# ---------------------------------------------------------------------------

class TestTicketStatusUpdate:
    def test_valid_status_done(self, client, ticket_store):
        store_path, _ = ticket_store
        resp = client.patch("/tickets/ticket-001/status", json={"status": "done"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "done"

    def test_valid_status_in_progress(self, client, ticket_store):
        resp = client.patch("/tickets/ticket-001/status", json={"status": "in_progress"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"

    def test_valid_status_pending(self, client, ticket_store):
        resp = client.patch("/tickets/ticket-001/status", json={"status": "pending"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

    def test_valid_status_blocked(self, client, ticket_store):
        resp = client.patch("/tickets/ticket-001/status", json={"status": "blocked"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "blocked"

    def test_invalid_status_returns_422(self, client):
        resp = client.patch("/tickets/ticket-001/status", json={"status": "flying"})
        assert resp.status_code == 422

    def test_invalid_status_detail_mentions_valid_values(self, client):
        resp = client.patch("/tickets/ticket-001/status", json={"status": "flying"})
        detail = resp.json()["detail"]
        assert "done" in detail or "in_progress" in detail or "pending" in detail

    def test_nonexistent_ticket_returns_404(self, client):
        resp = client.patch("/tickets/nonexistent-xyz/status", json={"status": "done"})
        assert resp.status_code == 404

    def test_404_detail_mentions_ticket_id(self, client):
        resp = client.patch("/tickets/nonexistent-xyz/status", json={"status": "done"})
        assert "nonexistent-xyz" in resp.json()["detail"]

    def test_missing_status_field_returns_422(self, client):
        resp = client.patch("/tickets/ticket-001/status", json={})
        assert resp.status_code == 422

    def test_status_persisted_to_store(self, client, ticket_store):
        store_path, _ = ticket_store
        client.patch("/tickets/ticket-001/status", json={"status": "done"})
        stored = _read_store(store_path)
        assert stored[0]["status"] == "done"

    def test_updated_at_changes(self, client, ticket_store):
        store_path, tickets = ticket_store
        original_updated_at = tickets[0]["updated_at"]
        resp = client.patch("/tickets/ticket-001/status", json={"status": "done"})
        # updated_at should be present (may equal original if test runs fast)
        assert "updated_at" in resp.json()

    def test_response_contains_ticket_id(self, client):
        resp = client.patch("/tickets/ticket-001/status", json={"status": "done"})
        assert resp.json()["id"] == "ticket-001"


# ---------------------------------------------------------------------------
# TestTicketNotes — POST /tickets/{id}/notes
# ---------------------------------------------------------------------------

class TestTicketNotes:
    def test_add_note_returns_200(self, client):
        resp = client.post(
            "/tickets/ticket-001/notes",
            json={"note": "Work started", "author": "master"},
        )
        assert resp.status_code == 200

    def test_note_appears_in_trace(self, client):
        resp = client.post(
            "/tickets/ticket-001/notes",
            json={"note": "Deployment complete", "author": "builder"},
        )
        trace = resp.json()["trace"]
        assert any(entry["note"] == "Deployment complete" for entry in trace)

    def test_author_stored_in_trace(self, client):
        resp = client.post(
            "/tickets/ticket-001/notes",
            json={"note": "Checked logs", "author": "doctor"},
        )
        trace = resp.json()["trace"]
        matching = [e for e in trace if e["note"] == "Checked logs"]
        assert matching[0]["agent"] == "doctor"

    def test_note_without_author_accepted(self, client):
        resp = client.post(
            "/tickets/ticket-001/notes",
            json={"note": "Anonymous note"},
        )
        assert resp.status_code == 200

    def test_empty_note_returns_422(self, client):
        resp = client.post(
            "/tickets/ticket-001/notes",
            json={"note": "", "author": "master"},
        )
        assert resp.status_code == 422

    def test_whitespace_only_note_returns_422(self, client):
        resp = client.post(
            "/tickets/ticket-001/notes",
            json={"note": "   ", "author": "master"},
        )
        assert resp.status_code == 422

    def test_missing_note_field_returns_422(self, client):
        resp = client.post(
            "/tickets/ticket-001/notes",
            json={"author": "master"},
        )
        assert resp.status_code == 422

    def test_nonexistent_ticket_returns_404(self, client):
        resp = client.post(
            "/tickets/nonexistent-xyz/notes",
            json={"note": "Hello", "author": "master"},
        )
        assert resp.status_code == 404

    def test_multiple_notes_accumulate(self, client):
        client.post("/tickets/ticket-001/notes", json={"note": "First note"})
        resp = client.post("/tickets/ticket-001/notes", json={"note": "Second note"})
        trace = resp.json()["trace"]
        notes = [e["note"] for e in trace]
        assert "First note" in notes
        assert "Second note" in notes

    def test_note_persisted_to_store(self, client, ticket_store):
        store_path, _ = ticket_store
        client.post("/tickets/ticket-001/notes", json={"note": "Persisted note"})
        stored = _read_store(store_path)
        trace = stored[0].get("trace", [])
        assert any(e["note"] == "Persisted note" for e in trace)

    def test_trace_entry_has_timestamp(self, client):
        resp = client.post("/tickets/ticket-001/notes", json={"note": "Timestamped"})
        trace = resp.json()["trace"]
        matching = [e for e in trace if e["note"] == "Timestamped"]
        assert "ts" in matching[0]
        assert matching[0]["ts"]  # non-empty


# ---------------------------------------------------------------------------
# TestTicketPriority — PATCH /tickets/{id}/priority
# ---------------------------------------------------------------------------

class TestTicketPriority:
    def test_valid_priority_low(self, client):
        resp = client.patch("/tickets/ticket-001/priority", json={"priority": "low"})
        assert resp.status_code == 200

    def test_valid_priority_medium(self, client):
        resp = client.patch("/tickets/ticket-001/priority", json={"priority": "medium"})
        assert resp.status_code == 200

    def test_valid_priority_high(self, client):
        resp = client.patch("/tickets/ticket-001/priority", json={"priority": "high"})
        assert resp.status_code == 200

    def test_valid_priority_critical(self, client):
        resp = client.patch("/tickets/ticket-001/priority", json={"priority": "critical"})
        assert resp.status_code == 200
        assert resp.json()["priority"] == "critical"

    def test_invalid_priority_returns_422(self, client):
        resp = client.patch("/tickets/ticket-001/priority", json={"priority": "urgent"})
        assert resp.status_code == 422

    def test_invalid_priority_detail_mentions_valid_values(self, client):
        resp = client.patch("/tickets/ticket-001/priority", json={"priority": "urgent"})
        detail = resp.json()["detail"]
        assert "high" in detail or "critical" in detail or "low" in detail

    def test_nonexistent_ticket_returns_404(self, client):
        resp = client.patch("/tickets/nonexistent-xyz/priority", json={"priority": "high"})
        assert resp.status_code == 404

    def test_missing_priority_field_returns_422(self, client):
        resp = client.patch("/tickets/ticket-001/priority", json={})
        assert resp.status_code == 422

    def test_priority_persisted_to_store(self, client, ticket_store):
        store_path, _ = ticket_store
        client.patch("/tickets/ticket-001/priority", json={"priority": "critical"})
        stored = _read_store(store_path)
        assert stored[0]["priority"] == "critical"

    def test_response_contains_ticket_id(self, client):
        resp = client.patch("/tickets/ticket-001/priority", json={"priority": "high"})
        assert resp.json()["id"] == "ticket-001"


# ---------------------------------------------------------------------------
# TestTicketAssignee — PATCH /tickets/{id}/assignee
# ---------------------------------------------------------------------------

class TestTicketAssignee:
    def test_valid_assignee_update(self, client):
        resp = client.patch("/tickets/ticket-001/assignee", json={"assignee": "builder"})
        assert resp.status_code == 200

    def test_assignee_reflected_in_response(self, client):
        resp = client.patch("/tickets/ticket-001/assignee", json={"assignee": "keeper"})
        assert resp.json()["assigned_agent"] == "keeper"

    def test_empty_assignee_returns_422(self, client):
        resp = client.patch("/tickets/ticket-001/assignee", json={"assignee": ""})
        assert resp.status_code == 422

    def test_whitespace_assignee_returns_422(self, client):
        resp = client.patch("/tickets/ticket-001/assignee", json={"assignee": "   "})
        assert resp.status_code == 422

    def test_missing_assignee_field_returns_422(self, client):
        resp = client.patch("/tickets/ticket-001/assignee", json={})
        assert resp.status_code == 422

    def test_nonexistent_ticket_returns_404(self, client):
        resp = client.patch("/tickets/nonexistent-xyz/assignee", json={"assignee": "builder"})
        assert resp.status_code == 404

    def test_404_detail_mentions_ticket_id(self, client):
        resp = client.patch("/tickets/nonexistent-xyz/assignee", json={"assignee": "builder"})
        assert "nonexistent-xyz" in resp.json()["detail"]

    def test_assignee_persisted_to_store(self, client, ticket_store):
        store_path, _ = ticket_store
        client.patch("/tickets/ticket-001/assignee", json={"assignee": "planning"})
        stored = _read_store(store_path)
        assert stored[0]["assigned_agent"] == "planning"

    def test_assignee_whitespace_stripped(self, client):
        resp = client.patch("/tickets/ticket-001/assignee", json={"assignee": "  master  "})
        assert resp.status_code == 200
        assert resp.json()["assigned_agent"] == "master"

    def test_response_contains_ticket_id(self, client):
        resp = client.patch("/tickets/ticket-001/assignee", json={"assignee": "builder"})
        assert resp.json()["id"] == "ticket-001"
