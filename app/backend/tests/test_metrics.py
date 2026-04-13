"""
Tests for GET /metrics/agents, GET /metrics/agents/{name}, and
GET /metrics/agents/cpu.

Uses a temporary agents directory so tests are hermetic and don't depend
on the real app/agents/ layout.

Patching strategy
-----------------
metrics.py imports ``AGENTS_DIR`` from ``app.utils`` at module load time::

    from app.utils import AGENTS_DIR

So we patch the *name in the metrics module's namespace*:
    monkeypatch.setattr(metrics_mod, "AGENTS_DIR", agents_dir)

That is the only patch required — _parse_task / _count_memory_entries etc.
all receive ``agent_dir`` as a plain Path argument and never look up
settings.agents_dir themselves.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers to build a minimal fake agents directory
# ---------------------------------------------------------------------------

def _make_agent(base: Path, name: str, *, task_status: str = "idle") -> Path:
    """Create a minimal agent directory with TASK.MD, MEMORY.MD, HEALTH.MD."""
    agent_dir = base / name
    agent_dir.mkdir(parents=True, exist_ok=True)

    (agent_dir / "TASK.MD").write_text(
        f"---\nstatus: {task_status}\nassigned_by: test\n"
        f"assigned_at: 2026-01-01T00:00:00Z\ncompleted_at: \n---\n"
        f"## Task\nTest task\n## Result\n\n## Error\n\n",
        encoding="utf-8",
    )

    (agent_dir / "MEMORY.MD").write_text(
        "entry one\nentry two\nentry three\n",
        encoding="utf-8",
    )

    (agent_dir / "HEALTH.MD").write_text(
        "[2026-01-01 00:00] [ERROR]: something went wrong\n"
        "[2026-01-01 00:01] [INFO]: all good\n",
        encoding="utf-8",
    )

    return agent_dir


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def metrics_mod(monkeypatch):
    """
    Return the metrics router module with AGENTS_DIR already importable.
    We import it fresh here so monkeypatching happens before any test uses it.
    """
    import app.backend.routers.metrics as mod
    return mod


@pytest.fixture()
def client(tmp_path, monkeypatch, metrics_mod):
    """
    TestClient backed by a minimal FastAPI app that only mounts the metrics
    router, pointed at a temporary agents directory with two fake agents.
    """
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    _make_agent(agents_dir, "alpha")
    _make_agent(agents_dir, "beta", task_status="running")

    # Patch the module-level name that the router uses at call time
    monkeypatch.setattr(metrics_mod, "AGENTS_DIR", agents_dir)

    app = FastAPI()
    app.include_router(metrics_mod.router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests — list endpoint
# ---------------------------------------------------------------------------

class TestListAgentMetrics:
    def test_returns_200(self, client):
        resp = client.get("/metrics/agents")
        assert resp.status_code == 200

    def test_returns_list(self, client):
        data = client.get("/metrics/agents").json()
        assert isinstance(data, list)

    def test_contains_both_agents(self, client):
        names = {item["name"] for item in client.get("/metrics/agents").json()}
        assert "alpha" in names
        assert "beta" in names

    def test_each_item_has_required_fields(self, client):
        for item in client.get("/metrics/agents").json():
            assert "name" in item
            assert "status" in item
            assert "is_alive" in item
            assert "task_count" in item
            assert "health_issues" in item
            assert "last_active_at" in item  # may be None but key must exist

    def test_task_count_reflects_memory_lines(self, client):
        alpha = next(
            item for item in client.get("/metrics/agents").json()
            if item["name"] == "alpha"
        )
        # MEMORY.MD has 3 non-blank lines
        assert alpha["task_count"] == 3

    def test_health_issues_reflects_health_lines(self, client):
        alpha = next(
            item for item in client.get("/metrics/agents").json()
            if item["name"] == "alpha"
        )
        # HEALTH.MD has 2 non-blank lines
        assert alpha["health_issues"] == 2

    def test_is_alive_false_when_no_status_json(self, client):
        alpha = next(
            item for item in client.get("/metrics/agents").json()
            if item["name"] == "alpha"
        )
        # No STATUS.json → not alive
        assert alpha["is_alive"] is False

    def test_last_active_at_is_string_or_none(self, client):
        for item in client.get("/metrics/agents").json():
            val = item["last_active_at"]
            assert val is None or isinstance(val, str)

    def test_empty_agents_dir_returns_empty_list(self, tmp_path, monkeypatch, metrics_mod):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        monkeypatch.setattr(metrics_mod, "AGENTS_DIR", empty_dir)
        app = FastAPI()
        app.include_router(metrics_mod.router)
        resp = TestClient(app).get("/metrics/agents")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# Tests — single-agent endpoint
# ---------------------------------------------------------------------------

class TestGetAgentMetrics:
    def test_returns_200_for_valid_agent(self, client):
        assert client.get("/metrics/agents/alpha").status_code == 200

    def test_returns_correct_name(self, client):
        assert client.get("/metrics/agents/alpha").json()["name"] == "alpha"

    def test_returns_correct_status(self, client):
        # beta was created with task_status="running"
        assert client.get("/metrics/agents/beta").json()["status"] == "running"

    def test_returns_404_for_nonexistent_agent(self, client):
        assert client.get("/metrics/agents/nonexistent_agent_xyz").status_code == 404

    def test_404_detail_mentions_agent_name(self, client):
        resp = client.get("/metrics/agents/nonexistent_agent_xyz")
        assert "nonexistent_agent_xyz" in resp.json()["detail"]

    def test_task_count_type_is_int(self, client):
        assert isinstance(client.get("/metrics/agents/alpha").json()["task_count"], int)

    def test_health_issues_type_is_int(self, client):
        assert isinstance(client.get("/metrics/agents/alpha").json()["health_issues"], int)

    def test_is_alive_type_is_bool(self, client):
        assert isinstance(client.get("/metrics/agents/alpha").json()["is_alive"], bool)


# ---------------------------------------------------------------------------
# Tests — graceful handling when optional files are absent
# ---------------------------------------------------------------------------

class TestAgentWithNoOptionalFiles:
    """Verify graceful handling when MEMORY.MD / HEALTH.MD are absent."""

    @pytest.fixture()
    def sparse_client(self, tmp_path, monkeypatch, metrics_mod):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        # Only TASK.MD — no MEMORY.MD, no HEALTH.MD
        agent_dir = agents_dir / "sparse"
        agent_dir.mkdir()
        (agent_dir / "TASK.MD").write_text(
            "---\nstatus: idle\nassigned_by: test\n"
            "assigned_at: 2026-01-01T00:00:00Z\ncompleted_at: \n---\n"
            "## Task\nMinimal\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(metrics_mod, "AGENTS_DIR", agents_dir)
        app = FastAPI()
        app.include_router(metrics_mod.router)
        return TestClient(app)

    def test_task_count_zero_when_no_memory(self, sparse_client):
        resp = sparse_client.get("/metrics/agents/sparse")
        assert resp.status_code == 200
        assert resp.json()["task_count"] == 0

    def test_health_issues_zero_when_no_health(self, sparse_client):
        resp = sparse_client.get("/metrics/agents/sparse")
        assert resp.json()["health_issues"] == 0


# ---------------------------------------------------------------------------
# Helpers for CPU tests
# ---------------------------------------------------------------------------

import json as _json


def _make_agent_with_status(base: Path, name: str, pid: int | None = None) -> Path:
    """Create a minimal agent directory with optional STATUS.json."""
    agent_dir = base / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "TASK.MD").write_text(
        "---\nstatus: idle\nassigned_by: test\n"
        "assigned_at: 2026-01-01T00:00:00Z\ncompleted_at: \n---\n"
        "## Task\nTest\n",
        encoding="utf-8",
    )
    if pid is not None:
        (agent_dir / "STATUS.json").write_text(
            _json.dumps({"pid": pid, "state": "running"}),
            encoding="utf-8",
        )
    return agent_dir


# ---------------------------------------------------------------------------
# Tests — CPU list endpoint
# ---------------------------------------------------------------------------

class TestListAgentCpu:
    """Tests for GET /metrics/agents/cpu."""

    @pytest.fixture()
    def cpu_client(self, tmp_path, monkeypatch, metrics_mod):
        """Client with two agents: one with no STATUS.json, one with a dead PID."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        _make_agent_with_status(agents_dir, "no_status")          # no STATUS.json
        _make_agent_with_status(agents_dir, "dead_pid", pid=99999999)  # non-existent PID

        monkeypatch.setattr(metrics_mod, "AGENTS_DIR", agents_dir)
        app = FastAPI()
        app.include_router(metrics_mod.router)
        return TestClient(app)

    def test_returns_200(self, cpu_client):
        resp = cpu_client.get("/metrics/agents/cpu")
        assert resp.status_code == 200

    def test_returns_list(self, cpu_client):
        data = cpu_client.get("/metrics/agents/cpu").json()
        assert isinstance(data, list)

    def test_contains_both_agents(self, cpu_client):
        names = {item["agent_name"] for item in cpu_client.get("/metrics/agents/cpu").json()}
        assert "no_status" in names
        assert "dead_pid" in names

    def test_each_item_has_required_fields(self, cpu_client):
        for item in cpu_client.get("/metrics/agents/cpu").json():
            assert "agent_name" in item
            assert "pid" in item
            assert "cpu_percent" in item
            assert "memory_mb" in item
            assert "timestamp" in item

    def test_no_status_agent_has_zero_cpu(self, cpu_client):
        item = next(
            i for i in cpu_client.get("/metrics/agents/cpu").json()
            if i["agent_name"] == "no_status"
        )
        assert item["cpu_percent"] == 0.0
        assert item["memory_mb"] == 0.0
        assert item["pid"] is None

    def test_dead_pid_agent_has_zero_cpu(self, cpu_client):
        item = next(
            i for i in cpu_client.get("/metrics/agents/cpu").json()
            if i["agent_name"] == "dead_pid"
        )
        assert item["cpu_percent"] == 0.0
        assert item["memory_mb"] == 0.0
        # Dead PID is normalised to None
        assert item["pid"] is None

    def test_timestamp_is_iso_string(self, cpu_client):
        for item in cpu_client.get("/metrics/agents/cpu").json():
            ts = item["timestamp"]
            assert isinstance(ts, str)
            assert "T" in ts  # ISO 8601 format

    def test_empty_agents_dir_returns_empty_list(self, tmp_path, monkeypatch, metrics_mod):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        monkeypatch.setattr(metrics_mod, "AGENTS_DIR", empty_dir)
        app = FastAPI()
        app.include_router(metrics_mod.router)
        resp = TestClient(app).get("/metrics/agents/cpu")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_cpu_percent_is_float(self, cpu_client):
        for item in cpu_client.get("/metrics/agents/cpu").json():
            assert isinstance(item["cpu_percent"], (int, float))

    def test_memory_mb_is_float(self, cpu_client):
        for item in cpu_client.get("/metrics/agents/cpu").json():
            assert isinstance(item["memory_mb"], (int, float))

    def test_live_pid_returns_real_metrics(self, tmp_path, monkeypatch, metrics_mod):
        """Use the current process PID to verify psutil integration returns non-negative values."""
        import os
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        _make_agent_with_status(agents_dir, "self_proc", pid=os.getpid())

        monkeypatch.setattr(metrics_mod, "AGENTS_DIR", agents_dir)
        app = FastAPI()
        app.include_router(metrics_mod.router)
        resp = TestClient(app).get("/metrics/agents/cpu")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        item = items[0]
        assert item["agent_name"] == "self_proc"
        assert item["pid"] == os.getpid()
        assert item["cpu_percent"] >= 0.0
        assert item["memory_mb"] > 0.0  # current process always has some memory
