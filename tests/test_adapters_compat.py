"""Compatibility tests for adapter request-shape quirks."""

from app.utils.adapters.deepseek import (
    _normalize_to_deepseek,
    _supports_reasoning_replay,
)
from app.utils.adapters.openai import _needs_max_completion_tokens


def test_openai_uses_max_completion_tokens_for_gpt5_family() -> None:
    assert _needs_max_completion_tokens("gpt-5.4-mini")
    assert _needs_max_completion_tokens("gpt-5.2")
    assert _needs_max_completion_tokens("openai/gpt-5.4-nano")
    assert not _needs_max_completion_tokens("gpt-4.1-mini")


def test_deepseek_normalize_replays_assistant_reasoning_content() -> None:
    messages = [
        {
            "role": "assistant",
            "content": [
                {"type": "reasoning", "text": "first thought"},
                {"type": "thinking", "thinking": "second thought"},
                {"type": "text", "text": "Let me call a tool."},
                {"type": "tool_use", "id": "tc_1", "name": "some_tool", "input": {"ok": True}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "tc_1", "content": "verified"},
            ],
        },
    ]

    out = _normalize_to_deepseek(messages, include_reasoning_content=True)
    assert out[0]["role"] == "assistant"
    assert out[0]["content"] == "Let me call a tool."
    assert out[0]["reasoning_content"] == "first thought\nsecond thought"
    assert out[0]["tool_calls"][0]["function"]["name"] == "some_tool"
    assert out[1]["role"] == "tool"
    assert out[1]["tool_call_id"] == "tc_1"
    assert out[1]["content"] == "verified"


def test_deepseek_reasoner_mode_does_not_replay_reasoning_content() -> None:
    messages = [
        {
            "role": "assistant",
            "content": [{"type": "reasoning", "text": "hidden"}],
        }
    ]

    out = _normalize_to_deepseek(messages, include_reasoning_content=False)
    assert out[0]["role"] == "assistant"
    assert "reasoning_content" not in out[0]


def test_supports_reasoning_replay_is_disabled_for_every_model() -> None:
    """Reasoning replay is off for ALL DeepSeek models, not gated per model.

    This was a per-model gate until c64e8d7 (2026-09-07), which disabled
    thinking for every DeepSeek request. The test kept asserting the old gate
    and so failed on every run. Pinning the current contract instead: no model
    replays reasoning_content, so no caller can accidentally reintroduce a
    per-model exception without updating this.
    """
    for model in ("deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner",
                  "deepseek-v4-flash", "anything-else"):
        assert not _supports_reasoning_replay(model), model
