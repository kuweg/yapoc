"""Phase 1.1/1.3 — the dashboard must not under-report failures.

Before this, `agents_with_errors` and `recent_error_count` were derived from
HEALTH.MD alone. Measured against the live database, that reported **0 errors
in the last 24 hours while 41 tasks had actually failed** — the dashboard could
say "all healthy" during a real outage, which is the single most dangerous
class of bug in a system that uses its own metrics to decide what to fix.

These tests pin the unified accounting: SQLite is the source of truth for
terminal task failures, HEALTH.MD is merged in without double-counting, and
`partial` (an in-flight continuation) is never counted as a failure.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.backend.routers import metrics as M


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """A throwaway SQLite DB wired into the metrics module."""
    import app.utils.db as db_mod

    path = tmp_path / "test.db"
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    monkeypatch.setattr(db_mod, "_db", conn, raising=False)
    monkeypatch.setattr(db_mod, "get_db", lambda: conn)
    monkeypatch.setattr(db_mod, "init_schema", lambda: None)

    conn.executescript(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, task_id TEXT,
            status TEXT, assigned_by TEXT, assigned_at TEXT, completed_at TEXT,
            task_summary TEXT, result_summary TEXT, error_summary TEXT,
            cost_usd REAL DEFAULT 0.0, continuation INTEGER DEFAULT 0);
        CREATE TABLE task_queue (
            id TEXT PRIMARY KEY, prompt TEXT, source TEXT, session_id TEXT,
            status TEXT, assigned_agent TEXT, result TEXT, error TEXT,
            cost_usd REAL DEFAULT 0.0, created_at TEXT, started_at TEXT,
            completed_at TEXT, updated_at TEXT, metadata TEXT);
        """
    )
    conn.commit()
    return conn


def _add_task(conn, agent, status, when, err="boom", task_id="t1", cont=0):
    conn.execute(
        "INSERT INTO tasks (agent, task_id, status, completed_at, error_summary, continuation)"
        " VALUES (?,?,?,?,?,?)",
        (agent, task_id, status, _iso(when), err, cont),
    )
    conn.commit()


def _add_queue(conn, tid, status, when, agent="master", err="queue boom"):
    conn.execute(
        "INSERT INTO task_queue (id, status, assigned_agent, completed_at, error)"
        " VALUES (?,?,?,?,?)",
        (tid, status, agent, _iso(when), err),
    )
    conn.commit()


NOW = datetime.now(timezone.utc)


def test_task_errors_are_counted(seeded_db):
    """A failed task with no HEALTH.MD line must still show up."""
    _add_task(seeded_db, "builder", "error", NOW - timedelta(minutes=5))
    _add_task(seeded_db, "planning", "error", NOW - timedelta(minutes=10))
    incidents, failures, _ = M._recent_task_incidents()
    assert failures == {"builder": 1, "planning": 1}
    assert len(incidents) == 2
    assert {i.source for i in incidents} == {"tasks"}


def test_queue_errors_and_timeouts_are_counted(seeded_db):
    _add_queue(seeded_db, "q1", "error", NOW - timedelta(minutes=3))
    _add_queue(seeded_db, "q2", "timeout", NOW - timedelta(minutes=4))
    incidents, failures, _ = M._recent_task_incidents()
    assert failures["master"] == 2
    assert {i.level for i in incidents} == {"ERROR", "TIMEOUT"}
    assert {i.source for i in incidents} == {"task_queue"}


def test_partial_is_a_continuation_not_a_failure(seeded_db):
    """The whole point of `partial` is that the work is still in flight.

    Counting it as an error would inflate the failure rate with healthy work
    and make the turn-continuation feature look like a regression.
    """
    _add_task(seeded_db, "planning", "partial", NOW - timedelta(minutes=2), cont=1)
    _add_task(seeded_db, "planning", "error", NOW - timedelta(minutes=6))
    incidents, failures, continuations = M._recent_task_incidents()
    assert failures == {"planning": 1}, "partial must not count as a failure"
    assert continuations == {"planning": 1}
    assert len(incidents) == 1


def test_old_failures_fall_outside_the_window(seeded_db):
    """Ranking failures over all time is what produced a wrong roadmap once."""
    _add_task(seeded_db, "builder", "error", NOW - timedelta(hours=40))
    _add_task(seeded_db, "builder", "error", NOW - timedelta(hours=2))
    _, failures, _ = M._recent_task_incidents(hours=24)
    assert failures == {"builder": 1}


