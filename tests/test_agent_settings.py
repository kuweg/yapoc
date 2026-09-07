"""Focused tests for runner-setting precedence."""

from app.utils import agent_settings
from app.agents.base.context import _parse_runner_config


def _resolve_max_turns(agent_name: str, config_text: str) -> int:
    """Mirror BaseAgent's per-field runner precedence."""
    json_runner = agent_settings.resolve_runner_settings(agent_name)
    config_runner = _parse_runner_config(config_text)
    value = json_runner.get("max_turns")
    if value is None:
        value = config_runner.get("max_turns")
    if value is None:
        value = agent_settings.settings.max_turns
    return value


def test_runner_settings_omit_absent_json_keys(monkeypatch):
    monkeypatch.setattr(
        agent_settings,
        "_read",
        lambda: {"agents": {"example": {"task_timeout": 600}}},
    )

    assert agent_settings.resolve_runner_settings("example") == {"task_timeout": 600}


def test_config_max_turns_used_when_json_has_no_override(monkeypatch):
    monkeypatch.setattr(
        agent_settings,
        "_read",
        lambda: {"agents": {"example": {"task_timeout": 600}}},
    )

    assert _resolve_max_turns("example", "runner:\n  max_turns: 30\n") == 30


def test_explicit_json_max_turns_overrides_config(monkeypatch):
    monkeypatch.setattr(
        agent_settings,
        "_read",
        lambda: {"agents": {"example": {"max_turns": 12}}},
    )

    assert _resolve_max_turns("example", "runner:\n  max_turns: 30\n") == 12
