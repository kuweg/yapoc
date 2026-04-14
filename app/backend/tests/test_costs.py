"""
Tests for the /api/costs and /api/costs/summary endpoints.

Covers:
1.  Empty state — no COSTS.json files → empty list
2.  Single record — one agent, one record
3.  Multi-agent aggregation — records from multiple agents merged
4.  Agent filter (?agent=<name>) — only returns matching agent
5.  Limit param — ?limit=2 caps results
6.  Summary endpoint — per-agent totals
7.  Summary ordering — sorted by total_cost_usd desc
8.  Summary with multiple agents
9.  Record schema — all required fields present
10. Cost calculation — cost_usd is a float >= 0
11. Timestamp ordering — records sorted newest first
12. Unknown agent filter — returns empty list
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# App import
# ---------------------------------------------------------------------------

from app.backend.main import app
from app.utils.cost_tracker import load_all_costs

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_record(
    agent_name: str = "master",
    task_id: str = "master:2026-01-01T00:00:00Z",
    description: str = "Test task",
    tokens_in: int = 100,
    tokens_out: int = 200,
    cost_usd: float = 0.001,
    timestamp: str = "2026-01-01T00:00:00Z",
    model_used: str = "claude-sonnet-4-6",
) -> dict:
    return {
        "task_id":     task_id,
        "description": description,
        "agent_name":  agent_name,
        "tokens_in":   tokens_in,
        "tokens_out":  tokens_out,
        "cost_usd":    cost_usd,
        "timestamp":   timestamp,
        "model_used":  model_used,
    }


@pytest.fixture
def tmp_agents_dir(tmp_path):
    """Create a temporary agents directory with no COSTS.json files."""
    agents = tmp_path / "agents"
    agents.mkdir()
    return agents


@pytest.fixture
def agents_dir_with_records(tmp_path):
    """Create a temporary agents directory with pre-populated COSTS.json files."""
    agents = tmp_path / "agents"
    agents.mkdir()

    # master: 2 records
    master_dir = agents / "master"
    master_dir.mkdir()
    master_records = [
        _make_record("master", "master:2026-01-02T00:00:00Z", "Task B", 200, 400, 0.005, "2026-01-02T00:00:00Z"),
        _make_record("master", "master:2026-01-01T00:00:00Z", "Task A", 100, 200, 0.002, "2026-01-01T00:00:00Z"),
    ]
    (master_dir / "COSTS.json").write_text(json.dumps(master_records))

    # planning: 1 record
    planning_dir = agents / "planning"
    planning_dir.mkdir()
    planning_records = [
        _make_record("planning", "planning:2026-01-03T00:00:00Z", "Plan task", 50, 100, 0.001, "2026-01-03T00:00:00Z", "claude-3-haiku-20240307"),
    ]
    (planning_dir / "COSTS.json").write_text(json.dumps(planning_records))

    return agents


# ---------------------------------------------------------------------------
# Helper: patch the router's _load_all() to read from a test agents dir.
#
# The router calls _load_all() which internally calls load_all_costs(settings.agents_dir).
# settings.agents_dir is a @property on the Settings class (not a plain attribute),
# so patching it via unittest.mock.patch requires PropertyMock and is fragile.
# Instead we patch app.backend.routers.costs._load_all directly — simpler and
# more robust, as it targets exactly what the endpoint calls.
# ---------------------------------------------------------------------------

@contextmanager
def _patch_agents_dir(agents_dir: Path):
    """Patch the router's _load_all to read from the given agents_dir."""
    def _fake_load_all():
        return load_all_costs(agents_dir)

    with patch("app.backend.routers.costs._load_all", side_effect=_fake_load_all):
        yield


# ---------------------------------------------------------------------------
# Tests: GET /api/costs
# ---------------------------------------------------------------------------

