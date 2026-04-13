from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelInfo:
    id: str
    context_window: int       # total tokens
    max_output: int           # max output tokens
    input_price: float        # $/1M tokens
    output_price: float       # $/1M tokens
    supports_tools: bool = True
    supports_vision: bool = False
    description: str = ""
    # ── Extended schema (for routing & context management) ────────────────────
    capability_tier: str = ""           # "frontier" | "advanced" | "efficient" | "lightweight"
    latency_tier: str = ""              # "very_fast" | "fast" | "medium" | "slow"
    quality_rank: int = 0               # 1 = best quality, 0 = unranked
    cost_efficiency_rank: int = 0       # 1 = best value, 0 = unranked
    knowledge_cutoff: str = ""          # e.g. "2025-12"
    recommended_tasks: tuple[str, ...] = ()
    fallback_models: tuple[str, ...] = ()
    max_rpm: int = 0                    # requests/min (0 = unknown)
    max_tpm: int = 0                    # tokens/min (0 = unknown)
    supports_streaming: bool = True
    supports_json_mode: bool = False
