"""Tests for Phase 0 — turn-exhaustion salvage and continuation.

Before this change, an agent that used up ``max_turns`` raised a bare
RuntimeError: the task was recorded as ``error`` and every turn of work was
discarded. Turn-limit exhaustion was 19 of the 28 failures in the current
release (all of them on 2026-09-06/07), and raising the caps did not help —
failures walked 15 -> 30 -> 45 over a single day.

These tests pin the replacement behaviour: the partial work survives, the task
is recorded as ``partial`` rather than ``error``, and it is re-enqueued to
continue from its own progress.
"""

import re

from app.agents.base import TurnLimitReached
from app.agents.base.runner import AgentRunner


# ── TurnLimitReached ────────────────────────────────────────────────────────


def test_message_text_is_unchanged():
    """HEALTH.MD scrapers and the doctor agent match on this exact string."""
    exc = TurnLimitReached(45, "partial work")
    assert str(exc) == "Task incomplete: reached the 45-turn limit"
    assert isinstance(exc, RuntimeError)  # still caught by generic handlers


def test_carries_partial_work():
    exc = TurnLimitReached(30, "half a plan")
    assert exc.max_turns == 30
    assert exc.partial_text == "half a plan"


# ── Header neutralization ───────────────────────────────────────────────────


def test_neutralize_headers_prevents_task_section_truncation():
    """A salvaged result containing "## X" must not truncate the ## Task section.

    ``BaseAgent.get_task_body`` extracts ``## Task`` up to ``(?=\\n## |\\Z)``.
    Embedding raw agent output that contains its own markdown headers would cut
    the continuation body off at the first one.
    """
    partial = "Did the thing.\n## Findings\nSome findings.\n### Detail\nmore"
    out = AgentRunner._neutralize_headers(partial)
    assert "\n## Findings" not in out
    assert "> ## Findings" in out
    assert "> ### Detail" in out
    # Content is preserved, only prefixed.
    assert "Some findings." in out
    # A mid-line hash is untouched.
    assert AgentRunner._neutralize_headers("issue #42 filed") == "issue #42 filed"


def test_section_markers_are_not_markdown_headers():
    """The markers must not start with '## ' or they truncate the body."""
    for marker in (AgentRunner._ORIGINAL_MARKER, AgentRunner._PROGRESS_MARKER):
        assert not marker.startswith("#")


# ── Continuation counter ────────────────────────────────────────────────────


def test_continuation_count_parsing():
    assert AgentRunner._continuation_count(None, {}) == 0
    assert AgentRunner._continuation_count(None, {"continuation": "2"}) == 2
    assert AgentRunner._continuation_count(None, {"continuation": " 3 "}) == 3
    # Garbage must not crash the failure path.
    assert AgentRunner._continuation_count(None, {"continuation": "abc"}) == 0
    assert AgentRunner._continuation_count(None, {"continuation": ""}) == 0
    assert AgentRunner._continuation_count(None, {"continuation": "-5"}) == 0


# ── Round-trip through the real TASK.MD parser ──────────────────────────────


