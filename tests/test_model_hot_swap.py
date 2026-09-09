"""Model/provider hot swap — rebinding an agent without restarting anything.

Two halves are covered here:

* ``app.utils.agent_settings`` persists the new binding, and exposes a
  cross-process generation token so a *running* agent can notice the change.
* ``BaseAgent.run_stream_with_tools`` acts on that token between turns, so a
  swap issued mid-task takes effect on the next turn rather than at the next
  process start.
"""

from __future__ import annotations

import json

import pytest

from app.utils import agent_settings
from app.utils.adapters import AgentConfig, ModelSwapped, TextDelta, ToolCall, TurnComplete


# ── Persistence + generation token ──────────────────────────────────────────


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """Point agent_settings at a throwaway file seeded with two agents."""
    path = tmp_path / "agent-settings.json"
    path.write_text(json.dumps({
        "version": 2,
        "default_n_fallbacks_models": 3,
        "agents": {
            "master": {
                "adapter": "anthropic", "model": "claude-sonnet-5",
                "temperature": 0.3, "max_tokens": 8096,
                "fallbacks": [{"adapter": "openai", "model": "gpt-4o-mini"}],
            },
            "builder": {
                "adapter": "anthropic", "model": "claude-sonnet-5",
                "temperature": 0.2, "max_tokens": 8096, "fallbacks": [],
            },
        },
    }))
    monkeypatch.setattr(agent_settings, "SETTINGS_PATH", path)
    monkeypatch.setattr(agent_settings, "_LEGACY_PATHS", [])
    return path


def test_swap_is_visible_to_the_next_reader_with_no_restart(settings_file):
    agent_settings.swap_agent_model("master", "openai", "gpt-4o-mini")

    # No cache to invalidate and no process to bounce: the very next resolve
    # already reports the new binding.
    entry = agent_settings.resolve_agent("master")
    assert (entry["adapter"], entry["model"]) == ("openai", "gpt-4o-mini")
    assert agent_settings.build_adapter_chain("master")[0].model == "gpt-4o-mini"


def test_swap_preserves_tuning_and_fallbacks(settings_file):
    agent_settings.swap_agent_model("master", "openai", "gpt-4o-mini")

    entry = agent_settings.resolve_agent("master")
    assert entry["temperature"] == 0.3
    assert entry["max_tokens"] == 8096
    assert entry["fallbacks"] == [{"adapter": "openai", "model": "gpt-4o-mini"}]


def test_generation_changes_on_swap_so_running_agents_can_notice(settings_file):
    before = agent_settings.config_generation()
    agent_settings.swap_agent_model("master", "openai", "gpt-4o-mini")
    assert agent_settings.config_generation() != before


def test_unknown_adapter_is_rejected_without_writing(settings_file):
    original = settings_file.read_text()
    with pytest.raises(ValueError, match="Unknown adapter"):
        agent_settings.swap_agent_model("master", "nope", "gpt-4o-mini")
    assert settings_file.read_text() == original


def test_model_not_offered_by_adapter_is_rejected(settings_file):
    original = settings_file.read_text()
    with pytest.raises(ValueError, match="not offered by adapter"):
        agent_settings.swap_agent_model("master", "openai", "claude-sonnet-5")
    assert settings_file.read_text() == original


def test_unlisted_agent_gets_an_entry(settings_file):
    """Agents created at runtime aren't in the file yet — swapping must still work."""
    agent_settings.swap_agent_model("dynamic-1", "openai", "gpt-4o-mini")

    entry = agent_settings.resolve_agent("dynamic-1")
    assert (entry["adapter"], entry["model"]) == ("openai", "gpt-4o-mini")
    assert entry["fallbacks"] == []


def test_provider_swap_defaults_to_every_listed_agent(settings_file):
    agent_settings.swap_provider("openai", "gpt-4o-mini")

    for name in ("master", "builder"):
        entry = agent_settings.resolve_agent(name)
        assert (entry["adapter"], entry["model"]) == ("openai", "gpt-4o-mini")
    # Per-agent tuning is a separate concern from the provider binding.
    assert agent_settings.resolve_agent("builder")["temperature"] == 0.2


def test_provider_swap_can_target_a_subset(settings_file):
    agent_settings.swap_provider("openai", "gpt-4o-mini", ["builder"])

    assert agent_settings.resolve_agent("builder")["adapter"] == "openai"
    assert agent_settings.resolve_agent("master")["adapter"] == "anthropic"


def test_provider_swap_is_all_or_nothing(settings_file):
    """A bad model must not leave half the fleet on the new provider."""
    original = settings_file.read_text()
    with pytest.raises(ValueError):
        agent_settings.swap_provider("openai", "claude-sonnet-5")
    assert settings_file.read_text() == original


