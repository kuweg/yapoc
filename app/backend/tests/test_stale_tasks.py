"""Tests for stale task watchdog endpoint."""
import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.backend.main import app

client = TestClient(app)


def test_list_stale_tasks_returns_200():
    resp = client.get("/stale-tasks")
    assert resp.status_code == 200


def test_list_stale_tasks_schema():
    resp = client.get("/stale-tasks")
    data = resp.json()
    assert "stale_tasks" in data
    assert "threshold_seconds" in data
    assert isinstance(data["stale_tasks"], list)
    assert isinstance(data["threshold_seconds"], int)


def test_no_stale_tasks_when_agents_dir_missing():
    with patch("app.backend.routers.stale_tasks._AGENTS_DIR", "/nonexistent/path"):
        resp = client.get("/stale-tasks")
    assert resp.status_code == 200
    assert resp.json()["stale_tasks"] == []


def test_stale_task_detected():
    with tempfile.TemporaryDirectory() as tmpdir:
        agent_dir = os.path.join(tmpdir, "test_agent")
        os.makedirs(agent_dir)
        # Write a TASK.MD that has been running for 700 seconds
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat().replace("+00:00", "Z")
        task_content = f"---\nstatus: running\nassigned_at: {old_time}\n---\n## Task\nTest task\n"
        with open(os.path.join(agent_dir, "TASK.MD"), "w") as f:
            f.write(task_content)
        with patch("app.backend.routers.stale_tasks._AGENTS_DIR", tmpdir):
            resp = client.get("/stale-tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["stale_tasks"]) == 1
    assert data["stale_tasks"][0]["agent"] == "test_agent"
    assert data["stale_tasks"][0]["elapsed_seconds"] >= 700


def test_non_running_task_not_stale():
    with tempfile.TemporaryDirectory() as tmpdir:
        agent_dir = os.path.join(tmpdir, "done_agent")
        os.makedirs(agent_dir)
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat().replace("+00:00", "Z")
        task_content = f"---\nstatus: done\nassigned_at: {old_time}\n---\n## Task\nTest task\n"
        with open(os.path.join(agent_dir, "TASK.MD"), "w") as f:
            f.write(task_content)
        with patch("app.backend.routers.stale_tasks._AGENTS_DIR", tmpdir):
            resp = client.get("/stale-tasks")
    assert resp.status_code == 200
    assert resp.json()["stale_tasks"] == []


def test_recent_running_task_not_stale():
    with tempfile.TemporaryDirectory() as tmpdir:
        agent_dir = os.path.join(tmpdir, "fresh_agent")
        os.makedirs(agent_dir)
        recent_time = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
        task_content = f"---\nstatus: running\nassigned_at: {recent_time}\n---\n## Task\nTest task\n"
        with open(os.path.join(agent_dir, "TASK.MD"), "w") as f:
            f.write(task_content)
        with patch("app.backend.routers.stale_tasks._AGENTS_DIR", tmpdir):
            resp = client.get("/stale-tasks")
    assert resp.status_code == 200
    assert resp.json()["stale_tasks"] == []
