"""Master's wait is bounded; the sub-agent's run is not.

master executes every queue entry under one lock, so a long `wait_for_agent`
freezes the user's chat. The cap bounds how long master WAITS — it must never
cancel, shorten, or fail the child, which keeps its own full budget and reports
back through the notification path.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest

from app.config import settings
from app.utils.tools import delegation
from app.utils import db as db_module


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "_DB_PATH", tmp_path / "yapoc.db")
    if hasattr(db_module._local, "conn"):
        monkeypatch.delattr(db_module._local, "conn", raising=False)
    db_module.init_schema()
    yield
    conn = getattr(db_module._local, "conn", None)
    if conn is not None:
        conn.close()
        del db_module._local.conn


def _task_md(tmp_path: Path, status: str, task_id: str = "run-1") -> Path:
    path = tmp_path / "TASK.MD"
    path.write_text(
        f"---\nstatus: {status}\ntask_id: {task_id}\nsession_id: \n"
        f"assigned_by: master\n---\n\n"
        "## Task\nbuild it\n\n## Result\n\n\n## Error\n\n",
        encoding="utf-8",
    )
    return path


# ── the cap applies to master only ──────────────────────────────────────────


def test_master_wait_is_capped():
    assert delegation._bounded_wait_timeout("master", 900) == settings.master_wait_timeout


def test_master_keeps_a_shorter_wait_it_asked_for():
    assert delegation._bounded_wait_timeout("master", 1) == 1


def test_sub_agents_are_not_capped():
    """planning waiting on builder runs in its own subprocess and blocks nobody."""
    assert delegation._bounded_wait_timeout("planning", 900) == 900


def test_cap_can_be_disabled(monkeypatch):
    monkeypatch.setattr(settings, "master_wait_timeout", 0)
    assert delegation._bounded_wait_timeout("master", 900) == 900


def test_the_child_budget_is_untouched():
    """The cap must not leak into any agent's own execution budget."""
    from app.backend.dispatcher import _agent_task_timeout

    entry = json.loads(
        (settings.project_root / "app/config/agent-settings.json").read_text()
    )
    agents = entry.get("agents", entry)
    assert _agent_task_timeout("builder") == agents["builder"]["task_timeout"]
    assert _agent_task_timeout("builder") != settings.master_wait_timeout


# ── giving up hands off, it does not fail ───────────────────────────────────


@pytest.mark.asyncio
async def test_still_running_agent_is_handed_off_not_failed(temp_db, tmp_path, monkeypatch):
    task_md = _task_md(tmp_path, "running")
    monkeypatch.setattr(delegation, "_task_path", lambda name: task_md)
    monkeypatch.setattr(delegation, "_read_status", lambda name: {"state": "running", "pid": 1})
    monkeypatch.setattr(settings, "master_wait_timeout", 1)

    tool = delegation.WaitForAgentTool(settings.agents_dir / "master")
    out = await tool.execute(agent_name="builder", timeout=900, poll_interval=1)

    assert "STILL RUNNING" in out
    assert "not cancelled" in out.lower()
    # The two ways master gets this wrong:
    assert "Do NOT spawn 'builder' again" in out
    assert "Do NOT state or summarize any result" in out
    # And it must not read as a failure.
    assert "failed" not in out.lower()


@pytest.mark.asyncio
async def test_a_crashed_agent_still_reports_as_crashed(temp_db, tmp_path, monkeypatch):
    """The handoff must not swallow a real crash — that fast-fail path stays."""
    task_md = _task_md(tmp_path, "running")
    monkeypatch.setattr(delegation, "_task_path", lambda name: task_md)
    monkeypatch.setattr(
        delegation, "_read_status", lambda name: {"state": "terminated", "pid": 99}
    )

    tool = delegation.WaitForAgentTool(settings.agents_dir / "master")
    out = await tool.execute(agent_name="builder", timeout=900, poll_interval=1)

    assert "terminated" in out.lower()
    assert "STILL RUNNING" not in out


@pytest.mark.asyncio
async def test_a_finished_agent_returns_its_result_unchanged(temp_db, tmp_path, monkeypatch):
    """The common Tier-2 case must be completely unaffected."""
    task_md = tmp_path / "TASK.MD"
    task_md.write_text(
        "---\nstatus: done\ntask_id: run-1\nassigned_by: master\n---\n\n"
        "## Task\nbuild it\n\n## Result\nrenamed foo to bar\n\n## Error\n\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(delegation, "_task_path", lambda name: task_md)

    tool = delegation.WaitForAgentTool(settings.agents_dir / "master")
    out = await tool.execute(agent_name="builder", timeout=900, poll_interval=1)

    assert "renamed foo to bar" in out
    assert "STILL RUNNING" not in out


@pytest.mark.asyncio
async def test_handoff_is_recorded_against_the_parent_task(temp_db, tmp_path, monkeypatch):
    from app.backend.services.task_runtime import current_task_id

    task_md = _task_md(tmp_path, "running")
    monkeypatch.setattr(delegation, "_task_path", lambda name: task_md)
    monkeypatch.setattr(delegation, "_read_status", lambda name: {"state": "running", "pid": 1})
    monkeypatch.setattr(settings, "master_wait_timeout", 1)

    parent_id = uuid.uuid4().hex
    db_module.create_queued_task(id=parent_id, prompt="add /ping", source="ui")

    token = current_task_id.set(parent_id)
    try:
        await delegation.WaitForAgentTool(settings.agents_dir / "master").execute(
            agent_name="builder", timeout=900, poll_interval=1
        )
    finally:
        current_task_id.reset(token)

    meta = json.loads(db_module.get_queued_task(parent_id)["metadata"] or "{}")
    assert meta["abandoned_waits"] == ["builder"]


@pytest.mark.asyncio
async def test_finalizing_the_turn_preserves_the_handoff_marker(temp_db):
    """The dispatcher parses metadata at task start; a mid-turn write must survive."""
    from app.backend.dispatcher import _current_metadata

    tid = uuid.uuid4().hex
    db_module.create_queued_task(
        id=tid, prompt="add /ping", source="ui",
        metadata=json.dumps({"history": []}),
    )
    stale = {"history": []}  # what the dispatcher captured at start
    db_module.update_queued_task(
        tid, metadata=json.dumps({"history": [], "abandoned_waits": ["builder"]})
    )

    merged = _current_metadata(tid, stale)
    assert merged["abandoned_waits"] == ["builder"]