def test_health_and_db_reports_of_one_failure_collapse(seeded_db):
    """A failing task writes BOTH a health line and a DB row — count it once."""
    ts = (NOW - timedelta(minutes=7)).strftime("%Y-%m-%d %H:%M")
    health = M.ObservabilityError(
        agent="builder", timestamp=ts, level="ERROR",
        message="Task incomplete: reached the 30-turn limit", source="health",
    )
    dbrow = M.ObservabilityError(
        agent="builder", timestamp=ts, level="ERROR",
        message="Task incomplete: reached the 30-turn limit", source="tasks",
        task_id="abc",
    )
    merged = M._dedupe_incidents([health, dbrow])
    assert len(merged) == 1, "the same failure was counted twice"
    # The DB record wins because it carries the task_id.
    assert merged[0].source == "tasks"
    assert merged[0].task_id == "abc"


def test_distinct_failures_are_not_collapsed(seeded_db):
    ts = (NOW - timedelta(minutes=7)).strftime("%Y-%m-%d %H:%M")
    a = M.ObservabilityError(agent="builder", timestamp=ts, level="ERROR",
                             message="disk full", source="health")
    b = M.ObservabilityError(agent="planning", timestamp=ts, level="ERROR",
                             message="disk full", source="health")
    c = M.ObservabilityError(agent="builder", timestamp=ts, level="ERROR",
                             message="totally different failure", source="tasks")
    assert len(M._dedupe_incidents([a, b, c])) == 3


async def test_dashboard_reconciles_with_the_database(seeded_db, monkeypatch, tmp_path):
    """The reconciliation check: tiles must equal what the DB actually holds.

    This is the regression guard for "dashboard reports zero errors during real
    failures". If the counters ever drift from the task tables again, this fails.
    """
    agents_dir = tmp_path / "agents"
    for name in ("builder", "planning"):
        (agents_dir / name).mkdir(parents=True)
    monkeypatch.setattr(M, "AGENTS_DIR", agents_dir)

    _add_task(seeded_db, "builder", "error", NOW - timedelta(minutes=5), task_id="a")
    _add_task(seeded_db, "planning", "error", NOW - timedelta(minutes=6), task_id="b")
    _add_task(seeded_db, "planning", "error", NOW - timedelta(minutes=7), task_id="c")
    _add_task(seeded_db, "planning", "partial", NOW - timedelta(minutes=8), task_id="d")
    _add_queue(seeded_db, "q1", "timeout", NOW - timedelta(minutes=9), agent="builder")

    dash = await M.get_observability_dashboard()

    db_failures = seeded_db.execute(
        "SELECT COUNT(*) FROM tasks WHERE status='error'"
    ).fetchone()[0] + seeded_db.execute(
        "SELECT COUNT(*) FROM task_queue WHERE status IN ('error','timeout')"
    ).fetchone()[0]

    assert dash.totals.task_failure_count == db_failures == 4
    assert dash.totals.continuation_count == 1
    # No HEALTH.MD files here, so the union equals the DB count exactly.
    assert dash.totals.recent_error_count == db_failures
    assert dash.totals.agents_with_errors == 2

    by_name = {a.name: a for a in dash.agents}
    assert by_name["planning"].task_failures == 2
    assert by_name["planning"].continuations == 1
    assert by_name["builder"].task_failures == 2  # 1 task + 1 queue timeout


async def test_dashboard_reports_zero_when_there_is_nothing_wrong(
    seeded_db, monkeypatch, tmp_path
):
    """The counters must not invent failures either."""
    agents_dir = tmp_path / "agents"
    (agents_dir / "builder").mkdir(parents=True)
    monkeypatch.setattr(M, "AGENTS_DIR", agents_dir)
    _add_task(seeded_db, "builder", "done", NOW - timedelta(minutes=5))

    dash = await M.get_observability_dashboard()
    assert dash.totals.task_failure_count == 0
    assert dash.totals.recent_error_count == 0
    assert dash.totals.agents_with_errors == 0


# ── Reliability scorecard (Phase 2.2) ──────────────────────────────────────


