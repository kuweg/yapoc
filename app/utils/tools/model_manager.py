"""Model Manager tools — availability checks, catalog queries, cross-agent config updates."""

from datetime import datetime
from typing import Any

import httpx

from app.config import settings
from app.utils.adapters import ADAPTER_REGISTRY
from app.utils.adapters.models import (
    MODEL_REGISTRY,
    PROVIDER_MODELS,
    find_by_capability,
    recommend_for_task,
    context_summary,
)
from app.utils.tools.config_update import _set_yaml_key

from . import BaseTool, RiskTier


# ── CheckModelAvailabilityTool ──────────────────────────────────────────────


class CheckModelAvailabilityTool(BaseTool):
    name = "check_model_availability"
    description = (
        "Probe whether a specific model is available on a given provider. "
        "Returns AVAILABLE (with context window and pricing) or UNAVAILABLE/UNREACHABLE/TIMEOUT."
    )
    risk_tier = RiskTier.AUTO
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "model_id": {
                "type": "string",
                "description": "Model identifier (e.g. 'claude-sonnet-4-6', 'gpt-4o')",
            },
            "adapter": {
                "type": "string",
                "description": f"Provider adapter. One of: {', '.join(ADAPTER_REGISTRY.keys())}",
            },
        },
        "required": ["model_id", "adapter"],
    }

    async def execute(self, **params: Any) -> str:
        model_id: str = params["model_id"]
        adapter: str = params["adapter"]

        if adapter not in ADAPTER_REGISTRY:
            return f"Error: Unknown adapter '{adapter}'. Available: {', '.join(ADAPTER_REGISTRY.keys())}"

        try:
            if adapter == "anthropic":
                return await self._check_anthropic(model_id)
            elif adapter == "openai":
                return await self._check_openai(model_id)
            elif adapter == "ollama":
                return await self._check_ollama(model_id)
            elif adapter == "openrouter":
                return await self._check_openrouter(model_id)
            else:
                return f"Error: No availability check implemented for adapter '{adapter}'"
        except httpx.TimeoutException:
            return f"Model '{model_id}' ({adapter}): TIMEOUT"
        except httpx.ConnectError:
            return f"Model '{model_id}' ({adapter}): UNREACHABLE"
        except Exception as exc:
            return f"Model '{model_id}' ({adapter}): UNREACHABLE — {exc}"

    async def _check_anthropic(self, model_id: str) -> str:
        """POST /v1/messages with max_tokens=1 to test availability."""
        api_key = settings.anthropic_api_key
        if not api_key:
            return f"Model '{model_id}' (anthropic): UNREACHABLE — no API key configured"

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model_id,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        return self._format_result(model_id, "anthropic", resp.status_code)

    async def _check_openai(self, model_id: str) -> str:
        """GET /v1/models/{model_id} to test availability."""
        api_key = settings.openai_api_key
        if not api_key:
            return f"Model '{model_id}' (openai): UNREACHABLE — no API key configured"

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://api.openai.com/v1/models/{model_id}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        return self._format_result(model_id, "openai", resp.status_code)

    async def _check_ollama(self, model_id: str) -> str:
        """GET /api/tags and check if model is in the list."""
        base_url = settings.ollama_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url}/api/tags")

        if resp.status_code != 200:
            return f"Model '{model_id}' (ollama): UNREACHABLE — HTTP {resp.status_code}"

        data = resp.json()
        models = [m.get("name", "") for m in data.get("models", [])]
        # Ollama model names may include :tag suffix
        found = any(model_id == m or model_id == m.split(":")[0] for m in models)
        if found:
            return self._format_result(model_id, "ollama", 200)
        return f"Model '{model_id}' (ollama): UNAVAILABLE — not found in local models"

    async def _check_openrouter(self, model_id: str) -> str:
        """GET /api/v1/models and check if model_id is in the list."""
        api_key = settings.openrouter_api_key
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://openrouter.ai/api/v1/models",
                headers=headers,
            )

        if resp.status_code != 200:
            return f"Model '{model_id}' (openrouter): UNREACHABLE — HTTP {resp.status_code}"

        data = resp.json()
        model_ids = [m.get("id", "") for m in data.get("data", [])]
        if model_id in model_ids:
            return self._format_result(model_id, "openrouter", 200)
        return f"Model '{model_id}' (openrouter): UNAVAILABLE — not in model list"

    @staticmethod
    def _format_result(model_id: str, adapter: str, status_code: int) -> str:
        if status_code == 200:
            info = MODEL_REGISTRY.get(model_id)
            if info:
                return (
                    f"Model '{model_id}' ({adapter}): AVAILABLE — "
                    f"context={info.context_window:,}, "
                    f"${info.input_price}/MTok in, ${info.output_price}/MTok out"
                )
            return f"Model '{model_id}' ({adapter}): AVAILABLE — not in catalog (no pricing info)"
        return f"Model '{model_id}' ({adapter}): UNAVAILABLE — HTTP {status_code}"


