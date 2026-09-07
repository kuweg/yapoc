"""Phase 2.5 — every modifying task records what it changed.

The roadmap asks that a task attach its changed files, the checks that ran, and
a rollback reference. Before this, a task row said only "done" — there was no
way to answer "what did that agent actually touch, and can I undo it?" without
reading a prose result.

Change sets come from the agent's OWN mutating tool calls rather than a
`git status` diff, because git status is global: two agents running
concurrently would each be credited with the other's edits.
"""

from __future__ import annotations

import json

import pytest

from app.agents.base.runner import AgentRunner
from app.utils.adapters import ToolStart


def _verdict(mutations, checkpoint=""):
    return AgentRunner._verification_verdict(mutations, checkpoint)


# ── Extracting mutations from tool calls ───────────────────────────────────


@pytest.mark.parametrize(
    "tool,params,expected",
    [
        ("file_write", {"path": "app/utils/x.py"}, "file_write:app/utils/x.py"),
        ("file_edit", {"path": "README.md"}, "file_edit:README.md"),
        ("file_delete", {"path": "tmp/y.txt"}, "file_delete:tmp/y.txt"),
        ("create_skill", {"name": "deploy"}, "create_skill:deploy"),
        ("shell_exec", {"command": "make build"}, "shell_exec:<opaque>"),
        ("execute_code", {"code": "print(1)"}, "execute_code:<opaque>"),
    ],
)
def test_mutating_tools_are_recorded(tool, params, expected):
    assert AgentRunner._mutation_from_event(ToolStart(name=tool, input=params)) == expected


@pytest.mark.parametrize(
    "tool", ["file_read", "file_list", "grep", "web_search", "search_memory", "notes_read"]
)
def test_read_only_tools_are_not_recorded(tool):
    assert AgentRunner._mutation_from_event(ToolStart(name=tool, input={"path": "x"})) is None


def test_missing_path_still_records_the_mutation():
    """A malformed call must not make a write look like it never happened."""
    got = AgentRunner._mutation_from_event(ToolStart(name="file_write", input={}))
    assert got == "file_write:<unknown>"


# ── The verdict ────────────────────────────────────────────────────────────


def test_no_mutations_is_none():
    assert _verdict([], "abc123") == "none"
    assert _verdict([]) == "none"


def test_enumerable_changes_with_a_checkpoint_are_verified():
    assert _verdict(["file_edit:a.py", "file_write:b.py"], "abc123") == "verified"


def test_enumerable_changes_without_a_checkpoint_are_unanchored():
    """Knowing what changed is not enough — you must be able to undo it."""
    assert _verdict(["file_edit:a.py"]) == "unanchored"


def test_shell_makes_the_change_set_opaque():
    """A shell command can touch anything, so the task cannot claim a change set.

    This is the case that would otherwise be reported as a clean, fully-known
    edit while arbitrary commands ran underneath it.
    """
    assert _verdict(["shell_exec:<opaque>"]) == "opaque"
    assert _verdict(["file_edit:a.py", "shell_exec:<opaque>"]) == "opaque"
    assert _verdict(["shell_exec:<opaque>"], "abc123") == "opaque+checkpoint"


# ── End to end through the runner ──────────────────────────────────────────


async def test_runner_records_changed_files_on_the_task_row(tmp_path, monkeypatch):
    from app.config import settings
    from app.utils.adapters import AgentConfig, TextDelta, ToolCall, TurnComplete

    monkeypatch.setattr(type(settings), "project_root", property(lambda self: tmp_path))
    agents_dir = tmp_path / "app" / "agents"
    agent_dir = agents_dir / "verifier"
    agent_dir.mkdir(parents=True)
    monkeypatch.setattr(type(settings), "agents_dir", property(lambda self: agents_dir))
    (agent_dir / "TASK.MD").write_text(
        "---\nstatus: running\ntask_id: v1\nassigned_by: master\n---\n"
        "## Task\nEdit a file.\n\n## Result\n\n"
    )
    (agent_dir / "CONFIG.yaml").write_text(
        "adapter: fake\nmodel: fake-1\ntools:\n  - file_list\nrunner:\n"
        "  max_turns: 3\n  task_timeout: 60\n"
    )
    (agent_dir / "PROMPT.MD").write_text("test agent")
    (tmp_path / "app" / "memory" / "agents" / "verifier").mkdir(parents=True)

    class _EditingAdapter:
        """Reports a file_write on turn 1, then finishes."""

        def __init__(self):
            self.turns = 0

        def context_window_size(self):
            return 200_000

        async def stream_with_tools(self, system_prompt, messages, tools):
            self.turns += 1
            if self.turns == 1:
                call = ToolCall(id="c1", name="file_list", input={"path": "."})
                yield ToolStart(name="file_write", input={"path": "app/utils/new.py"})
                yield TurnComplete(
                    stop_reason="tool_use",
                    tool_calls=[call],
                    assistant_content=[
                        {"type": "tool_use", "id": call.id, "name": call.name,
                         "input": call.input}
                    ],
                )
            else:
                yield TextDelta(text="done editing")
                yield TurnComplete(
                    stop_reason="end_turn", tool_calls=[],
                    assistant_content=[{"type": "text", "text": "done editing"}],
                )

    fake = _EditingAdapter()

    async def _load_adapter(self, config):
        return fake

    async def _load_config(self, config_raw=None):
        return AgentConfig(adapter="fake", model="fake-1", temperature=0.0, max_tokens=100)

    monkeypatch.setattr("app.agents.base.BaseAgent._load_adapter", _load_adapter)
    monkeypatch.setattr("app.agents.base.BaseAgent._load_config", _load_config)

    recorded = []
    monkeypatch.setattr("app.utils.db.insert_task", lambda **kw: recorded.append(kw) or 1)
    monkeypatch.setattr("app.utils.db.init_schema", lambda: None)

    runner = AgentRunner("verifier")

    async def _noop_notify(text, status):
        pass

    monkeypatch.setattr(runner, "_notify_parent_via_bus", _noop_notify)
    monkeypatch.setattr(runner, "_write_status", lambda *a, **k: None)

    await runner._run_task("Edit a file.")

    assert recorded, "no task row recorded"
    row = recorded[-1]
    assert row["status"] == "done"
    changed = json.loads(row["changed_files"])
    assert changed == ["file_write:app/utils/new.py"], changed
    # No git checkpoint in a temp dir, so the change set is known but unanchored.
    assert row["verification"] == "unanchored"


def test_observability_decodes_changed_files():
    from app.backend.routers.metrics import _parse_changed_files

    assert _parse_changed_files('["file_edit:a.py"]') == ["file_edit:a.py"]
    assert _parse_changed_files("") == []
    assert _parse_changed_files(None) == []
    # Legacy rows and corrupt values must not break the dashboard.
    assert _parse_changed_files("not json") == []
    assert _parse_changed_files('{"not": "a list"}') == []
