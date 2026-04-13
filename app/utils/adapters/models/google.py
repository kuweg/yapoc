"""Google Gemini model catalog.

Source: https://ai.google.dev/gemini-api/docs/models
         https://ai.google.dev/pricing
"""

from __future__ import annotations

from .base import ModelInfo

MODELS: list[ModelInfo] = [
    ModelInfo(
        id="gemini-2.5-pro",
        context_window=2_000_000,
        max_output=8_192,
        input_price=1.25,
        output_price=10.0,
        supports_tools=True,
        supports_vision=True,
        description="Gemini 2.5 Pro — frontier reasoning, 2M context",
        capability_tier="frontier",
        latency_tier="medium",
    ),
    ModelInfo(
        id="gemini-2.5-flash",
        context_window=1_000_000,
        max_output=8_192,
        input_price=0.30,
        output_price=2.50,
        supports_tools=True,
        supports_vision=True,
        description="Gemini 2.5 Flash — fast, cheap, 1M context",
        capability_tier="efficient",
        latency_tier="fast",
    ),
    ModelInfo(
        id="gemini-2.5-flash-lite",
        context_window=1_000_000,
        max_output=8_192,
        input_price=0.10,
        output_price=0.40,
        supports_tools=True,
        supports_vision=True,
        description="Gemini 2.5 Flash-Lite — cheapest Gemini tier",
        capability_tier="lightweight",
        latency_tier="very_fast",
    ),
    ModelInfo(
        id="gemini-2.0-flash",
        context_window=1_000_000,
        max_output=8_192,
        input_price=0.10,
        output_price=0.40,
        supports_tools=True,
        supports_vision=True,
        description="Gemini 2.0 Flash (previous gen)",
        capability_tier="efficient",
        latency_tier="very_fast",
    ),
    ModelInfo(
        id="gemini-1.5-pro",
        context_window=2_000_000,
        max_output=8_192,
        input_price=1.25,
        output_price=5.0,
        supports_tools=True,
        supports_vision=True,
        description="Gemini 1.5 Pro (legacy)",
        capability_tier="advanced",
        latency_tier="medium",
    ),
    ModelInfo(
        id="gemini-1.5-flash",
        context_window=1_000_000,
        max_output=8_192,
        input_price=0.075,
        output_price=0.30,
        supports_tools=True,
        supports_vision=True,
        description="Gemini 1.5 Flash (legacy)",
        capability_tier="efficient",
        latency_tier="very_fast",
    ),
]
