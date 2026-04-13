"""LM Studio local model catalog.

LM Studio runs an OpenAI-compatible server locally. Models are user-provided,
so this catalog contains *templates* for popular downloadable GGUF models.
Pricing is $0/$0 — local inference is free.

Context windows are approximate; actual limits depend on the loaded quant.
"""

from __future__ import annotations

from .base import ModelInfo

MODELS: list[ModelInfo] = [
    ModelInfo(
        id="lmstudio-community/Meta-Llama-3.1-8B-Instruct-GGUF",
        context_window=131_072,
        max_output=4_096,
        input_price=0.0,
        output_price=0.0,
        supports_tools=True,
        description="Llama 3.1 8B — local, free",
        capability_tier="efficient",
        latency_tier="fast",
    ),
    ModelInfo(
        id="lmstudio-community/Meta-Llama-3.1-70B-Instruct-GGUF",
        context_window=131_072,
        max_output=4_096,
        input_price=0.0,
        output_price=0.0,
        supports_tools=True,
        description="Llama 3.1 70B — local, free",
        capability_tier="advanced",
        latency_tier="slow",
    ),
    ModelInfo(
        id="lmstudio-community/Qwen2.5-7B-Instruct-GGUF",
        context_window=131_072,
        max_output=8_192,
        input_price=0.0,
        output_price=0.0,
        supports_tools=True,
        description="Qwen 2.5 7B — local, free",
        capability_tier="efficient",
        latency_tier="fast",
    ),
    ModelInfo(
        id="lmstudio-community/Qwen2.5-Coder-32B-Instruct-GGUF",
        context_window=131_072,
        max_output=8_192,
        input_price=0.0,
        output_price=0.0,
        supports_tools=True,
        description="Qwen 2.5 Coder 32B — local, free, code-focused",
        capability_tier="advanced",
        latency_tier="medium",
    ),
    ModelInfo(
        id="lmstudio-community/Mistral-Small-Instruct-2409-GGUF",
        context_window=131_072,
        max_output=8_192,
        input_price=0.0,
        output_price=0.0,
        supports_tools=True,
        description="Mistral Small 22B — local, free",
        capability_tier="efficient",
        latency_tier="fast",
    ),
    ModelInfo(
        id="lmstudio-community/gpt-oss-20b-GGUF",
        context_window=32_768,
        max_output=4_096,
        input_price=0.0,
        output_price=0.0,
        supports_tools=True,
        description="Generic local GGUF — set to whatever you loaded",
        capability_tier="efficient",
        latency_tier="fast",
    ),
]