# ── Mid-task hot swap in the run loop ───────────────────────────────────────


def _make_agent(tmp_path, monkeypatch, name="swapagent", max_turns=6):
    from app.config import settings

    monkeypatch.setattr(type(settings), "project_root", property(lambda self: tmp_path))
    agents_dir = tmp_path / "app" / "agents"
    agent_dir = agents_dir / name
    agent_dir.mkdir(parents=True)
    monkeypatch.setattr(type(settings), "agents_dir", property(lambda self: agents_dir))
    (agent_dir / "CONFIG.yaml").write_text(
        f"adapter: fake\nmodel: old-1\ntools:\n  - file_list\n"
        f"runner:\n  max_turns: {max_turns}\n  task_timeout: 60\n"
    )
    (agent_dir / "PROMPT.MD").write_text("test agent")
    (agent_dir / "TASK.MD").write_text(
        "---\nstatus: running\ntask_id: t1\n---\n## Task\nSay something.\n\n## Result\n\n"
    )
    (tmp_path / "app" / "memory" / "agents" / name).mkdir(parents=True)

    from app.agents.base import BaseAgent

    return BaseAgent(agent_dir)


class _FakeAdapter:
    """Emits `stall_turns` tool calls, then a final answer.

    The stall exists purely to create a turn boundary for a swap to land on:
    the outgoing adapter stalls once, the incoming one answers straight away,
    so which adapter served which turn is unambiguous from the turn counts.
    """

    def __init__(self, label: str, *, stall_turns: int = 0, window: int = 200_000):
        self.label = label
        self.turns = 0
        self.stall_turns = stall_turns
        self.window = window

    def context_window_size(self):
        return self.window

    async def stream_with_tools(self, system_prompt, messages, tools):
        self.turns += 1
        if self.turns <= self.stall_turns:
            yield TurnComplete(
                stop_reason="tool_use",
                tool_calls=[ToolCall(id=f"c{self.turns}", name="file_list", input={"path": "."})],
                assistant_content=[{
                    "type": "tool_use", "id": f"c{self.turns}",
                    "name": "file_list", "input": {"path": "."},
                }],
            )
        else:
            yield TextDelta(text=f"answered by {self.label}")
            yield TurnComplete(
                stop_reason="end_turn", tool_calls=[],
                assistant_content=[{"type": "text", "text": f"answered by {self.label}"}],
            )


def _wire_swap(monkeypatch, old, new, *, swap_after_checks=2):
    """Serve `old` until the settings generation moves, then `new`.

    ``swap_after_checks`` counts calls to ``config_generation``: one for the
    baseline captured before the loop, then one at the top of each turn. The
    default lands the swap between turn 0 and turn 1, i.e. mid-task.
    """
    state = {"gen": 1, "checks": 0}

    def _generation():
        state["checks"] += 1
        if state["checks"] > swap_after_checks:
            state["gen"] = 2
        return state["gen"]

    async def _load_config(self, config_raw=None):
        if state["gen"] == 1:
            return AgentConfig(adapter="fake", model="old-1", temperature=0.0, max_tokens=100)
        return AgentConfig(adapter="fake2", model="new-1", temperature=0.0, max_tokens=100)

    async def _load_adapter(self, config):
        return old if config.model == "old-1" else new

    monkeypatch.setattr("app.agents.base._agent_settings.config_generation", _generation)
    monkeypatch.setattr("app.agents.base.BaseAgent._load_adapter", _load_adapter)
    monkeypatch.setattr("app.agents.base.BaseAgent._load_config", _load_config)
    return state


async def _run(agent):
    return [event async for event in agent.run_stream_with_tools(manage_task_file=False)]


async def test_swap_takes_effect_on_the_next_turn_of_a_running_task(tmp_path, monkeypatch):
    """The point of the feature: no restart, and no waiting for the task to end."""
    agent = _make_agent(tmp_path, monkeypatch)
    old = _FakeAdapter("old", stall_turns=1)
    new = _FakeAdapter("new")
    _wire_swap(monkeypatch, old, new)

    await _run(agent)

    assert old.turns == 1, "first turn should have used the original provider"
    assert new.turns == 1, "second turn should have used the swapped-in provider"
    result = (tmp_path / "app" / "memory" / "agents" / "swapagent" / "RESULT.MD").read_text()
    assert "answered by new" in result


