"""Artifacts must record the task that produced them.

Before this, the registry schema had `source_task` / `source_session` fields
that nothing ever filled: every record arrived through `backfill_scan`, which
sees the file on disk long after the producing task ended and can only stamp
`source_agent: "backfill"`. The provenance is knowable exactly once — at the
moment the file is written — which is why registration moved there.

Two execution shapes have to work, and they resolve the task id differently:
in-process agents read the `current_task_id` ContextVar the dispatcher sets;
sub-process agents have no such ContextVar and fall back to TASK.MD.
"""

from __future__ import annotations

import pytest

from app.backend.services import artifacts


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Point the artifact registry and data/generated at a temp tree."""
    monkeypatch.setattr(artifacts, "_project_root", lambda: tmp_path)
    (tmp_path / "data" / "generated").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def agent_dir(tmp_path):
    d = tmp_path / "app" / "agents" / "builder"
    d.mkdir(parents=True)
    return d


def _make_file(root, name="chart_1.png") -> str:
    path = root / "data" / "generated" / name
    path.write_bytes(b"\x89PNG fake")
    return str(path)


# ── Resolution chain ──────────────────────────────────────────────────────


def test_resolves_task_from_the_context_var(registry, agent_dir):
    """In-process agents: the dispatcher sets this before running the task."""
    from app.backend.services.task_runtime import current_task_id

    token = current_task_id.set("task-abc")
    try:
        agent, task, _ = artifacts.resolve_provenance(agent_dir)
    finally:
        current_task_id.reset(token)

    assert agent == "builder"
    assert task == "task-abc"


def test_falls_back_to_task_md_for_subprocess_agents(registry, agent_dir):
    """Sub-process agents never see the ContextVar — it lives in another process."""
    (agent_dir / "TASK.MD").write_text(
        "---\nstatus: running\ntask_id: task-from-file\nsession_id: sess-9\n---\n## Task\ndo it\n"
    )

    agent, task, session = artifacts.resolve_provenance(agent_dir)

    assert (agent, task, session) == ("builder", "task-from-file", "sess-9")


def test_context_var_wins_over_a_stale_task_md(registry, agent_dir):
    """TASK.MD can lag behind; the live ContextVar is the current truth."""
    from app.backend.services.task_runtime import current_task_id

    (agent_dir / "TASK.MD").write_text("---\ntask_id: stale-task\n---\n")
    token = current_task_id.set("live-task")
    try:
        _, task, _ = artifacts.resolve_provenance(agent_dir)
    finally:
        current_task_id.reset(token)

    assert task == "live-task"


def test_explicit_session_wins_over_task_md(registry, agent_dir):
    (agent_dir / "TASK.MD").write_text("---\nsession_id: from-file\n---\n")
    _, _, session = artifacts.resolve_provenance(agent_dir, session_id="injected")
    assert session == "injected"


def test_missing_context_degrades_instead_of_raising(registry):
    """No agent dir, no task, no session — still a usable answer."""
    agent, task, session = artifacts.resolve_provenance(None)
    assert agent == "generated"
    assert task is None and session is None


def test_unreadable_task_md_does_not_raise(registry, agent_dir):
    (agent_dir / "TASK.MD").mkdir()  # a directory where a file is expected
    agent, task, _ = artifacts.resolve_provenance(agent_dir)
    assert agent == "builder"
    assert task is None


# ── Registration ──────────────────────────────────────────────────────────


def test_register_generated_stamps_the_producing_task(registry, agent_dir):
    (agent_dir / "TASK.MD").write_text("---\ntask_id: task-77\nsession_id: sess-77\n---\n")
    path = _make_file(registry)

    record = artifacts.register_generated(path, agent_dir)

    assert record is not None
    assert record["source_agent"] == "builder"
    assert record["source_task"] == "task-77"
    assert record["source_session"] == "sess-77"
    # The version entry carries it too, so lineage survives a re-render.
    assert record["versions"][0]["source_task"] == "task-77"


def test_registration_failure_never_breaks_the_producing_tool(registry, agent_dir):
    """A chart that rendered fine must not report failure over bookkeeping."""
    assert artifacts.register_generated(registry / "data" / "generated" / "missing.png", agent_dir) is None


def test_backfill_does_not_overwrite_real_provenance(registry, agent_dir):
    """`list_artifacts` runs a backfill sweep on every call — it must not clobber."""
    (agent_dir / "TASK.MD").write_text("---\ntask_id: task-real\n---\n")
    path = _make_file(registry)
    artifacts.register_generated(path, agent_dir)

    artifacts.backfill_scan()
    artifacts.backfill_scan()

    records = artifacts.list_artifacts()
    assert len(records) == 1
    assert records[0]["source_agent"] == "builder"
    assert records[0]["source_task"] == "task-real"
    assert records[0]["version"] == 1, "backfill re-registered an already-known file"


# ── Querying by task ──────────────────────────────────────────────────────


def test_artifacts_can_be_listed_by_the_task_that_produced_them(registry, agent_dir):
    (agent_dir / "TASK.MD").write_text("---\ntask_id: task-a\n---\n")
    artifacts.register_generated(_make_file(registry, "a.png"), agent_dir)

    (agent_dir / "TASK.MD").write_text("---\ntask_id: task-b\n---\n")
    artifacts.register_generated(_make_file(registry, "b.png"), agent_dir)
    artifacts.register_generated(_make_file(registry, "c.png"), agent_dir)

    assert [r["name"] for r in artifacts.list_artifacts(task="task-a")] == ["a.png"]
    assert sorted(r["name"] for r in artifacts.list_artifacts(task="task-b")) == ["b.png", "c.png"]
    assert artifacts.list_artifacts(task="task-none") == []


def test_task_filter_composes_with_the_other_filters(registry, agent_dir):
    (agent_dir / "TASK.MD").write_text("---\ntask_id: task-a\n---\n")
    artifacts.register_generated(_make_file(registry, "a.png"), agent_dir)
    artifacts.register_generated(_make_file(registry, "notes.md"), agent_dir)

    images = artifacts.list_artifacts(task="task-a", kind="image")

    assert [r["name"] for r in images] == ["a.png"]
