"""
Tests for GET /api/test.

Uses a minimal FastAPI app that only mounts the test_endpoint router,
following the same TestClient pattern as test_metrics.py and test_tickets.py.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.routers.test_endpoint import router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client() -> TestClient:
    """TestClient backed by a minimal FastAPI app with only the test_endpoint router."""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTestEndpoint:
    """Tests for GET /api/test."""

    def test_returns_200(self, client):
        resp = client.get("/api/test")
        assert resp.status_code == 200

    def test_returns_status_ok(self, client):
        data = client.get("/api/test").json()
        assert data == {"status": "ok"}

    def test_response_is_json(self, client):
        resp = client.get("/api/test")
        assert resp.headers["content-type"].startswith("application/json")

    def test_status_field_is_string(self, client):
        data = client.get("/api/test").json()
        assert isinstance(data["status"], str)

    def test_status_value_is_ok(self, client):
        data = client.get("/api/test").json()
        assert data["status"] == "ok"

    def test_no_extra_fields(self, client):
        """Response body should contain exactly one key: 'status'."""
        data = client.get("/api/test").json()
        assert set(data.keys()) == {"status"}

    def test_post_not_allowed(self, client):
        """Only GET is defined — POST should return 405."""
        resp = client.post("/api/test")
        assert resp.status_code == 405

    def test_wrong_path_returns_404(self, client):
        resp = client.get("/api/test/extra")
        assert resp.status_code == 404
