"""Anthropic Claude model catalog.

Source: https://platform.claude.com/docs/en/about-claude/pricing
         https://platform.claude.com/docs/en/about-claude/models
"""

from __future__ import annotations

from .base import ModelInfo

# ── Current models ───────────────────────────────────────────────────────────

MODELS: list[ModelInfo] = [
    # Latest generation
    ModelInfo(
        id="claude-opus-4-6",
        context_window=1_000_000,
        max_output=128_000,
        input_price=5.0,
        output_price=25.0,
        description="Most intelligent model for agents and coding",
    ),
    ModelInfo(
        id="claude-sonnet-4-6",
        context_window=1_000_000,
        max_output=64_000,
        input_price=3.0,
        output_price=15.0,
        description="Best combination of speed and intelligence",
    ),
    ModelInfo(
        id="claude-haiku-4-5-20251001",
        context_window=200_000,
        max_output=64_000,
        input_price=1.0,
        output_price=5.0,
        description="Fastest model with near-frontier intelligence",
    ),
    # Previous generation
    ModelInfo(
        id="claude-sonnet-4-5-20250929",
        context_window=1_000_000,
        max_output=64_000,
        input_price=3.0,
        output_price=15.0,
        description="Previous-gen Sonnet",
    ),
    ModelInfo(
        id="claude-opus-4-5-20251101",
        context_window=200_000,
        max_output=64_000,
        input_price=5.0,
        output_price=25.0,
        description="Previous-gen Opus",
    ),
    ModelInfo(
        id="claude-opus-4-1-20250805",
        context_window=200_000,
        max_output=32_000,
        input_price=15.0,
        output_price=75.0,
        description="Opus 4.1",
    ),
    ModelInfo(
        id="claude-sonnet-4-20250514",
        context_window=1_000_000,
        max_output=64_000,
        input_price=3.0,
        output_price=15.0,
        description="Claude Sonnet 4",
    ),
    ModelInfo(
        id="claude-opus-4-20250514",
        context_window=200_000,
        max_output=32_000,
        input_price=15.0,
        output_price=75.0,
        description="Claude Opus 4",
    ),
    # Legacy (still available)
    ModelInfo(
        id="claude-3-5-haiku-20241022",
        context_window=200_000,
        max_output=8_192,
        input_price=0.80,
        output_price=4.0,
        description="Claude 3.5 Haiku (legacy)",
    ),
    ModelInfo(
        id="claude-3-haiku-20240307",
        context_window=200_000,
        max_output=4_096,
        input_price=0.25,
        output_price=1.25,
        supports_tools=True,
        description="Claude 3 Haiku (deprecated, retiring Apr 2026)",
    ),
]
