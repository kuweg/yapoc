"""MoonshotAI model catalog.

Source: https://platform.moonshot.ai/docs/pricing
"""

from __future__ import annotations

from .base import ModelInfo

MODELS: list[ModelInfo] = [
    ModelInfo(
        id="kimi-k2.6",
        context_window=256_000,
        max_output=8_192,
        input_price=0.95,
        output_price=4.00,
        supports_tools=True,
        supports_vision=True,
        supports_streaming=True,
        supports_json_mode=True,
        capability_tier="frontier",
        latency_tier="fast",
        knowledge_cutoff="2025-05",
        recommended_tasks=("coding", "agent pipelines", "long context", "general chat"),
        fallback_models=(),
        quality_rank=2,
        cost_efficiency_rank=3,
        description="Kimi K2.6 — MoonshotAI's flagship multimodal model with 256K context, tool calling, and agent swarm capabilities.",
    ),
]
