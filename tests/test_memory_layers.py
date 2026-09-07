"""Phase 3.1 — typed memory layers, retention policy, repetition collapse.

Measured against the live database before this landed: **58.2% of hot memory
rows (1,460 of 2,510) were near-duplicates** of each other, 786 of them the
single line `health_check: ISSUES DETECTED — N issue(s)`. That volume is what
made the Phase 2.4 benchmark's "security audit findings" query return five
`model_audit` rows and none of the two real findings.
"""

from __future__ import annotations

import sqlite3

import pytest

from app.utils.memory_layers import (
    ARCHIVAL,
    EPISODIC,
    LAYERS,
    PREFERENCE,
    PROJECT,
    RETENTION_DAYS,
    WORKING,
    annotate_representative,
    backfill_layers,
    classify_layer,
    collapse_repetitions,
    find_repetition_groups,
    layer_stats,
    shape_key,
)


# ── Classification ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "agent,source,expected",
    [
        ("builder", "MEMORY.MD", EPISODIC),
        ("builder", "TASK.MD", EPISODIC),
        ("evaluator", "REPORT.MD", EPISODIC),
        ("doctor", "HEALTH.MD", EPISODIC),
        ("builder", "NOTES.MD", PROJECT),
        ("builder", "LEARNINGS.MD", PROJECT),
        ("shared", "KNOWLEDGE.MD", PROJECT),
        ("user", "PROFILE.md", PREFERENCE),
        ("user", "HISTORY.md", PREFERENCE),
        ("_session", "abc.jsonl", WORKING),
        ("builder", "something-new.md", EPISODIC),
    ],
)
def test_layer_classification(agent, source, expected):
    assert classify_layer(agent, source) == expected


def test_user_memory_is_always_preference():
    """A user statement is a preference wherever it was written down."""
    assert classify_layer("user", "MEMORY.MD") == PREFERENCE
    assert classify_layer("user", "anything.md") == PREFERENCE


def test_cold_rows_are_archival_regardless_of_source():
    assert classify_layer("builder", "NOTES.MD", tier="cold") == ARCHIVAL


def test_unknown_source_gets_the_middle_retention():
    """An unclassified row should be neither forgotten fast nor kept forever."""
    layer = classify_layer("builder", "mystery.md")
    assert layer == EPISODIC
    assert RETENTION_DAYS[layer] is not None
    assert RETENTION_DAYS[WORKING] < RETENTION_DAYS[layer] < RETENTION_DAYS[PROJECT]


def test_preferences_never_expire_on_age():
    """Silently forgetting a stated preference is worse than holding a stale one."""
    assert RETENTION_DAYS[PREFERENCE] is None
    assert RETENTION_DAYS[ARCHIVAL] is None


def test_every_layer_has_a_retention_rule():
    assert set(RETENTION_DAYS) == set(LAYERS)


# ── Shape detection ────────────────────────────────────────────────────────


def test_entries_differing_only_by_a_number_share_a_shape():
    a = "health_check: ISSUES DETECTED — 7 issue(s)"
    b = "health_check: ISSUES DETECTED — 786 issue(s)"
    assert shape_key(a) == shape_key(b)


def test_uuids_and_timestamps_are_normalized():
    a = "task: --- status: running task_id: fac66f4e-ecdd-4114-9539-b1c2d3e4f5a6 at 2026-09-07T10:00:00Z"
    b = "task: --- status: running task_id: 11111111-2222-3333-4444-555555555555 at 2026-01-01T23:59:59Z"
    assert shape_key(a) == shape_key(b)


def test_genuinely_different_entries_do_not_share_a_shape():
    a = "Decision: turn exhaustion now records status=partial"
    b = "health_check: ISSUES DETECTED — 7 issue(s)"
    assert shape_key(a) != shape_key(b)


def test_short_entries_are_never_grouped():
    """Too little structure to be sure two rows are the same kind of thing."""
    rows = [{"id": i, "agent": "a", "source": "M", "content": "ok", "timestamp": "t"}
            for i in range(10)]
    assert find_repetition_groups(rows) == []


# ── Grouping ───────────────────────────────────────────────────────────────


