"""Centralized model catalog for all LLM providers.

Each provider file exports:
  MODELS  — list of ModelInfo with pricing, context windows, routing metadata

This module provides combined lookups used by adapters, CLI, renderer,
and agent routing logic.
"""

from __future__ import annotations

from . import anthropic as _anthropic
from . import google as _google
from . import lmstudio as _lmstudio
from . import ollama as _ollama
from . import openai as _openai
from . import openrouter as _openrouter
from .base import ModelInfo


# ── Combined lookups (all providers) ─────────────────────────────────────────

def _collect(*catalogs: list[ModelInfo]) -> list[ModelInfo]:
    out: list[ModelInfo] = []
    for catalog in catalogs:
        out.extend(catalog)
    return out


_ALL_MODELS: list[ModelInfo] = _collect(
    _anthropic.MODELS,
    _openai.MODELS,
    _ollama.MODELS,
    _openrouter.MODELS,
    _google.MODELS,
    _lmstudio.MODELS,
)

# id → ModelInfo (fast lookup)
MODEL_REGISTRY: dict[str, ModelInfo] = {m.id: m for m in _ALL_MODELS}

ALL_CONTEXT_WINDOWS: dict[str, int] = {m.id: m.context_window for m in _ALL_MODELS}
ALL_PRICING: dict[str, tuple[float, float]] = {m.id: (m.input_price, m.output_price) for m in _ALL_MODELS}

# Per-provider model ID lists (for CLI picker)
ANTHROPIC_MODEL_IDS = [m.id for m in _anthropic.MODELS]
OPENAI_MODEL_IDS = [m.id for m in _openai.MODELS]
OLLAMA_MODEL_IDS = [m.id for m in _ollama.MODELS]
OPENROUTER_MODEL_IDS = [m.id for m in _openrouter.MODELS]
GOOGLE_MODEL_IDS = [m.id for m in _google.MODELS]
LMSTUDIO_MODEL_IDS = [m.id for m in _lmstudio.MODELS]

PROVIDER_MODELS: dict[str, list[str]] = {
    "anthropic": ANTHROPIC_MODEL_IDS,
    "openai": OPENAI_MODEL_IDS,
    "ollama": OLLAMA_MODEL_IDS,
    "openrouter": OPENROUTER_MODEL_IDS,
    "google": GOOGLE_MODEL_IDS,
    "lmstudio": LMSTUDIO_MODEL_IDS,
}


# ── Routing helpers ──────────────────────────────────────────────────────────

def get_model(model_id: str) -> ModelInfo | None:
    """Look up a model by ID. Returns None if not in catalog."""
    return MODEL_REGISTRY.get(model_id)


def get_fallbacks(model_id: str) -> list[ModelInfo]:
    """Return fallback models for a given model, resolved to ModelInfo objects."""
    info = MODEL_REGISTRY.get(model_id)
    if not info or not info.fallback_models:
        return []
    return [MODEL_REGISTRY[fid] for fid in info.fallback_models if fid in MODEL_REGISTRY]


def find_by_capability(tier: str) -> list[ModelInfo]:
    """Return all models matching a capability tier (e.g. 'frontier', 'efficient')."""
    return [m for m in _ALL_MODELS if m.capability_tier == tier]


def find_by_latency(tier: str) -> list[ModelInfo]:
    """Return all models matching a latency tier (e.g. 'fast', 'very_fast')."""
    return [m for m in _ALL_MODELS if m.latency_tier == tier]


def find_cheapest(
    *,
    min_context: int = 0,
    supports_tools: bool = True,
    provider: str = "",
) -> ModelInfo | None:
    """Find the cheapest model meeting the given constraints.

    Sorts by (input_price + output_price). Filters by min context window,
    tool support, and optionally provider prefix.
    """
    candidates = [
        m for m in _ALL_MODELS
        if m.context_window >= min_context
        and (not supports_tools or m.supports_tools)
        and (not provider or m.id.startswith(provider + "/") or m.id in PROVIDER_MODELS.get(provider, []))
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda m: m.input_price + m.output_price)


def find_best_quality(
    *,
    max_input_price: float = float("inf"),
    supports_tools: bool = True,
    provider: str = "",
) -> ModelInfo | None:
    """Find the highest-quality ranked model within a budget.

    Only considers models with quality_rank > 0 (ranked).
    """
    candidates = [
        m for m in _ALL_MODELS
        if m.quality_rank > 0
        and m.input_price <= max_input_price
        and (not supports_tools or m.supports_tools)
        and (not provider or m.id.startswith(provider + "/") or m.id in PROVIDER_MODELS.get(provider, []))
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda m: m.quality_rank)


def recommend_for_task(task_keyword: str) -> list[ModelInfo]:
    """Return models whose recommended_tasks contain the keyword (case-insensitive)."""
    kw = task_keyword.lower()
    return [
        m for m in _ALL_MODELS
        if any(kw in t.lower() for t in m.recommended_tasks)
    ]


def context_summary(model_id: str) -> str:
    """Return a human-readable summary of a model's capabilities for agent context injection."""
    info = MODEL_REGISTRY.get(model_id)
    if not info:
        return f"Unknown model: {model_id}"
    parts = [
        f"Model: {info.id}",
        f"Context: {info.context_window:,} tokens, Max output: {info.max_output:,} tokens",
        f"Pricing: ${info.input_price}/MTok in, ${info.output_price}/MTok out",
    ]
    if info.capability_tier:
        parts.append(f"Capability: {info.capability_tier}, Latency: {info.latency_tier}")
    if info.recommended_tasks:
        parts.append(f"Best for: {', '.join(info.recommended_tasks)}")
    if info.fallback_models:
        parts.append(f"Fallbacks: {', '.join(info.fallback_models)}")
    if info.knowledge_cutoff:
        parts.append(f"Knowledge cutoff: {info.knowledge_cutoff}")
    if info.description:
        parts.append(info.description)
    return "\n".join(parts)


__all__ = [
    "ModelInfo",
    "MODEL_REGISTRY",
    "ALL_CONTEXT_WINDOWS",
    "ALL_PRICING",
    "ANTHROPIC_MODEL_IDS",
    "OPENAI_MODEL_IDS",
    "OLLAMA_MODEL_IDS",
    "OPENROUTER_MODEL_IDS",
    "GOOGLE_MODEL_IDS",
    "LMSTUDIO_MODEL_IDS",
    "PROVIDER_MODELS",
    # Routing helpers
    "get_model",
    "get_fallbacks",
    "find_by_capability",
    "find_by_latency",
    "find_cheapest",
    "find_best_quality",
    "recommend_for_task",
    "context_summary",
]
