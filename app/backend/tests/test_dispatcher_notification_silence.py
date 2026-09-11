"""A dispatcher-routed run produces no completion notification.

The direct cron route collects its own result, so the child has nobody to
notify. All three notification producers must agree on that — a single one
that still fires would put the master turn (and the lane block) right back.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.backend.services.notification_queue import (
    DISPATCHER_PARENT,
    NON_AGENT_PARENTS,
)


def _write_task_md(agent_dir: Path, assigned_by: str, status: str = "done") -> Path:
    agent_dir.mkdir(parents=True, exist_ok=True)
    path = agent_dir / "TASK.MD"
    path.write_text(
        f"---\nstatus: {status}\ntask_id: t-1\nsession_id: \n"
        f"assigned_by: {assigned_by}\ncompleted_at: 2026-09-11T00:00:00Z\n---\n\n"
        "## Task\nsweep\n\n## Result\nconsolidated\n\n## Error\n\n",
        encoding="utf-8",
    )
    return path


def test_dispatcher_is_not_a_notifiable_parent():
    assert DISPATCHER_PARENT in NON_AGENT_PARENTS
    assert "master" not in NON_AGENT_PARENTS


@pytest.mark.asyncio
async def test_notify_parent_tool_declines_a_dispatcher_run(tmp_path):
    from app.utils.tools.delegation import NotifyParentTool

    agent_dir = tmp_path / "librarian"
    _write_task_md(agent_dir, DISPATCHER_PARENT)

    result = await NotifyParentTool(agent_dir).execute(result="done", status="done")
    assert "No parent to notify" in result


@pytest.mark.asyncio
async def test_notify_parent_tool_still_notifies_a_real_parent(tmp_path, monkeypatch):
    """Guard against the sentinel swallowing legitimate master delegations."""
    from app.utils.tools import delegation

    agent_dir = tmp_path / "builder"
    _write_task_md(agent_dir, "master")

    published: list[str] = []

    class _Bus:
        async def stream_add(self, stream, payload, agent_name=None):
            published.append(stream)

    monkeypatch.setattr("app.backend.message_bus.bus", _Bus())
    monkeypatch.setattr(delegation, "_wake_agent_if_idle", _noop)

    result = await delegation.NotifyParentTool(agent_dir).execute(
        result="built it", status="done"
    )
    assert "notified" in result
    assert published == ["agent:master:inbox"]


async def _noop(*args, **kwargs):
    return None


class _RecordingQueue:
    """Minimal NotificationQueue stand-in — records what the poller enqueues."""

    def __init__(self):
        self.entries: list[dict] = []

    def enqueue(self, **kwargs):
        self.entries.append(kwargs)

    def purge_consumed(self, keep_last: int = 200):
        return None


class _RegistrySaying:
    def __init__(self, parent):
        self._parent = parent

    def get_parent(self, agent_name):
        return self._parent


def _poller_for(agents_dir, registry, monkeypatch):
    from app.backend.services import notification_poller as poller_module

    # Keep the persistent dedup set out of the repo's data dir.
    monkeypatch.setattr(poller_module, "_save_notified", lambda notified: None)
    queue = _RecordingQueue()
    poller = poller_module.NotificationPoller(
        agents_dir=agents_dir, registry=registry, queue=queue
    )
    poller._notified = set()
    return poller, queue


def test_poller_skips_a_dispatcher_run_even_with_a_stale_registry(tmp_path, monkeypatch):
    """The spawn registry keeps the LAST parent, so a librarian master once
    spawned still maps to master there. assigned_by must win."""
    agents_dir = tmp_path / "agents"
    _write_task_md(agents_dir / "librarian", DISPATCHER_PARENT)

    poller, queue = _poller_for(agents_dir, _RegistrySaying("master"), monkeypatch)
    poller._poll_once()

    assert queue.entries == []


def test_poller_still_notifies_for_a_master_spawned_run(tmp_path, monkeypatch):
    agents_dir = tmp_path / "agents"
    _write_task_md(agents_dir / "builder", "master")

    poller, queue = _poller_for(agents_dir, _RegistrySaying("master"), monkeypatch)
    poller._poll_once()

    assert len(queue.entries) == 1
    assert queue.entries[0]["parent_agent"] == "master"


def test_poller_falls_back_to_assigned_by_when_registry_is_empty(tmp_path, monkeypatch):
    agents_dir = tmp_path / "agents"
    _write_task_md(agents_dir / "builder", "planning")

    poller, queue = _poller_for(agents_dir, _RegistrySaying(None), monkeypatch)
    poller._poll_once()

    assert len(queue.entries) == 1
    assert queue.entries[0]["parent_agent"] == "planning"


# ── the runner's own notify path ────────────────────────────────────────────
#
# This is the producer that always fires: AgentRunner calls it at the end of
# every task, whether or not the agent used the notify_parent tool.


def _runner_with_frontmatter(frontmatter: dict, bus):
    from app.agents.base.runner import AgentRunner

    runner = AgentRunner.__new__(AgentRunner)
    runner._name = "librarian"
    runner._bus = bus
    runner._parse_task_frontmatter = lambda: frontmatter
    return runner


class _RecordingBus:
    def __init__(self):
        self.streams: list[str] = []

    async def stream_add(self, stream, payload, agent_name=None):
        self.streams.append(stream)


@pytest.mark.asyncio
async def test_runner_does_not_notify_for_a_dispatcher_run():
    bus = _RecordingBus()
    runner = _runner_with_frontmatter({"assigned_by": DISPATCHER_PARENT}, bus)

    await runner._notify_parent_via_bus("consolidated", "done")

    assert bus.streams == []


@pytest.mark.asyncio
async def test_runner_still_notifies_a_real_parent():
    bus = _RecordingBus()
    runner = _runner_with_frontmatter(
        {"assigned_by": "master", "session_id": "", "task_id": "t-1"}, bus
    )

    await runner._notify_parent_via_bus("consolidated", "done")

    assert bus.streams == ["agent:master:inbox"]