def _get_task_body(content: str) -> str:
    """Mirror of BaseAgent.get_task_body, to assert what the agent would read."""
    m = re.search(r"## Task\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
    return m.group(1).strip() if m else content.strip()


def _build_body(original: str, partial: str, attempt: int = 1) -> str:
    """Mirror of the body construction in _enqueue_continuation."""
    return (
        f"{AgentRunner._CONTINUATION_HEADER} attempt {attempt} of 3.\n"
        f"You previously ran out of turns (30) on this task. "
        f"Your own progress is below — continue from it, do not start over, "
        f"and do not repeat work already done.\n\n"
        f"{AgentRunner._ORIGINAL_MARKER}\n{original}\n\n"
        f"{AgentRunner._PROGRESS_MARKER}\n"
        f"{AgentRunner._neutralize_headers(partial)}\n"
    )


def test_continuation_body_survives_get_task_body():
    """The whole continuation must come back — preamble, task AND progress."""
    original = "Implement the widget."
    partial = "Read the code.\n## Notes\nThe widget lives in widget.py."
    task_md = (
        "---\nstatus: pending\ntask_id: abc\ncontinuation: 1\n---\n"
        f"## Task\n{_build_body(original, partial)}\n"
        "## Context\nsome context\n"
        "## Result\n\n"
    )
    body = _get_task_body(task_md)
    assert AgentRunner._CONTINUATION_HEADER in body
    assert original in body
    assert "The widget lives in widget.py." in body
    assert AgentRunner._PROGRESS_MARKER in body
    # Must not have leaked into the following section.
    assert "some context" not in body


def test_continuation_does_not_nest_on_second_attempt():
    """Attempt 2 must carry ONE copy of the original task, not a nested chain."""
    original = "Implement the widget."
    first = _build_body(original, "Read the code.", attempt=1)

    # Recover the original the way _enqueue_continuation does.
    assert first.startswith(AgentRunner._CONTINUATION_HEADER)
    _, _, rest = first.partition(AgentRunner._ORIGINAL_MARKER + "\n")
    recovered = rest.split("\n" + AgentRunner._PROGRESS_MARKER)[0].strip()
    assert recovered == original

    second = _build_body(recovered, "Read the code. Wrote the widget.", attempt=2)
    assert second.count(AgentRunner._ORIGINAL_MARKER) == 1
    assert second.count(original) == 1
    assert "attempt 2 of 3" in second


def test_partial_status_does_not_touch_the_failure_counter():
    """`partial` must neither reset (like done) nor increment (like error).

    Resetting would hide a real failure streak; incrementing would fire the
    two-consecutive-failures alert on work that is still in flight.
    """
    from app.agents.base import BaseAgent

    calls = []

    class _Probe(BaseAgent):
        def __init__(self):  # bypass BaseAgent.__init__
            self._name = "probe"

    import app.agents.base as base_mod

    class _Tracker:
        @staticmethod
        def record_agent_success(name):
            calls.append(("success", name))

        @staticmethod
        def record_agent_failure(name):
            calls.append(("failure", name))
            return False

    original = base_mod._agent_failure_tracker
    base_mod._agent_failure_tracker = _Tracker
    try:
        probe = _Probe()
        probe._track_consecutive_failures("partial")
        assert calls == []
        probe._track_consecutive_failures("done")
        assert calls == [("success", "probe")]
        probe._track_consecutive_failures("error")
        assert calls[-1] == ("failure", "probe")
    finally:
        base_mod._agent_failure_tracker = original


# ── Integration: the real _handle_turn_limit against a temp agent dir ───────


def _make_runner(tmp_path, monkeypatch, agent_name="contagent", continuation="0"):
    """Build a real AgentRunner over a temp project root."""
    from app.config import settings

    monkeypatch.setattr(
        type(settings), "project_root", property(lambda self: tmp_path)
    )
    agents_dir = tmp_path / "app" / "agents"
    agent_dir = agents_dir / agent_name
    agent_dir.mkdir(parents=True)
    monkeypatch.setattr(
        type(settings), "agents_dir", property(lambda self: agents_dir)
    )
    (agent_dir / "TASK.MD").write_text(
        "---\n"
        "status: running\n"
        "task_id: task-123\n"
        "assigned_by: master\n"
        "assigned_at: 2026-09-07T10:00:00Z\n"
        f"continuation: {continuation}\n"
        "---\n"
        "## Task\nImplement the widget.\n\n"
        "## Context\nbackground info\n\n"
        "## Result\n\n"
    )
    # RESULT.MD is a memory-dir file (BaseAgent._is_memory_file), not an
    # agent-dir file — the runner reads it back from there.
    memory_dir = tmp_path / "app" / "memory" / "agents" / agent_name
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "RESULT.MD").write_text(
        "Explored the repo.\n## Findings\nWidget lives in widget.py."
    )
    runner = AgentRunner(agent_name)
    return runner, agent_dir, memory_dir