def _row(i, content, agent="doctor", source="MEMORY.MD", ts="2026-09-01T00:00:00Z"):
    return {"id": i, "agent": agent, "source": source, "content": content, "timestamp": ts}


def test_repetition_group_keeps_the_newest_as_representative():
    rows = [
        _row(1, "health_check: ISSUES DETECTED — 1 issue(s)", ts="2026-09-01T00:00:00Z"),
        _row(2, "health_check: ISSUES DETECTED — 5 issue(s)", ts="2026-09-03T00:00:00Z"),
        _row(3, "health_check: ISSUES DETECTED — 9 issue(s)", ts="2026-09-02T00:00:00Z"),
    ]
    groups = find_repetition_groups(rows, min_count=3)
    assert len(groups) == 1
    g = groups[0]
    assert g.count == 3
    assert g.representative_id == 2, "the latest value is the one worth keeping"
    assert sorted(g.collapsed_ids) == [1, 3]


def test_groups_do_not_span_agents():
    """Two agents logging similar lines are still separate facts."""
    rows = [
        _row(1, "health_check: ISSUES DETECTED — 1 issue(s)", agent="doctor"),
        _row(2, "health_check: ISSUES DETECTED — 2 issue(s)", agent="doctor"),
        _row(3, "health_check: ISSUES DETECTED — 3 issue(s)", agent="doctor"),
        _row(4, "health_check: ISSUES DETECTED — 4 issue(s)", agent="cron"),
        _row(5, "health_check: ISSUES DETECTED — 5 issue(s)", agent="cron"),
        _row(6, "health_check: ISSUES DETECTED — 6 issue(s)", agent="cron"),
    ]
    groups = find_repetition_groups(rows, min_count=3)
    assert len(groups) == 2
    assert {g.agent for g in groups} == {"doctor", "cron"}


def test_min_count_is_respected():
    rows = [_row(i, f"health_check: ISSUES DETECTED — {i} issue(s)") for i in range(1, 3)]
    assert find_repetition_groups(rows, min_count=3) == []


def test_annotation_records_how_many_times_it_happened():
    """786 occurrences is itself the signal, even if 785 rows are not worth returning."""
    out = annotate_representative("health_check: ISSUES DETECTED — 7 issue(s)", 786)
    assert "[x786 occurrences]" in out
    assert "ISSUES DETECTED" in out
    # Idempotent — collapsing twice must not stack annotations.
    assert annotate_representative(out, 786) == out


# ── Database operations ────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path, monkeypatch):
    import app.utils.db as db_mod

    conn = sqlite3.connect(tmp_path / "m.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    monkeypatch.setattr(db_mod, "get_db", lambda: conn)
    conn.executescript(
        """
        CREATE TABLE memory_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, source TEXT,
            content TEXT, timestamp TEXT, embedding BLOB,
            tier TEXT DEFAULT 'hot', provenance TEXT DEFAULT '',
            layer TEXT DEFAULT 'episodic');
        CREATE VIRTUAL TABLE memory_fts USING fts5(content, content_rowid='id');
        """
    )
    conn.commit()
    return conn


def _seed(conn, n=6, agent="doctor", source="MEMORY.MD"):
    for i in range(n):
        cur = conn.execute(
            "INSERT INTO memory_entries (agent, source, content, timestamp)"
            " VALUES (?,?,?,?)",
            (agent, source, f"health_check: ISSUES DETECTED — {i} issue(s)",
             f"2026-09-0{i + 1}T00:00:00Z"),
        )
        conn.execute("INSERT INTO memory_fts (rowid, content) VALUES (?,?)",
                     (cur.lastrowid, f"health_check: ISSUES DETECTED — {i} issue(s)"))
    conn.commit()


def test_dry_run_changes_nothing(db):
    _seed(db)
    report = collapse_repetitions(db=db, dry_run=True)
    assert report.dry_run and report.collapsed == 5
    hot = db.execute("SELECT COUNT(*) FROM memory_entries WHERE tier='hot'").fetchone()[0]
    assert hot == 6, "a dry run must not touch the data"


def test_collapse_demotes_duplicates_but_deletes_nothing(db):
    """Non-destructive by design: collapsed rows stay reachable via include_cold."""
    _seed(db)
    before = db.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]

    report = collapse_repetitions(db=db, dry_run=False)
    assert report.collapsed == 5

    after = db.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]
    assert after == before, "rows were deleted; collapse must only demote"

    hot = db.execute("SELECT COUNT(*) FROM memory_entries WHERE tier='hot'").fetchone()[0]
    assert hot == 1
    survivor = db.execute("SELECT content, layer FROM memory_entries WHERE tier='hot'").fetchone()
    assert "[x6 occurrences]" in survivor["content"]
    cold_layers = {r["layer"] for r in db.execute("SELECT layer FROM memory_entries WHERE tier='cold'")}
    assert cold_layers == {ARCHIVAL}


