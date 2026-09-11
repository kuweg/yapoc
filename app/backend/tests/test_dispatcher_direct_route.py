"""The dispatcher's direct cron route.

A cron job carrying an ``assign_to`` target runs on that agent's own
subprocess instead of occupying the single master lane. These tests pin the
three things that made that worth doing: the routing decision, the fact that a
delegated run never takes master's slot, and the silence on completion (no
notification task, because nobody is waiting for a summary).
"""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest

from app.backend import dispatcher
from app.config import settings
from app.utils import db as db_module


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the task_queue at a throwaway SQLite file."""
    monkeypatch.setattr(db_module, "_DB_PATH", tmp_path / "yapoc.db")
    if hasattr(db_module._local, "conn"):
        monkeypatch.delattr(db_module._local, "conn", raising=False)
    db_module.init_schema()
    yield
    conn = getattr(db_module._local, "conn", None)
    if conn is not None:
        conn.close()
        del db_module._local.conn


@pytest.fixture(autouse=True)
def clean_lanes():
    """Never leak lane bookkeeping between tests."""
    dispatcher._running_task_ids.clear()
    dispatcher._master_task_ids.clear()
    dispatcher._running_tasks.clear()
    dispatcher._shutdown.clear()
    yield
    dispatcher._running_task_ids.clear()
    dispatcher._master_task_ids.clear()
    dispatcher._running_tasks.clear()
    dispatcher._shutdown.clear()


def _cron_row(assign_to: str, **extra) -> dict:
    meta = {"cron_job_id": "sweep", "assign_to": assign_to, **extra}
    return {"id": uuid.uuid4().hex, "source": "cron", "metadata": json.dumps(meta)}


# ── routing decision ────────────────────────────────────────────────────────


def test_cron_job_with_agent_target_routes_direct():
    assert dispatcher.direct_target(_cron_row("librarian")) == "librarian"


def test_cron_job_targeting_master_stays_on_master_lane():
    assert dispatcher.direct_target(_cron_row("master")) is None


def test_unknown_agent_falls_back_to_master_lane():
    """A typo in assign_to must degrade to the old behaviour, not fail the job."""
    assert dispatcher.direct_target(_cron_row("libarian")) is None


def test_non_cron_sources_never_route_direct():
    """assign_to is only ever written by the cron tick and the cron router."""
    row = _cron_row("librarian")
    row["source"] = "ui"
    assert dispatcher.direct_target(row) is None


@pytest.mark.parametrize("metadata", [None, "", "not json", "[]", "{}"])
def test_missing_or_malformed_metadata_stays_on_master_lane(metadata):
    assert dispatcher.direct_target(
        {"id": "x", "source": "cron", "metadata": metadata}
    ) is None


def test_agent_budget_matches_the_agents_own_resolution():
    """The dispatcher must wait exactly as long as the agent will run.

    librarian pins task_timeout in agent-settings.json, which outranks its
    CONFIG.yaml runner block — the same order BaseAgent applies.
    """
    entry = json.loads(
        (settings.project_root / "app/config/agent-settings.json").read_text()
    )
    agents = entry.get("agents", entry)
    expected = agents["librarian"]["task_timeout"]
    assert dispatcher._agent_task_timeout("librarian") == expected


# ── delegated execution ─────────────────────────────────────────────────────


class _StubSpawn:
    """Stands in for SpawnAgentTool, recording who claimed to be spawning."""

    calls: list[dict] = []
    response = "Agent 'librarian' spawned (PID 4242, state: running). Task assigned."

    def __init__(self, agent_dir=None, session_id=None, caller=None):
        self._caller = caller

    async def execute(self, **params):
        type(self).calls.append({"caller": self._caller, **params})
        return type(self).response


@pytest.fixture
def delegated_env(tmp_path, monkeypatch):
    """Wire the delegated path to stubs: no subprocess, no git, no report."""
    from app.utils.tools import delegation
    from app.backend import morning_report

    _StubSpawn.calls = []
    _StubSpawn.response = (
        "Agent 'librarian' spawned (PID 4242, state: running). Task assigned."
    )

    task_md = tmp_path / "TASK.MD"
    task_md.write_text(
        "---\nstatus: pending\ntask_id: run-1\nassigned_by: dispatcher\n---\n\n"
        "## Task\nsweep\n\n## Result\n\n\n## Error\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(delegation, "SpawnAgentTool", _StubSpawn)
    monkeypatch.setattr(delegation, "_task_path", lambda name: task_md)
    monkeypatch.setattr(
        delegation, "_resolve_checkpoint",
        lambda *a, **k: asyncio.sleep(0, result=""),
    )
    monkeypatch.setattr(dispatcher, "_DELEGATED_POLL_INTERVAL", 0.01)
    monkeypatch.setattr(dispatcher, "_DELEGATED_TIMEOUT_GRACE", 0)
    monkeypatch.setattr(dispatcher, "graph_event_bus", _NullGraphBus())
    monkeypatch.setattr(morning_report, "write_morning_report", lambda *a, **k: None)
    return {"task_md": task_md, "delegation": delegation}


class _NullGraphBus:
    async def emit_task_assigned(self, **kwargs):
        return None


def _queue_cron_task(assign_to: str = "librarian", **meta_extra) -> str:
    tid = uuid.uuid4().hex
    db_module.create_queued_task(
        id=tid,
        prompt="[Cron: sweep] consolidate memory",
        source="cron",
        metadata=json.dumps({"cron_job_id": "sweep", "assign_to": assign_to, **meta_extra}),
    )
    return tid


@pytest.mark.asyncio
async def test_delegated_run_records_result_without_master(temp_db, delegated_env, monkeypatch):
    delegation = delegated_env["delegation"]
    monkeypatch.setattr(
        delegation, "_poll_one_dag",
        lambda name: asyncio.sleep(0, result=("done", "consolidated 3 files", "")),
    )
    tid = _queue_cron_task()

    await dispatcher._execute_delegated_task_body(tid, "librarian")

    row = db_module.get_queued_task(tid)
    assert row["status"] == "done"
    assert row["result"] == "consolidated 3 files"
    # The row must name the agent that actually ran it, not master.
    assert row["assigned_agent"] == "librarian"


@pytest.mark.asyncio
async def test_delegated_run_identifies_itself_as_dispatcher(temp_db, delegated_env, monkeypatch):
    """assigned_by is what silences the completion notification downstream."""
    delegation = delegated_env["delegation"]
    monkeypatch.setattr(
        delegation, "_poll_one_dag",
        lambda name: asyncio.sleep(0, result=("done", "ok", "")),
    )
    await dispatcher._execute_delegated_task_body(_queue_cron_task(), "librarian")

    assert len(_StubSpawn.calls) == 1
    assert _StubSpawn.calls[0]["caller"] == "dispatcher"
    assert _StubSpawn.calls[0]["agent_name"] == "librarian"


@pytest.mark.asyncio
async def test_agent_error_is_recorded_and_feeds_cron_escalation(
    temp_db, delegated_env, monkeypatch
):
    delegation = delegated_env["delegation"]
    monkeypatch.setattr(
        delegation, "_poll_one_dag",
        lambda name: asyncio.sleep(0, result=("error", "", "adapter refused")),
    )
    failures: list[str] = []
    import app.utils.cron_parser as cron_parser
    monkeypatch.setattr(cron_parser, "record_cron_failure", lambda jid: failures.append(jid) or False)

    tid = _queue_cron_task()
    await dispatcher._execute_delegated_task_body(tid, "librarian")

    row = db_module.get_queued_task(tid)
    assert row["status"] == "error"
    assert "adapter refused" in row["error"]
    assert failures == ["sweep"]


@pytest.mark.asyncio
async def test_spawn_refusal_fails_the_task_instead_of_hanging(
    temp_db, delegated_env, monkeypatch
):
    """A busy agent soft-rejects the spawn; polling TASK.MD would then report
    the PREVIOUS run's status as this task's result."""
    _StubSpawn.response = "Agent 'librarian' is currently processing a task (PID 9, state: running)."
    delegation = delegated_env["delegation"]
    polled: list[str] = []
    monkeypatch.setattr(
        delegation, "_poll_one_dag",
        lambda name: polled.append(name) or asyncio.sleep(0, result=("done", "stale", "")),
    )

    tid = _queue_cron_task()
    await dispatcher._execute_delegated_task_body(tid, "librarian")

    row = db_module.get_queued_task(tid)
    assert row["status"] == "error"
    assert "Spawn refused" in row["error"]
    assert polled == []  # never read the other run's result


@pytest.mark.asyncio
async def test_agent_that_never_finishes_times_out(temp_db, delegated_env, monkeypatch):
    delegation = delegated_env["delegation"]
    monkeypatch.setattr(
        delegation, "_poll_one_dag",
        lambda name: asyncio.sleep(0, result=("running", "", "")),
    )
    monkeypatch.setattr(dispatcher, "_agent_task_timeout", lambda name: 1)

    tid = _queue_cron_task()
    await dispatcher._execute_delegated_task_body(tid, "librarian")

    row = db_module.get_queued_task(tid)
    assert row["status"] == "timeout"
    assert "did not finish" in row["error"]


@pytest.mark.asyncio
async def test_a_superseding_spawn_is_not_mistaken_for_our_result(
    temp_db, delegated_env, monkeypatch
):
    task_md: Path = delegated_env["task_md"]
    delegation = delegated_env["delegation"]

    def _reassign(name):
        # Someone else spawns into librarian mid-run.
        task_md.write_text(
            "---\nstatus: done\ntask_id: run-2\nassigned_by: master\n---\n\n"
            "## Task\nother\n\n## Result\nsomeone else's work\n\n## Error\n\n",
            encoding="utf-8",
        )
        return asyncio.sleep(0, result=("done", "someone else's work", ""))

    monkeypatch.setattr(delegation, "_poll_one_dag", _reassign)

    tid = _queue_cron_task()
    await dispatcher._execute_delegated_task_body(tid, "librarian")

    row = db_module.get_queued_task(tid)
    assert row["status"] == "error"
    assert "Superseded" in row["error"]
    assert row["result"] != "someone else's work"


@pytest.mark.asyncio
async def test_silent_job_records_its_result_but_stays_quiet(
    temp_db, delegated_env, monkeypatch
):
    delegation = delegated_env["delegation"]
    monkeypatch.setattr(
        delegation, "_poll_one_dag",
        lambda name: asyncio.sleep(0, result=("done", "quiet sweep", "")),
    )
    events: list[str] = []
    monkeypatch.setattr(
        dispatcher, "_push_task_state",
        lambda event, payload: events.append(event) or asyncio.sleep(0),
    )

    tid = _queue_cron_task(silent=True)
    await dispatcher._execute_delegated_task_body(tid, "librarian")

    assert db_module.get_queued_task(tid)["status"] == "done"
    assert "task_complete" not in events  # only the running update fired


# ── lane separation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_running_librarian_sweep_does_not_block_the_next_chat_message(
    temp_db, monkeypatch
):
    """The whole point: a cron sweep and a user message run at the same time.

    Before the direct route, both shared one slot and the chat waited for the
    sweep to finish.
    """
    import app.agents.master.agent as master_module

    class _IdleMaster:
        def is_busy(self):
            return False

    monkeypatch.setattr(master_module, "master_agent", _IdleMaster())
    monkeypatch.setattr(dispatcher, "_check_goals", lambda: asyncio.sleep(0))
    monkeypatch.setattr(dispatcher, "_check_timeouts", lambda: asyncio.sleep(0))

    started: list[tuple[str, str]] = []

    async def _fake_master(tid):
        started.append(("master", tid))
        await asyncio.sleep(30)

    async def _fake_delegated(tid, agent):
        started.append((agent, tid))
        await asyncio.sleep(30)

    monkeypatch.setattr(dispatcher, "_execute_task", _fake_master)
    monkeypatch.setattr(dispatcher, "_execute_delegated_task", _fake_delegated)

    sweep_id = _queue_cron_task()
    chat_id = uuid.uuid4().hex
    db_module.create_queued_task(id=chat_id, prompt="hello", source="ui")

    loop_task = asyncio.create_task(dispatcher.dispatcher_loop())
    try:
        for _ in range(200):
            await asyncio.sleep(0.02)
            if len(started) >= 2:
                break
    finally:
        dispatcher.request_shutdown()
        loop_task.cancel()
        await asyncio.gather(loop_task, return_exceptions=True)
        for task in list(dispatcher._running_tasks.values()):
            task.cancel()
        await asyncio.gather(*dispatcher._running_tasks.values(), return_exceptions=True)

    assert ("librarian", sweep_id) in started
    assert ("master", chat_id) in started
    # The sweep must never have consumed the master slot.
    assert sweep_id not in dispatcher._master_task_ids
    assert chat_id in dispatcher._master_task_ids


@pytest.mark.asyncio
async def test_master_lane_still_admits_only_one_task(temp_db, monkeypatch):
    import app.agents.master.agent as master_module

    class _IdleMaster:
        def is_busy(self):
            return False

    monkeypatch.setattr(master_module, "master_agent", _IdleMaster())
    monkeypatch.setattr(dispatcher, "_check_goals", lambda: asyncio.sleep(0))
    monkeypatch.setattr(dispatcher, "_check_timeouts", lambda: asyncio.sleep(0))

    started: list[str] = []

    async def _fake_master(tid):
        started.append(tid)
        await asyncio.sleep(30)

    monkeypatch.setattr(dispatcher, "_execute_task", _fake_master)

    for _ in range(3):
        db_module.create_queued_task(id=uuid.uuid4().hex, prompt="hi", source="ui")

    loop_task = asyncio.create_task(dispatcher.dispatcher_loop())
    try:
        await asyncio.sleep(0.5)
    finally:
        dispatcher.request_shutdown()
        loop_task.cancel()
        await asyncio.gather(loop_task, return_exceptions=True)
        for task in list(dispatcher._running_tasks.values()):
            task.cancel()
        await asyncio.gather(*dispatcher._running_tasks.values(), return_exceptions=True)

    assert len(started) == 1
