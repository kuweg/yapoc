"""OpenRouter model catalog (static fallback).

OpenRouter provides dynamic model listing via GET /api/v1/models.
This static catalog is used as fallback when the API key is missing
or the fetch fails. Models use namespaced IDs: "provider/model-name".

Pricing reflects OpenRouter's rates which may differ slightly from
direct provider pricing due to routing overhead.

Source: https://openrouter.ai/models
"""

from __future__ import annotations

from .base import ModelInfo

MODELS: list[ModelInfo] = [
    # ── Anthropic via OpenRouter ─────────────────────────────────────────────
    ModelInfo(
        id="anthropic/claude-opus-4-6",
        context_window=1_000_000,
        max_output=128_000,
        input_price=5.0,
        output_price=25.0,
        description="Claude Opus 4.6 via OpenRouter",
    ),
    ModelInfo(
        id="anthropic/claude-sonnet-4-6",
        context_window=1_000_000,
        max_output=64_000,
        input_price=3.0,
        output_price=15.0,
        description="Claude Sonnet 4.6 via OpenRouter",
    ),
    ModelInfo(
        id="anthropic/claude-haiku-4-5-20251001",
        context_window=200_000,
        max_output=64_000,
        input_price=1.0,
        output_price=5.0,
        description="Claude Haiku 4.5 via OpenRouter",
    ),
    # ── OpenAI via OpenRouter ────────────────────────────────────────────────
    ModelInfo(
        id="openai/gpt-4o",
        context_window=128_000,
        max_output=16_384,
        input_price=2.50,
        output_price=10.0,
        description="GPT-4o via OpenRouter",
    ),
    ModelInfo(
        id="openai/gpt-4o-mini",
        context_window=128_000,
        max_output=16_384,
        input_price=0.15,
        output_price=0.60,
        description="GPT-4o mini via OpenRouter",
    ),
    ModelInfo(
        id="openai/o3-mini",
        context_window=200_000,
        max_output=100_000,
        input_price=1.10,
        output_price=4.40,
        description="o3-mini reasoning via OpenRouter",
    ),
    ModelInfo(
        id="openai/o4-mini",
        context_window=200_000,
        max_output=100_000,
        input_price=1.10,
        output_price=4.40,
        description="o4-mini reasoning via OpenRouter",
    ),
    # ── Google via OpenRouter ────────────────────────────────────────────────
    ModelInfo(
        id="google/gemini-2.0-flash-001",
        context_window=1_000_000,
        max_output=8_192,
        input_price=0.10,
        output_price=0.40,
        description="Gemini 2.0 Flash — fast and cheap",
    ),
    ModelInfo(
        id="google/gemini-2.5-pro-preview",
        context_window=1_000_000,
        max_output=65_536,
        input_price=1.25,
        output_price=10.0,
        description="Gemini 2.5 Pro — strong reasoning",
    ),
    # ── Meta via OpenRouter ──────────────────────────────────────────────────
    ModelInfo(
        id="meta-llama/llama-3.3-70b-instruct",
        context_window=128_000,
        max_output=8_192,
        input_price=0.39,
        output_price=0.39,
        description="Llama 3.3 70B Instruct",
    ),
    # ── DeepSeek via OpenRouter ──────────────────────────────────────────────
    ModelInfo(
        id="deepseek/deepseek-chat-v3-0324",
        context_window=128_000,
        max_output=8_192,
        input_price=0.27,
        output_price=1.10,
        description="DeepSeek V3 Chat",
    ),
    # ── Mistral via OpenRouter ───────────────────────────────────────────────
    ModelInfo(
        id="mistralai/mistral-large-2411",
        context_window=128_000,
        max_output=8_192,
        input_price=2.0,
        output_price=6.0,
        description="Mistral Large",
    ),
]