async def test_turn_limit_salvages_and_reenqueues(tmp_path, monkeypatch):
    """The golden path: partial work is kept and the task goes back to pending."""
    from app.config import settings

    monkeypatch.setattr(settings, "max_task_continuations", 3)
    runner, agent_dir, memory_dir = _make_runner(tmp_path, monkeypatch)

    recorded = []
    monkeypatch.setattr(
        "app.utils.db.insert_task",
        lambda **kw: recorded.append(kw) or 1,
    )
    notified = []

    async def _fake_notify(text, status):
        notified.append((text, status))

    monkeypatch.setattr(runner, "_notify_parent_via_bus", _fake_notify)

    await runner._handle_turn_limit(
        TurnLimitReached(30, "fallback text"),
        "Implement the widget.",
        {"task_id": "task-123"},
    )

    task_md = (agent_dir / "TASK.MD").read_text()
    # Re-enqueued, not finished.
    assert "status: pending" in task_md
    assert "continuation: 1" in task_md
    # The salvaged work made it into the new body, headers neutralized.
    body = _get_task_body(task_md)
    assert "Implement the widget." in body
    assert "Widget lives in widget.py." in body
    assert "\n## Findings" not in body
    # Recorded as partial, carrying BOTH the result and the reason.
    assert len(recorded) == 1
    assert recorded[0]["status"] == "partial"
    assert "Widget lives in widget.py." in recorded[0]["result_summary"]
    assert "30-turn limit" in recorded[0]["error_summary"]
    assert recorded[0]["task_id"] == "task-123"
    # The parent is NOT told it failed — the task is still in flight.
    assert notified == []


async def test_continuation_budget_exhausted_is_a_hard_error(tmp_path, monkeypatch):
    """Burning the budget must be a LOUDER failure, not a silent partial."""
    from app.config import settings

    monkeypatch.setattr(settings, "max_task_continuations", 3)
    runner, agent_dir, memory_dir = _make_runner(tmp_path, monkeypatch, continuation="3")

    recorded = []
    monkeypatch.setattr(
        "app.utils.db.insert_task", lambda **kw: recorded.append(kw) or 1
    )
    notified = []

    async def _fake_notify(text, status):
        notified.append((text, status))

    monkeypatch.setattr(runner, "_notify_parent_via_bus", _fake_notify)

    await runner._handle_turn_limit(
        TurnLimitReached(30, "fallback"), "Implement the widget.", {}
    )

    task_md = (agent_dir / "TASK.MD").read_text()
    assert "status: error" in task_md
    assert "status: pending" not in task_md
    assert recorded[0]["status"] == "error"
    assert "budget exhausted" in recorded[0]["error_summary"].lower()
    # The parent IS told, so the failure counter and alert path engage.
    assert len(notified) == 1
    assert notified[0][1] == "error"


async def test_continuation_clears_the_dedup_guard(tmp_path, monkeypatch):
    """Without this the re-enqueued task is skipped as a duplicate delivery."""
    from app.config import settings

    monkeypatch.setattr(settings, "max_task_continuations", 3)
    runner, _, _ = _make_runner(tmp_path, monkeypatch)
    monkeypatch.setattr("app.utils.db.insert_task", lambda **kw: 1)

    async def _fake_notify(text, status):
        pass

    monkeypatch.setattr(runner, "_notify_parent_via_bus", _fake_notify)

    # Simulate _run_task having recorded this id as executed.
    runner._recent_task_ids.append("task-123")
    assert "task-123" in runner._recent_task_ids

    await runner._handle_turn_limit(
        TurnLimitReached(30, "x"), "Implement the widget.", {}
    )

    assert "task-123" not in runner._recent_task_ids


async def test_no_partial_output_is_a_hard_error(tmp_path, monkeypatch):
    """Nothing to continue from means there is nothing to salvage — fail."""
    from app.config import settings

    monkeypatch.setattr(settings, "max_task_continuations", 3)
    runner, agent_dir, memory_dir = _make_runner(tmp_path, monkeypatch)
    (memory_dir / "RESULT.MD").write_text("   ")

    recorded = []
    monkeypatch.setattr(
        "app.utils.db.insert_task", lambda **kw: recorded.append(kw) or 1
    )

    async def _fake_notify(text, status):
        pass

    monkeypatch.setattr(runner, "_notify_parent_via_bus", _fake_notify)

    await runner._handle_turn_limit(TurnLimitReached(30, ""), "Do it.", {})

    assert recorded[0]["status"] == "error"
    assert "no partial output" in recorded[0]["error_summary"].lower()


