"""Where a handed-off result goes when it finally arrives.

Two properties: it jumps ahead of messages typed while it was running, and the
turn that processes it is allowed to finish the job rather than only summarize.
"""
from __future__ import annotations

import json
import uuid

import pytest

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


# ── priority ────────────────────────────────────────────────────────────────


def _pending_order() -> list[str]:
    """Run the dispatcher's real pending query and return sources in order."""
    from app.backend import dispatcher

    rows = db_module.get_db().execute(
        dispatcher.PENDING_QUERY, (dispatcher._PENDING_WINDOW,)
    ).fetchall()
    return [r["source"] for r in rows]


def test_a_waiting_result_jumps_ahead_of_newly_typed_messages(temp_db):
    """The user typed twice while builder ran; builder's result goes first."""
    db_module.create_queued_task(id=uuid.uuid4().hex, prompt="also add a test", source="ui")
    db_module.create_queued_task(id=uuid.uuid4().hex, prompt="and docs", source="ui")
    db_module.create_queued_task(id=uuid.uuid4().hex, prompt="[result]", source="notification")

    assert _pending_order()[0] == "notification"


def test_continuations_rank_with_notifications(temp_db):
    db_module.create_queued_task(id=uuid.uuid4().hex, prompt="hi", source="ui")
    db_module.create_queued_task(id=uuid.uuid4().hex, prompt="[result]", source="continuation")

    assert _pending_order()[0] == "continuation"


def test_user_messages_still_outrank_autonomous_work(temp_db):
    """The existing guarantee must survive: chat beats cron/goal."""
    db_module.create_queued_task(id=uuid.uuid4().hex, prompt="[Cron: sweep]", source="cron")
    db_module.create_queued_task(id=uuid.uuid4().hex, prompt="[Goal]", source="goal")
    db_module.create_queued_task(id=uuid.uuid4().hex, prompt="hi", source="ui")

    assert _pending_order()[0] == "ui"


def test_full_ordering_is_results_then_user_then_autonomous(temp_db):
    db_module.create_queued_task(id=uuid.uuid4().hex, prompt="[Cron]", source="cron")
    db_module.create_queued_task(id=uuid.uuid4().hex, prompt="hi", source="ui")
    db_module.create_queued_task(id=uuid.uuid4().hex, prompt="[result]", source="notification")

    assert _pending_order() == ["notification", "ui", "cron"]


# ── continuation routing ────────────────────────────────────────────────────


def _deliver(notification: dict, parent_meta: dict | None = None) -> dict:
    """Run queue_pending_notifications against one notification, return the row."""
    from app.backend.services import notification_delivery as nd

    parent_id = uuid.uuid4().hex
    db_module.create_queued_task(
        id=parent_id, prompt="add /ping", source="ui",
        metadata=json.dumps(parent_meta or {}),
    )
    db_module.update_queued_task(parent_id, status="done")
    notification = {"parent_task_id": parent_id, **notification}

    class _Queue:
        def pending_entries(self, parent):
            return [notification]

        def acknowledge(self, entries):
            return None

    original_queue = nd.notification_queue
    nd.notification_queue = _Queue()
    try:
        nd.queue_pending_notifications()
    finally:
        nd.notification_queue = original_queue

    rows = [dict(r) for r in db_module.get_db().execute(
        "SELECT * FROM task_queue WHERE source IN ('notification','continuation')"
    ).fetchall()]
    assert len(rows) == 1
    return rows[0]


def _note(child: str, status: str = "done") -> dict:
    return {
        "parent_agent": "master", "child_agent": child, "status": status,
        "result": "added /ping; router not registered yet", "error": "",
        "session_id": "", "task_id": uuid.uuid4().hex,
        "completed_at": "2026-09-11T00:00:00Z",
    }


def test_a_handed_off_result_may_finish_the_job(temp_db):
    """master stopped waiting mid-chain, so the follow-up turn can spawn."""
    row = _deliver(_note("builder"), parent_meta={"abandoned_waits": ["builder"]})

    assert row["source"] == "continuation"
    assert "stopped waiting for 'builder'" in row["prompt"]


def test_an_ordinary_builder_result_stays_summary_only(temp_db):
    """master waited and already saw this result — no re-running it."""
    row = _deliver(_note("builder"))

    assert row["source"] == "notification"
    assert "Do not re-spawn completed work" in row["prompt"]


def test_planning_continuations_are_unchanged(temp_db):
    row = _deliver(_note("planning"))

    assert row["source"] == "continuation"
    assert "unexecuted plan" in row["prompt"]


def test_a_handed_off_failure_is_not_auto_retried(temp_db):
    """An errored child is reported, not silently re-spawned."""
    row = _deliver(_note("builder", status="error"),
                   parent_meta={"abandoned_waits": ["builder"]})

    assert row["source"] == "notification"


def test_a_different_child_is_not_treated_as_handed_off(temp_db):
    """The marker is per-agent, not a blanket flag on the parent task."""
    row = _deliver(_note("keeper"), parent_meta={"abandoned_waits": ["builder"]})

    assert row["source"] == "notification"
