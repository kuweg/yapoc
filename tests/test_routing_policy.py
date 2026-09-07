"""Phase 3.4 — route from measured history, with deterministic fallbacks.

Measured over 30 days of real tasks:

    builder    n=236  success 97%  avg $0.0103  avg 37s
    planning   n=80   success 85%  avg $0.0288  avg 84s

Planning costs ~2.8x more, takes ~2.3x longer and fails ~4x as often, so for
work that needs no decomposition, routing through it buys nothing. That was an
argument in the original harness report; Phases 1 and 2 turned it into data.
"""

from __future__ import annotations

import pytest

from app.utils.routing_policy import (
    DEFAULT_TARGETS,
    MIN_SAMPLES,
    AgentStats,
    agent_stats,
    classify_task,
    recommend,
)


# ── Classification ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("create the file app/utils/foo.py with a hello function", "concrete_implementation"),
        ("add a test for the retry helper", "concrete_implementation"),
        ("fix the off-by-one in the pager", "concrete_implementation"),
        ("figure out how we should approach the memory architecture", "ambiguous_decomposition"),
        ("investigate why the deploy is slow and design a plan", "ambiguous_decomposition"),
        ("research the best library for PDF parsing", "research"),
        ("read the documentation for httpx timeouts", "research"),
        ("configure the api key for the telegram bot", "config"),
        ("update agent-settings.json for the new model", "config"),
        ("clean up and archive old memory entries", "maintenance"),
        ("", "unknown"),
    ],
)
def test_task_classification(prompt, expected):
    assert classify_task(prompt) == expected


def test_config_beats_concrete_when_both_match():
    """"configure the api key" is concrete AND config — config is the useful route."""
    assert classify_task("update the api key in .env") == "config"


def test_every_class_has_a_default_target():
    """A class with no fallback would make thin history a crash."""
    for cls in ("concrete_implementation", "ambiguous_decomposition", "research",
                "config", "maintenance", "unknown"):
        assert cls in DEFAULT_TARGETS


# ── Recommendation ─────────────────────────────────────────────────────────


def _stats(builder=None, planning=None):
    out = {}
    if builder:
        out["builder"] = AgentStats("builder", *builder)
    if planning:
        out["planning"] = AgentStats("planning", *planning)
    return out


def test_routes_concrete_work_direct_when_builder_is_better():
    stats = _stats(builder=(236, 0.97, 0.0103, 37.0), planning=(80, 0.85, 0.0288, 84.0))
    rec = recommend("create the file foo.py", stats=stats)
    assert rec.target == "builder"
    assert rec.from_history
    assert "97%" in rec.reason and "85%" in rec.reason
    assert rec.evidence["builder"]["tasks"] == 236


def test_routes_through_planning_when_planning_is_actually_better():
    """The policy must follow the data, not a preconception about builder."""
    stats = _stats(builder=(50, 0.60, 0.05, 90.0), planning=(50, 0.95, 0.01, 40.0))
    rec = recommend("create the file foo.py", stats=stats)
    assert rec.target == "planning"
    assert rec.from_history


def test_thin_history_falls_back_to_the_default(caplog):
    """A routing decision from four data points is noise wearing a number."""
    stats = _stats(builder=(MIN_SAMPLES - 1, 1.0, 0.001, 10.0))
    rec = recommend("create the file foo.py", stats=stats)
    assert rec.target == DEFAULT_TARGETS["concrete_implementation"]
    assert not rec.from_history
    assert "insufficient history" in rec.reason


def test_no_history_at_all_falls_back():
    rec = recommend("create the file foo.py", stats={})
    assert rec.target == DEFAULT_TARGETS["concrete_implementation"]
    assert not rec.from_history


def test_builder_history_without_planning_history_still_recommends():
    stats = _stats(builder=(236, 0.97, 0.0103, 37.0))
    rec = recommend("create the file foo.py", stats=stats)
    assert rec.target == "builder"
    assert rec.from_history
    assert "no comparable planning history" in rec.reason


@pytest.mark.parametrize(
    "prompt,target",
    [
        ("research the best pdf library", "researcher"),
        ("configure the api key", "keeper"),
        ("figure out the approach", "planning"),
        ("archive old entries", "builder"),
    ],
)
def test_single_owner_classes_do_not_consult_history(prompt, target):
    """Only concrete work has a genuine alternative to weigh."""
    rec = recommend(prompt, stats=_stats(builder=(999, 1.0, 0.0, 1.0)))
    assert rec.target == target
    assert not rec.from_history


def test_recommendation_always_carries_its_reasoning():
    """A silent route is undebuggable when it goes wrong."""
    for prompt in ("create the file x.py", "research something", ""):
        rec = recommend(prompt, stats=_stats(builder=(236, 0.97, 0.01, 37.0)))
        assert rec.reason.strip()
        assert rec.line()
        assert isinstance(rec.evidence, dict)


# ── Stats from the database ────────────────────────────────────────────────


def test_agent_stats_shape(tmp_path):
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE tasks (agent TEXT, status TEXT, assigned_at TEXT,
           completed_at TEXT, cost_usd REAL)"""
    )
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for status, cost in [("done", 0.01), ("done", 0.03), ("error", 0.02)]:
        conn.execute(
            "INSERT INTO tasks VALUES ('builder', ?, ?, ?, ?)",
            (status, now, now, cost),
        )
    conn.commit()

    stats = agent_stats(days=30, db=conn)
    assert "builder" in stats
    st = stats["builder"]
    assert st.tasks == 3
    assert st.success_rate == pytest.approx(2 / 3)
    assert st.avg_cost_usd == pytest.approx(0.02)
    assert not st.has_evidence  # 3 < MIN_SAMPLES


def test_partial_tasks_are_excluded_from_success_rate(tmp_path):
    """`partial` has no outcome yet; counting it either way distorts routing."""
    import sqlite3
    from datetime import datetime, timezone

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE tasks (agent TEXT, status TEXT, assigned_at TEXT,
           completed_at TEXT, cost_usd REAL)"""
    )
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for status in ("done", "done", "partial", "partial"):
        conn.execute("INSERT INTO tasks VALUES ('builder', ?, ?, ?, 0.01)",
                     (status, now, now))
    conn.commit()

    stats = agent_stats(days=30, db=conn)
    assert stats["builder"].tasks == 2
    assert stats["builder"].success_rate == 1.0