async def test_swap_emits_a_model_swapped_event(tmp_path, monkeypatch):
    """The UI renders the live model in each agent's title, so it needs the event."""
    agent = _make_agent(tmp_path, monkeypatch, name="swapevent")
    _wire_swap(monkeypatch, _FakeAdapter("old", stall_turns=1), _FakeAdapter("new"))

    events = [e for e in await _run(agent) if isinstance(e, ModelSwapped)]

    assert len(events) == 1
    assert (events[0].agent, events[0].adapter, events[0].model) == ("swapevent", "fake2", "new-1")


async def test_swap_moves_the_compaction_threshold_to_the_new_window(tmp_path, monkeypatch):
    """A smaller window must start compacting sooner, or the new provider 413s.

    Thresholds are loop-local, so they are observed here through their effect:
    a context that was comfortable at 200k is over the line at 100, and the
    next turn compacts. Carrying the old threshold across the swap would send
    an oversized request to the new provider instead.
    """
    from app.utils.adapters import CompactEvent

    agent = _make_agent(tmp_path, monkeypatch, name="swapwindow")
    old = _FakeAdapter("old", stall_turns=1, window=200_000)
    new = _FakeAdapter("new", window=100)
    _wire_swap(monkeypatch, old, new)

    events = await _run(agent)

    assert any(isinstance(e, ModelSwapped) for e in events)
    assert any(isinstance(e, CompactEvent) for e in events), (
        "compaction did not re-arm against the new provider's window"
    )


async def test_unchanged_config_does_not_rebuild_the_adapter(tmp_path, monkeypatch):
    """An unrelated write to the settings file must not churn the live adapter."""
    agent = _make_agent(tmp_path, monkeypatch, name="noswap")
    old, new = _FakeAdapter("old", stall_turns=1), _FakeAdapter("new")

    state = {"gen": 1}

    def _generation():
        # The file was touched, but this agent's binding is identical.
        state["gen"] += 1
        return state["gen"]

    async def _load_config(self, config_raw=None):
        return AgentConfig(adapter="fake", model="old-1", temperature=0.0, max_tokens=100)

    async def _load_adapter(self, config):
        return old

    monkeypatch.setattr("app.agents.base._agent_settings.config_generation", _generation)
    monkeypatch.setattr("app.agents.base.BaseAgent._load_adapter", _load_adapter)
    monkeypatch.setattr("app.agents.base.BaseAgent._load_config", _load_config)

    events = await _run(agent)

    assert old.turns == 2
    assert new.turns == 0
    assert not any(isinstance(e, ModelSwapped) for e in events)


async def test_a_broken_config_reload_keeps_the_running_model(tmp_path, monkeypatch):
    """A half-written settings file must not take down a healthy task."""
    agent = _make_agent(tmp_path, monkeypatch, name="brokenswap")
    old = _FakeAdapter("old", stall_turns=1)

    monkeypatch.setattr(
        "app.agents.base._agent_settings.config_generation",
        lambda: __import__("time").time_ns(),  # always "changed"
    )

    async def _load_config(self, config_raw=None):
        if getattr(self, "_seen_once", False):
            raise ValueError("truncated JSON")
        self._seen_once = True
        return AgentConfig(adapter="fake", model="old-1", temperature=0.0, max_tokens=100)

    async def _load_adapter(self, config):
        return old

    monkeypatch.setattr("app.agents.base.BaseAgent._load_adapter", _load_adapter)
    monkeypatch.setattr("app.agents.base.BaseAgent._load_config", _load_config)

    await _run(agent)

    assert old.turns == 2, "the task should have finished on the model it started with"
    result = (tmp_path / "app" / "memory" / "agents" / "brokenswap" / "RESULT.MD").read_text()
    assert "answered by old" in result


async def test_agent_flow_receives_provider_usage(tmp_path, monkeypatch):
    from app.utils.adapters import UsageStats

    class UsageAdapter(_FakeAdapter):
        async def stream_with_tools(self, system_prompt, messages, tools):
            yield UsageStats(input_tokens=1200, output_tokens=75,
                             tokens_per_second=25.0, context_window=200000)
            async for event in super().stream_with_tools(system_prompt, messages, tools):
                yield event

    agent = _make_agent(tmp_path, monkeypatch)
    adapter = UsageAdapter('usage')
    _wire_swap(monkeypatch, adapter, adapter, swap_after_checks=100)
    activity = []

    async def capture(kind, payload):
        activity.append((kind, payload))

    monkeypatch.setattr(agent, '_emit_event', capture)
    streamed = await _run(agent)
    assert any(isinstance(event, UsageStats) for event in streamed)
    usage = [payload for kind, payload in activity if kind == 'usage_stats']
    assert usage == [{'model': 'old-1', 'adapter': 'fake', 'input_tokens': 1200,
                      'output_tokens': 75, 'tokens_per_second': 25.0, 'context_window': 200000}]
