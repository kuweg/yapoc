"""Phase 5 — an empty provider response must not kill the task on first sight.

The evaluator reported this against `master` for 12 rounds: "provider returned
no answer or tool calls", 3 times in one 2.5-hour window. A turn producing no
text and no tool calls raised immediately — a one-shot hard failure on a classic
transient, where the very next attempt usually succeeds.
"""

from __future__ import annotations

import pytest

from app.utils.adapters import AgentConfig, TextDelta, TurnComplete


def _make_agent(tmp_path, monkeypatch, name="emptyagent", max_turns=6):
    from app.config import settings

    monkeypatch.setattr(type(settings), "project_root", property(lambda self: tmp_path))
    agents_dir = tmp_path / "app" / "agents"
    agent_dir = agents_dir / name
    agent_dir.mkdir(parents=True)
    monkeypatch.setattr(type(settings), "agents_dir", property(lambda self: agents_dir))
    (agent_dir / "CONFIG.yaml").write_text(
        f"adapter: fake\nmodel: fake-1\ntools:\n  - file_list\n"
        f"runner:\n  max_turns: {max_turns}\n  task_timeout: 60\n"
    )
    (agent_dir / "PROMPT.MD").write_text("test agent")
    (agent_dir / "TASK.MD").write_text(
        "---\nstatus: running\ntask_id: t1\n---\n## Task\nSay something.\n\n## Result\n\n"
    )
    (tmp_path / "app" / "memory" / "agents" / name).mkdir(parents=True)

    from app.agents.base import BaseAgent

    return BaseAgent(agent_dir)


class _EmptyThenAnswers:
    """Returns nothing at all for `empty_turns`, then a real answer."""

    def __init__(self, empty_turns: int):
        self.empty_turns = empty_turns
        self.turns = 0

    def context_window_size(self):
        return 200_000

    async def stream_with_tools(self, system_prompt, messages, tools):
        self.turns += 1
        if self.turns <= self.empty_turns:
            # No text, no tool calls — the exact shape that used to be fatal.
            yield TurnComplete(stop_reason="end_turn", tool_calls=[], assistant_content=[])
        else:
            yield TextDelta(text="the real answer")
            yield TurnComplete(
                stop_reason="end_turn", tool_calls=[],
                assistant_content=[{"type": "text", "text": "the real answer"}],
            )


def _wire(monkeypatch, adapter):
    async def _load_adapter(self, config):
        return adapter

    async def _load_config(self, config_raw=None):
        return AgentConfig(adapter="fake", model="fake-1", temperature=0.0, max_tokens=100)

    monkeypatch.setattr("app.agents.base.BaseAgent._load_adapter", _load_adapter)
    monkeypatch.setattr("app.agents.base.BaseAgent._load_config", _load_config)


async def _run(agent):
    out = []
    async for event in agent.run_stream_with_tools(manage_task_file=False):
        out.append(event)
    return out


async def test_one_empty_response_is_survived(tmp_path, monkeypatch):
    """The reported failure: a single empty turn used to end the task."""
    agent = _make_agent(tmp_path, monkeypatch)
    adapter = _EmptyThenAnswers(empty_turns=1)
    _wire(monkeypatch, adapter)

    await _run(agent)

    assert adapter.turns == 2, "did not retry after the empty response"
    result = (tmp_path / "app" / "memory" / "agents" / "emptyagent" / "RESULT.MD").read_text()
    assert "the real answer" in result


async def test_two_empty_responses_are_survived(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path, monkeypatch)
    adapter = _EmptyThenAnswers(empty_turns=2)
    _wire(monkeypatch, adapter)

    await _run(agent)

    assert adapter.turns == 3
    result = (tmp_path / "app" / "memory" / "agents" / "emptyagent" / "RESULT.MD").read_text()
    assert "the real answer" in result


async def test_retries_are_bounded_not_infinite(tmp_path, monkeypatch):
    """A provider stuck returning nothing must still terminate.

    Retrying forever would convert a dead provider into a hung agent, which is
    worse than the original failure.
    """
    agent = _make_agent(tmp_path, monkeypatch, name="alwaysempty", max_turns=20)
    adapter = _EmptyThenAnswers(empty_turns=999)
    _wire(monkeypatch, adapter)

    with pytest.raises(RuntimeError) as excinfo:
        await _run(agent)

    assert "no answer or tool calls" in str(excinfo.value)
    # 2 retries after the first attempt, then it gives up — well under max_turns,
    # so the bound comes from the retry budget rather than turn exhaustion.
    assert adapter.turns == 3, f"expected 3 attempts, got {adapter.turns}"


async def test_the_retry_nudges_rather_than_repeating_silently(tmp_path, monkeypatch):
    """The model should be told its last response was empty."""
    agent = _make_agent(tmp_path, monkeypatch, name="nudged")
    seen: list[list[dict]] = []

    class _Recording(_EmptyThenAnswers):
        async def stream_with_tools(self, system_prompt, messages, tools):
            seen.append([m for m in messages if m.get("role") == "user"])
            async for ev in super().stream_with_tools(system_prompt, messages, tools):
                yield ev

    adapter = _Recording(empty_turns=1)
    _wire(monkeypatch, adapter)
    await _run(agent)

    assert len(seen) >= 2
    second_turn_user_msgs = " ".join(str(m.get("content", "")) for m in seen[1])
    assert "empty" in second_turn_user_msgs.lower()