def test_collapse_keeps_fts_in_sync(db):
    """A stale FTS row would keep serving the un-annotated text."""
    _seed(db)
    collapse_repetitions(db=db, dry_run=False)
    row = db.execute(
        "SELECT f.content FROM memory_fts f JOIN memory_entries m ON m.id=f.rowid"
        " WHERE m.tier='hot'"
    ).fetchone()
    assert "[x6 occurrences]" in row["content"]


def test_collapse_is_idempotent(db):
    _seed(db)
    collapse_repetitions(db=db, dry_run=False)
    second = collapse_repetitions(db=db, dry_run=False)
    assert second.collapsed == 0
    hot = db.execute("SELECT COUNT(*) FROM memory_entries WHERE tier='hot'").fetchone()[0]
    assert hot == 1


def test_collapse_spares_distinct_entries(db):
    """The policy must not eat the signal it exists to protect."""
    _seed(db, n=4)
    for i, text in enumerate([
        "Decision: turn exhaustion records status=partial and re-enqueues",
        "Security finding: path traversal bypassed the security directory lock",
    ]):
        cur = db.execute(
            "INSERT INTO memory_entries (agent, source, content, timestamp)"
            " VALUES ('master','NOTES.MD',?,?)", (text, f"2026-09-1{i}T00:00:00Z"))
        db.execute("INSERT INTO memory_fts (rowid, content) VALUES (?,?)", (cur.lastrowid, text))
    db.commit()

    collapse_repetitions(db=db, dry_run=False)
    hot = [r["content"] for r in db.execute("SELECT content FROM memory_entries WHERE tier='hot'")]
    assert any("turn exhaustion" in c for c in hot)
    assert any("path traversal" in c for c in hot)
    assert len(hot) == 3  # 2 distinct + 1 collapsed representative


def test_agent_scoped_collapse(db):
    _seed(db, n=4, agent="doctor")
    _seed(db, n=4, agent="cron")
    collapse_repetitions(db=db, dry_run=False, agent="doctor")
    doctor_hot = db.execute(
        "SELECT COUNT(*) FROM memory_entries WHERE tier='hot' AND agent='doctor'"
    ).fetchone()[0]
    cron_hot = db.execute(
        "SELECT COUNT(*) FROM memory_entries WHERE tier='hot' AND agent='cron'"
    ).fetchone()[0]
    assert doctor_hot == 1 and cron_hot == 4


def test_backfill_assigns_layers_to_legacy_rows(db):
    db.execute(
        "INSERT INTO memory_entries (agent, source, content, timestamp, layer)"
        " VALUES ('user','PROFILE.md','likes dark mode','2026-09-01T00:00:00Z','')")
    db.execute(
        "INSERT INTO memory_entries (agent, source, content, timestamp, layer)"
        " VALUES ('builder','NOTES.MD','poetry only','2026-09-01T00:00:00Z','')")
    db.commit()

    assert backfill_layers(db=db) == 2
    layers = {r["source"]: r["layer"] for r in db.execute("SELECT source, layer FROM memory_entries")}
    assert layers["PROFILE.md"] == PREFERENCE
    assert layers["NOTES.MD"] == PROJECT
    # Idempotent.
    assert backfill_layers(db=db) == 0


def test_layer_stats_reports_the_policy(db):
    _seed(db, n=3)
    backfill_layers(db=db)
    stats = layer_stats(db=db)
    assert stats[EPISODIC]["hot"] == 3
