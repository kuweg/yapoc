"""Phase 5 — the Anthropic adapter sent an impossible thinking config.

Found by following an evaluator finding: a spawned agent's HEALTH.MD contained

    400 - thinking.adaptive.budget_tokens: Extra inputs are not permitted

The adapter sent `{"type": "adaptive", "budget_tokens": N}`. Those are two
different shapes: adaptive thinking takes no budget, and `budget_tokens`
belongs to the older `{"type": "enabled"}` form. The combination is rejected
outright, so every Anthropic request with thinking on was a hard 400.
"""

from __future__ import annotations

import pytest

from app.utils.adapters.anthropic import (
    _supports_adaptive_thinking,
    build_thinking_kwargs,
)


@pytest.mark.parametrize(
    "model",
    ["claude-sonnet-4-6", "claude-opus-4-6", "claude-opus-4-7", "claude-opus-4-8",
     "claude-opus-5", "claude-sonnet-5", "claude-fable-5-1"],
)
def test_modern_models_use_adaptive(model):
    assert _supports_adaptive_thinking(model)


@pytest.mark.parametrize(
    "model", ["claude-haiku-4-5", "claude-sonnet-4-5", "claude-3-5-sonnet", "", "gpt-5.6-terra"]
)
def test_pre_4_6_models_keep_the_budget_form(model):
    """`budget_tokens` is still the correct shape for older models."""
    assert not _supports_adaptive_thinking(model)


def test_adaptive_config_never_carries_budget_tokens():
    """The exact 400 that was hitting production, asserted on real output."""
    kw = build_thinking_kwargs(
        model="claude-sonnet-4-6", thinking_enabled=True,
        temperature=0.3, budget_tokens=24000,
    )
    assert kw["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert "budget_tokens" not in kw["thinking"]


def test_adaptive_omits_sampling_parameters():
    """Sampling params are rejected on adaptive models newer than 4.6."""
    kw = build_thinking_kwargs(
        model="claude-opus-5", thinking_enabled=True,
        temperature=0.3, budget_tokens=24000,
    )
    assert "temperature" not in kw
    assert "top_p" not in kw and "top_k" not in kw


def test_adaptive_sets_display_so_thinking_is_not_empty():
    """`display` defaults to omitted on newer models, emptying ThinkingDelta."""
    kw = build_thinking_kwargs(
        model="claude-opus-5", thinking_enabled=True,
        temperature=0.3, budget_tokens=24000,
    )
    assert kw["thinking"]["display"] == "summarized"


def test_pre_4_6_model_keeps_the_budget_form():
    kw = build_thinking_kwargs(
        model="claude-haiku-4-5", thinking_enabled=True,
        temperature=0.3, budget_tokens=24000,
    )
    assert kw["thinking"] == {"type": "enabled", "budget_tokens": 24000}
    # The old form did require temperature=1.0 and the interleaved beta header.
    assert kw["temperature"] == 1.0
    assert "interleaved-thinking" in kw["extra_headers"]["anthropic-beta"]


def test_thinking_disabled_uses_the_configured_temperature():
    kw = build_thinking_kwargs(
        model="claude-opus-5", thinking_enabled=False,
        temperature=0.42, budget_tokens=24000,
    )
    assert kw == {"temperature": 0.42}
    assert "thinking" not in kw


def test_no_config_mixes_the_two_shapes():
    """adaptive+budget_tokens and enabled-without-budget are both invalid."""
    for model in ("claude-sonnet-4-6", "claude-opus-5", "claude-haiku-4-5",
                  "claude-sonnet-4-5", "gpt-5.6-terra"):
        kw = build_thinking_kwargs(
            model=model, thinking_enabled=True, temperature=0.3, budget_tokens=24000,
        )
        block = kw.get("thinking")
        if not block:
            continue
        if block["type"] == "adaptive":
            assert "budget_tokens" not in block, model
        else:
            assert block.get("budget_tokens"), model