# ── ListModelsTool ──────────────────────────────────────────────────────────


class ListModelsTool(BaseTool):
    name = "list_models"
    description = (
        "Query the model catalog. Filter by provider, capability tier, task keyword, "
        "or max price. Returns a formatted table. Pure catalog query — no network calls."
    )
    risk_tier = RiskTier.AUTO
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "provider": {
                "type": "string",
                "description": f"Filter by provider. One of: {', '.join(PROVIDER_MODELS.keys())}",
            },
            "capability_tier": {
                "type": "string",
                "description": "Filter by capability tier: frontier, advanced, efficient, lightweight",
            },
            "task_keyword": {
                "type": "string",
                "description": "Filter by recommended task keyword (e.g. 'coding', 'analysis')",
            },
            "max_input_price": {
                "type": "number",
                "description": "Max input price in $/MTok",
            },
            "sort_by": {
                "type": "string",
                "enum": ["cost", "quality", "id"],
                "description": "Sort order (default: cost)",
            },
        },
    }

    async def execute(self, **params: Any) -> str:
        provider = params.get("provider", "")
        capability_tier = params.get("capability_tier", "")
        task_keyword = params.get("task_keyword", "")
        max_input_price = params.get("max_input_price")
        sort_by = params.get("sort_by", "cost")

        # Start with full catalog
        models = list(MODEL_REGISTRY.values())

        # Apply filters
        if provider:
            provider_ids = set(PROVIDER_MODELS.get(provider, []))
            models = [m for m in models if m.id in provider_ids]

        if capability_tier:
            tier_models = set(m.id for m in find_by_capability(capability_tier))
            models = [m for m in models if m.id in tier_models]

        if task_keyword:
            task_models = set(m.id for m in recommend_for_task(task_keyword))
            models = [m for m in models if m.id in task_models]

        if max_input_price is not None:
            models = [m for m in models if m.input_price <= max_input_price]

        if not models:
            return "No models match the given filters."

        # Sort
        if sort_by == "quality":
            models.sort(key=lambda m: (m.quality_rank if m.quality_rank > 0 else 999, m.id))
        elif sort_by == "id":
            models.sort(key=lambda m: m.id)
        else:  # cost
            models.sort(key=lambda m: m.input_price + m.output_price)

        # Cap at 30
        capped = models[:30]

        # Format table
        lines = [
            f"{'Model ID':<40} {'Context':>9} {'$/MTok In':>10} {'$/MTok Out':>11} {'Tier':<12} {'Tools':>5}",
            "-" * 92,
        ]
        for m in capped:
            lines.append(
                f"{m.id:<40} {m.context_window:>9,} {m.input_price:>10.2f} {m.output_price:>11.2f} "
                f"{m.capability_tier or '-':<12} {'Y' if m.supports_tools else 'N':>5}"
            )

        if len(models) > 30:
            lines.append(f"\n... and {len(models) - 30} more models matching filters.")

        return "\n".join(lines)


# ── UpdateAgentConfigTool ───────────────────────────────────────────────────