class TestListCosts:
    def test_empty_state_returns_empty_list(self, tmp_agents_dir):
        """No COSTS.json files → empty list."""
        with _patch_agents_dir(tmp_agents_dir):
            resp = client.get("/costs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_single_record(self, tmp_path):
        """One agent with one record → list with one item."""
        agents = tmp_path / "agents"
        (agents / "master").mkdir(parents=True)
        record = _make_record("master")
        (agents / "master" / "COSTS.json").write_text(json.dumps([record]))

        with _patch_agents_dir(agents):
            resp = client.get("/costs")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["agent_name"] == "master"
        assert data[0]["task_id"] == record["task_id"]

    def test_multi_agent_aggregation(self, agents_dir_with_records):
        """Records from multiple agents are merged and returned."""
        with _patch_agents_dir(agents_dir_with_records):
            resp = client.get("/costs", params={"limit": 100})

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3  # 2 master + 1 planning
        agent_names = {r["agent_name"] for r in data}
        assert "master" in agent_names
        assert "planning" in agent_names

    def test_agent_filter(self, agents_dir_with_records):
        """?agent=planning returns only planning records."""
        with _patch_agents_dir(agents_dir_with_records):
            resp = client.get("/costs", params={"agent": "planning"})

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["agent_name"] == "planning"

    def test_agent_filter_master(self, agents_dir_with_records):
        """?agent=master returns only master records."""
        with _patch_agents_dir(agents_dir_with_records):
            resp = client.get("/costs", params={"agent": "master"})

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert all(r["agent_name"] == "master" for r in data)

    def test_limit_param(self, agents_dir_with_records):
        """?limit=1 returns at most 1 record."""
        with _patch_agents_dir(agents_dir_with_records):
            resp = client.get("/costs", params={"limit": 1})

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

    def test_limit_param_two(self, agents_dir_with_records):
        """?limit=2 returns at most 2 records."""
        with _patch_agents_dir(agents_dir_with_records):
            resp = client.get("/costs", params={"limit": 2})

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_unknown_agent_filter_returns_empty(self, agents_dir_with_records):
        """?agent=nonexistent returns empty list."""
        with _patch_agents_dir(agents_dir_with_records):
            resp = client.get("/costs", params={"agent": "nonexistent_agent_xyz"})

        assert resp.status_code == 200
        assert resp.json() == []

    def test_record_schema_has_all_fields(self, tmp_path):
        """Each record has all required schema fields."""
        agents = tmp_path / "agents"
        (agents / "master").mkdir(parents=True)
        record = _make_record("master")
        (agents / "master" / "COSTS.json").write_text(json.dumps([record]))

        with _patch_agents_dir(agents):
            resp = client.get("/costs")

        assert resp.status_code == 200
        item = resp.json()[0]
        required_fields = {"task_id", "description", "agent_name", "tokens_in",
                           "tokens_out", "cost_usd", "timestamp", "model_used"}
        assert required_fields.issubset(item.keys())

    def test_cost_usd_is_non_negative_float(self, tmp_path):
        """cost_usd is a float >= 0."""
        agents = tmp_path / "agents"
        (agents / "master").mkdir(parents=True)
        record = _make_record("master", cost_usd=0.00345)
        (agents / "master" / "COSTS.json").write_text(json.dumps([record]))

        with _patch_agents_dir(agents):
            resp = client.get("/costs")

        assert resp.status_code == 200
        item = resp.json()[0]
        assert isinstance(item["cost_usd"], float)
        assert item["cost_usd"] >= 0.0

    def test_timestamp_ordering_newest_first(self, agents_dir_with_records):
        """Records are sorted by timestamp descending (newest first)."""
        with _patch_agents_dir(agents_dir_with_records):
            resp = client.get("/costs", params={"limit": 100})

        assert resp.status_code == 200
        data = resp.json()
        timestamps = [r["timestamp"] for r in data]
        assert timestamps == sorted(timestamps, reverse=True)


# ---------------------------------------------------------------------------
# Tests: GET /api/costs/summary
# ---------------------------------------------------------------------------

class TestCostSummary:
    def test_empty_state_returns_empty_list(self, tmp_agents_dir):
        """No COSTS.json files → empty summary list."""
        with _patch_agents_dir(tmp_agents_dir):
            resp = client.get("/costs/summary")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_single_agent_summary(self, tmp_path):
        """One agent with two records → one summary entry with correct totals."""
        agents = tmp_path / "agents"
        (agents / "master").mkdir(parents=True)
        records = [
            _make_record("master", cost_usd=0.001, tokens_in=100, tokens_out=200),
            _make_record("master", task_id="master:2026-01-02T00:00:00Z", cost_usd=0.002, tokens_in=150, tokens_out=300),
        ]
        (agents / "master" / "COSTS.json").write_text(json.dumps(records))

        with _patch_agents_dir(agents):
            resp = client.get("/costs/summary")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        s = data[0]
        assert s["agent_name"] == "master"
        assert s["total_tasks"] == 2
        assert abs(s["total_cost_usd"] - 0.003) < 1e-6
        assert s["total_tokens_in"] == 250
        assert s["total_tokens_out"] == 500

    def test_multi_agent_summary(self, agents_dir_with_records):
        """Multiple agents → one summary entry per agent."""
        with _patch_agents_dir(agents_dir_with_records):
            resp = client.get("/costs/summary")

        assert resp.status_code == 200
        data = resp.json()
        agent_names = {s["agent_name"] for s in data}
        assert "master" in agent_names
        assert "planning" in agent_names

    def test_summary_sorted_by_cost_desc(self, agents_dir_with_records):
        """Summary is sorted by total_cost_usd descending."""
        with _patch_agents_dir(agents_dir_with_records):
            resp = client.get("/costs/summary")

        assert resp.status_code == 200
        data = resp.json()
        costs = [s["total_cost_usd"] for s in data]
        assert costs == sorted(costs, reverse=True)

    def test_summary_schema_has_all_fields(self, tmp_path):
        """Each summary entry has all required fields."""
        agents = tmp_path / "agents"
        (agents / "master").mkdir(parents=True)
        (agents / "master" / "COSTS.json").write_text(json.dumps([_make_record("master")]))

        with _patch_agents_dir(agents):
            resp = client.get("/costs/summary")

        assert resp.status_code == 200
        item = resp.json()[0]
        required = {"agent_name", "total_cost_usd", "total_tasks", "total_tokens_in", "total_tokens_out"}
        assert required.issubset(item.keys())