def test_failure_classification_buckets():
    assert M._classify_failure("Task timed out") == "timeout"
    assert M._classify_failure("Task incomplete: reached the 45-turn limit") == "turn_limit"
    assert M._classify_failure("All 4 adapters in the fallback chain failed") == "provider_config"
    assert M._classify_failure("400 INVALID_ARGUMENT thinking budget") == "provider_config"
    assert M._classify_failure("Incomplete provider response: length") == "malformed_output"
    assert M._classify_failure("something nobody predicted") == "other"
    assert M._classify_failure("") == "unlabelled"
    assert M._classify_failure(None) == "unlabelled"


async def test_scorecard_window_changes_the_failure_ranking(seeded_db):
    """The window is the whole point — pooling all time inverts the ranking.

    This is the mistake that produced a wrong first draft of the roadmap:
    old, long-fixed provider bugs outnumbered the live problem when counted
    over all time. A 2-day window must show the live problem on top.
    """
    for i in range(5):
        _add_task(seeded_db, "planning", "error", NOW - timedelta(hours=2),
                  err="Task incomplete: reached the 45-turn limit", task_id=f"new{i}")
    for i in range(20):
        _add_task(seeded_db, "builder", "error", NOW - timedelta(days=60),
                  err="All 4 adapters in the fallback chain failed", task_id=f"old{i}")
    # `assigned_at` drives the window; _add_task only sets completed_at.
    seeded_db.execute("UPDATE tasks SET assigned_at = completed_at")
    seeded_db.commit()

    recent = await M.get_reliability_scorecard(days=2)
    assert recent.failed == 5
    assert max(recent.failure_mix, key=recent.failure_mix.get) == "turn_limit"

    alltime = await M.get_reliability_scorecard(days=365)
    assert alltime.failed == 25
    assert max(alltime.failure_mix, key=alltime.failure_mix.get) == "provider_config"
    assert recent.window_days == 2 and alltime.window_days == 365


async def test_scorecard_failure_rate_excludes_partial(seeded_db):
    """`partial` has no outcome yet, so it belongs in neither numerator nor
    denominator — otherwise continuations would move the rate on their own."""
    _add_task(seeded_db, "planning", "done", NOW - timedelta(hours=1), task_id="a")
    _add_task(seeded_db, "planning", "done", NOW - timedelta(hours=1), task_id="b")
    _add_task(seeded_db, "planning", "error", NOW - timedelta(hours=1), task_id="c")
    _add_task(seeded_db, "planning", "partial", NOW - timedelta(hours=1), task_id="d", cont=1)
    seeded_db.execute("UPDATE tasks SET assigned_at = completed_at")
    seeded_db.commit()

    s = await M.get_reliability_scorecard(days=7)
    assert (s.completed, s.failed, s.partial) == (2, 1, 1)
    assert s.failure_rate == round(1 / 3, 4)  # not 1/4
    assert s.by_agent[0].continuations == 1


async def test_scorecard_cost_per_completed_task(seeded_db):
    seeded_db.execute(
        "INSERT INTO tasks (agent, task_id, status, assigned_at, completed_at, cost_usd, continuation)"
        " VALUES ('builder','x','done',?,?,0.10,0)", (_iso(NOW), _iso(NOW)))
    seeded_db.execute(
        "INSERT INTO tasks (agent, task_id, status, assigned_at, completed_at, cost_usd, continuation)"
        " VALUES ('builder','y','done',?,?,0.30,0)", (_iso(NOW), _iso(NOW)))
    seeded_db.execute(
        "INSERT INTO tasks (agent, task_id, status, assigned_at, completed_at, cost_usd, continuation)"
        " VALUES ('builder','z','partial',?,?,0.20,1)", (_iso(NOW), _iso(NOW)))
    seeded_db.commit()

    s = await M.get_reliability_scorecard(days=7)
    assert s.total_cost_usd == pytest.approx(0.60)
    assert s.cost_per_completed_task == pytest.approx(0.30)  # 0.60 / 2 completed
    # Only the continuation row's spend counts as continuation cost.
    assert s.continuation_cost_usd == pytest.approx(0.20)


async def test_scorecard_empty_window_does_not_claim_free_work(seeded_db):
    """No completions must give None, not 0.0 — 0.0 reads as 'costs nothing'."""
    s = await M.get_reliability_scorecard(days=7)
    assert s.tasks == 0
    assert s.failure_rate == 0.0
    assert s.cost_per_completed_task is None