class UpdateAgentConfigTool(BaseTool):
    name = "update_agent_config"
    description = (
        "Update another agent's CONFIG.md (adapter, model, temperature, max_tokens). "
        "Always requires human approval. Logs changes to the target agent's HEALTH.MD."
    )
    risk_tier = RiskTier.CONFIRM
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Target agent name (e.g. 'master', 'planning', 'builder')",
            },
            "adapter": {
                "type": "string",
                "description": f"LLM adapter. One of: {', '.join(ADAPTER_REGISTRY.keys())}",
            },
            "model": {
                "type": "string",
                "description": "Model identifier",
            },
            "temperature": {
                "type": "number",
                "description": "Temperature (0.0 to 1.0)",
                "minimum": 0.0,
                "maximum": 1.0,
            },
            "max_tokens": {
                "type": "integer",
                "description": "Maximum output tokens per turn",
            },
            "justification": {
                "type": "string",
                "description": "REQUIRED — why you're making this change (audit trail)",
            },
        },
        "required": ["agent_name", "justification"],
    }

    async def execute(self, **params: Any) -> str:
        import aiofiles

        agent_name: str = params["agent_name"]
        justification: str = params.get("justification", "")
        if not justification:
            return "Error: 'justification' parameter is required for audit trail."

        # Refuse base agent
        if agent_name == "base":
            return "Error: Cannot modify the 'base' agent — it's a framework module, not a real agent."

        agent_dir = settings.agents_dir / agent_name
        if not agent_dir.exists():
            return f"Error: Agent '{agent_name}' not found at {agent_dir}"

        config_path = agent_dir / "CONFIG.md"
        health_path = agent_dir / "HEALTH.MD"

        # Validate adapter
        adapter = params.get("adapter")
        if adapter and adapter not in ADAPTER_REGISTRY:
            return (
                f"Error: Unknown adapter '{adapter}'. "
                f"Available: {', '.join(ADAPTER_REGISTRY.keys())}"
            )

        # Validate temperature
        temperature = params.get("temperature")
        if temperature is not None:
            try:
                temperature = float(temperature)
                if not (0.0 <= temperature <= 1.0):
                    return "Error: temperature must be between 0.0 and 1.0"
            except (TypeError, ValueError):
                return "Error: temperature must be a number"

        # Validate max_tokens
        max_tokens = params.get("max_tokens")
        if max_tokens is not None:
            try:
                max_tokens = int(max_tokens)
                if max_tokens <= 0:
                    return "Error: max_tokens must be positive"
            except (TypeError, ValueError):
                return "Error: max_tokens must be an integer"

        model = params.get("model")

        # At least one config field must be set
        if not any([adapter, model, temperature is not None, max_tokens is not None]):
            return "Error: provide at least one of adapter, model, temperature, or max_tokens to update."

        # Read current CONFIG.md
        content = ""
        if config_path.exists():
            async with aiofiles.open(config_path, encoding="utf-8") as f:
                content = await f.read()

        # Apply changes
        changes: list[str] = []
        if adapter:
            content = _set_yaml_key(content, "adapter", adapter)
            changes.append(f"adapter={adapter}")
        if model:
            content = _set_yaml_key(content, "model", model)
            changes.append(f"model={model}")
        if temperature is not None:
            content = _set_yaml_key(content, "temperature", str(temperature))
            changes.append(f"temperature={temperature}")
        if max_tokens is not None:
            content = _set_yaml_key(content, "max_tokens", str(max_tokens))
            changes.append(f"max_tokens={max_tokens}")

        # Write updated CONFIG.md
        async with aiofiles.open(config_path, "w", encoding="utf-8") as f:
            await f.write(content)

        # Audit trail to target agent's HEALTH.MD
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        change_str = ", ".join(changes)
        audit = f"[{timestamp}] MODEL_MANAGER_UPDATE: {change_str} | reason: {justification} | by: model_manager\n"
        async with aiofiles.open(health_path, "a", encoding="utf-8") as f:
            await f.write(audit)

        return f"Updated {agent_name} CONFIG.md: {change_str}. Change takes effect on next turn."
