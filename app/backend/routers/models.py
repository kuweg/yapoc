"""Models endpoint — lists available LLM models grouped by adapter with API key status."""

import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.utils.adapters import ADAPTER_REGISTRY
from app.utils.adapters.models import PROVIDER_MODELS, MODEL_REGISTRY
from app.utils import AGENTS_DIR

router = APIRouter(prefix="/models")


class ModelEntry(BaseModel):
    id: str
    description: str
    context_window: int
    supports_tools: bool


class AdapterInfo(BaseModel):
    name: str
    has_key: bool
    models: list[ModelEntry]


class ModelsResponse(BaseModel):
    adapters: list[AdapterInfo]


def _adapter_has_key(adapter_name: str) -> bool:
    """Check if the API key for a given adapter is configured."""
    key_map = {
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "codex": settings.openai_api_key,  # Codex uses OpenAI key
        "deepseek": settings.deepseek_api_key,
        "google": settings.google_api_key,
        "openrouter": settings.openrouter_api_key,
        "lmstudio": settings.lmstudio_api_key,
        "ollama": "local",  # Ollama runs locally, no key needed
    }
    val = key_map.get(adapter_name, "")
    return bool(val)


@router.get("", response_model=ModelsResponse)
async def list_models():
    adapters: list[AdapterInfo] = []
    for adapter_name in ADAPTER_REGISTRY:
        model_ids = PROVIDER_MODELS.get(adapter_name, [])
        models = []
        for mid in model_ids:
            info = MODEL_REGISTRY.get(mid)
            if info:
                models.append(ModelEntry(
                    id=info.id,
                    description=info.description,
                    context_window=info.context_window,
                    supports_tools=info.supports_tools,
                ))
        adapters.append(AdapterInfo(
            name=adapter_name,
            has_key=_adapter_has_key(adapter_name),
            models=models,
        ))
    return ModelsResponse(adapters=adapters)


class ConfigUpdateRequest(BaseModel):
    adapter: str
    model: str


_AGENT_SETTINGS_PATH = settings.project_root / "app" / "config" / "agent-settings.json"


@router.put("/agents/{name}/config")
async def update_agent_config(name: str, payload: ConfigUpdateRequest):
    """Update adapter and model in both agent-settings.json (authoritative) and CONFIG.yaml."""
    agent_dir = AGENTS_DIR / name
    if not agent_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    # Validate adapter exists
    if payload.adapter not in ADAPTER_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown adapter '{payload.adapter}'. Available: {list(ADAPTER_REGISTRY)}",
        )

    # Validate model belongs to adapter
    valid_models = PROVIDER_MODELS.get(payload.adapter, [])
    if payload.model not in valid_models:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{payload.model}' not in adapter '{payload.adapter}'. Available: {valid_models}",
        )

    # 1. Update agent-settings.json (authoritative source — loaded first by BaseAgent)
    if _AGENT_SETTINGS_PATH.exists():
        try:
            data = json.loads(_AGENT_SETTINGS_PATH.read_text(encoding="utf-8"))
            agents = data.get("agents", {})
            if name in agents:
                agents[name]["adapter"] = payload.adapter
                agents[name]["model"] = payload.model
            else:
                agents[name] = {
                    "adapter": payload.adapter,
                    "model": payload.model,
                    "temperature": 0.3,
                    "max_tokens": 8096,
                    "fallbacks": [],
                }
            data["agents"] = agents
            _AGENT_SETTINGS_PATH.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        except Exception:
            pass  # Fall through to CONFIG.yaml update

    # 2. Also update CONFIG.yaml (fallback source, keeps files in sync)
    config_path = agent_dir / "CONFIG.yaml"
    if config_path.exists():
        text = config_path.read_text(encoding="utf-8")
        text = re.sub(r"^adapter:\s*.*$", f"adapter: {payload.adapter}", text, count=1, flags=re.MULTILINE)
        text = re.sub(r"^model:\s*.*$", f"model: {payload.model}", text, count=1, flags=re.MULTILINE)
        config_path.write_text(text, encoding="utf-8")

    return {"status": "ok", "name": name, "adapter": payload.adapter, "model": payload.model}
