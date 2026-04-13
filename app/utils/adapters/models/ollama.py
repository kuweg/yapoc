"""Ollama (local) model catalog.

Context windows and capabilities vary by quantization and hardware.
Pricing is $0 — these run locally. Listed for completeness in the
model picker and context window lookups.
"""

from __future__ import annotations

from .base import ModelInfo

MODELS: list[ModelInfo] = [
    ModelInfo(
        id="llama3.2",
        context_window=128_000,
        max_output=8_192,
        input_price=0.0,
        output_price=0.0,
        description="Meta Llama 3.2 (1B/3B)",
    ),
    ModelInfo(
        id="llama3.1",
        context_window=128_000,
        max_output=8_192,
        input_price=0.0,
        output_price=0.0,
        description="Meta Llama 3.1 (8B/70B/405B)",
    ),
    ModelInfo(
        id="llama3.3",
        context_window=128_000,
        max_output=8_192,
        input_price=0.0,
        output_price=0.0,
        description="Meta Llama 3.3 70B",
    ),
    ModelInfo(
        id="qwen2.5",
        context_window=128_000,
        max_output=8_192,
        input_price=0.0,
        output_price=0.0,
        supports_tools=True,
        description="Qwen 2.5 (7B/32B/72B), strong tool use",
    ),
    ModelInfo(
        id="qwen3",
        context_window=128_000,
        max_output=8_192,
        input_price=0.0,
        output_price=0.0,
        supports_tools=True,
        description="Qwen 3, hybrid thinking + tool use",
    ),
    ModelInfo(
        id="mistral",
        context_window=32_768,
        max_output=8_192,
        input_price=0.0,
        output_price=0.0,
        supports_tools=True,
        description="Mistral 7B",
    ),
    ModelInfo(
        id="mixtral",
        context_window=32_768,
        max_output=8_192,
        input_price=0.0,
        output_price=0.0,
        supports_tools=True,
        description="Mixtral 8x7B MoE",
    ),
    ModelInfo(
        id="codellama",
        context_window=16_384,
        max_output=4_096,
        input_price=0.0,
        output_price=0.0,
        supports_tools=False,
        supports_vision=False,
        description="Code Llama (code-focused)",
    ),
    ModelInfo(
        id="phi3",
        context_window=128_000,
        max_output=4_096,
        input_price=0.0,
        output_price=0.0,
        supports_tools=False,
        description="Microsoft Phi-3 (3.8B)",
    ),
    ModelInfo(
        id="deepseek-r1",
        context_window=128_000,
        max_output=8_192,
        input_price=0.0,
        output_price=0.0,
        supports_tools=True,
        description="DeepSeek R1 reasoning model",
    ),
    ModelInfo(
        id="command-r",
        context_window=128_000,
        max_output=4_096,
        input_price=0.0,
        output_price=0.0,
        supports_tools=True,
        description="Cohere Command R (RAG-optimized)",
    ),
]