async def test_continuation_disabled_restores_old_behaviour(tmp_path, monkeypatch):
    """max_task_continuations=0 must behave exactly like the old terminal error."""
    from app.config import settings

    monkeypatch.setattr(settings, "max_task_continuations", 0)
    runner, agent_dir, memory_dir = _make_runner(tmp_path, monkeypatch)

    recorded = []
    monkeypatch.setattr(
        "app.utils.db.insert_task", lambda **kw: recorded.append(kw) or 1
    )
    notified = []

    async def _fake_notify(text, status):
        notified.append((text, status))

    monkeypatch.setattr(runner, "_notify_parent_via_bus", _fake_notify)

    await runner._handle_turn_limit(TurnLimitReached(45, "x"), "Do it.", {})

    assert recorded[0]["status"] == "error"
    assert "status: error" in (agent_dir / "TASK.MD").read_text()
    assert notified[0][1] == "error"


# ── Wiring: does the raise in BaseAgent actually reach the runner handler? ──


async def test_turn_limit_propagates_from_agent_loop_to_continuation(
    tmp_path, monkeypatch
):
    """End-to-end wiring test with a fake adapter that never finishes.

    The tests above call `_handle_turn_limit` directly, which does not prove
    that BaseAgent's turn loop raises TurnLimitReached, nor that `_run_task`
    catches it ahead of its generic `except Exception`. This drives the real
    loop with an adapter that always asks for another tool call, so `max_turns`
    is genuinely exhausted, and asserts the task comes out re-enqueued rather
    than errored.
    """
    from app.config import settings
    from app.utils.adapters import AgentConfig, TextDelta, ToolCall, TurnComplete

    monkeypatch.setattr(settings, "max_task_continuations", 3)
    runner, agent_dir, memory_dir = _make_runner(tmp_path, monkeypatch, "loopagent")
    (memory_dir / "RESULT.MD").write_text("")
    # max_turns: 2 keeps the test fast; the ceiling value is irrelevant.
    (agent_dir / "CONFIG.yaml").write_text(
        "adapter: fake\nmodel: fake-1\ntools:\n  - file_list\n"
        "runner:\n  max_turns: 2\n  task_timeout: 60\n"
    )
    (agent_dir / "PROMPT.MD").write_text("You are a test agent.")

    class _NeverFinishesAdapter:
        """Emits text then asks for a tool call, every turn, forever."""

        def __init__(self):
            self.turns = 0

        def context_window_size(self):
            return 200_000

        async def stream_with_tools(self, system_prompt, messages, tools):
            self.turns += 1
            yield TextDelta(text=f"working (turn {self.turns}) ")
            # A real tool call every turn, so the loop always has a reason to
            # take another turn and genuinely runs the budget down.
            call = ToolCall(
                id=f"call_{self.turns}", name="file_list", input={"path": "."}
            )
            yield TurnComplete(
                stop_reason="tool_use",
                tool_calls=[call],
                assistant_content=[
                    {"type": "text", "text": f"working (turn {self.turns})"},
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": call.input,
                    },
                ],
            )

    fake = _NeverFinishesAdapter()

    async def _fake_load_adapter(self, config):
        return fake

    async def _fake_load_config(self, config_raw=None):
        return AgentConfig(
            adapter="fake", model="fake-1", temperature=0.0, max_tokens=100
        )

    monkeypatch.setattr(
        "app.agents.base.BaseAgent._load_adapter", _fake_load_adapter
    )
    monkeypatch.setattr("app.agents.base.BaseAgent._load_config", _fake_load_config)

    recorded = []
    monkeypatch.setattr(
        "app.utils.db.insert_task", lambda **kw: recorded.append(kw) or 1
    )
    monkeypatch.setattr("app.utils.db.init_schema", lambda: None)

    notified = []

    async def _fake_notify(text, status):
        notified.append((text, status))

    monkeypatch.setattr(runner, "_notify_parent_via_bus", _fake_notify)
    monkeypatch.setattr(runner, "_write_status", lambda *a, **k: None)

    await runner._run_task("Implement the widget.")

    # The loop really ran out of turns rather than erroring early.
    assert fake.turns == 2, f"expected 2 turns, adapter saw {fake.turns}"
    # And the outcome is a continuation, not a failure.
    assert recorded, "no task row was recorded"
    assert recorded[-1]["status"] == "partial", recorded[-1]
    task_md = (agent_dir / "TASK.MD").read_text()
    assert "status: pending" in task_md
    assert "continuation: 1" in task_md
    assert AgentRunner._CONTINUATION_HEADER in _get_task_body(task_md)
    # Parent not told of a failure — the task is still in flight.
    assert notified == []
