"""Models endpoint — lists available models, and hot-swaps agent→model bindings.

A swap here takes effect without restarting anything: it rewrites
``app/config/agent-settings.json`` (which every reader loads uncached), and
running agents re-resolve their adapter between turns. See
``app.utils.agent_settings.swap_agent_model``.
"""

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.utils import agent_settings as _agent_settings
from app.utils.adapters import ADAPTER_REGISTRY
from app.utils.adapters.models import PROVIDER_MODELS, MODEL_REGISTRY
from app.utils import AGENTS_DIR

router = APIRouter(prefix="/models")


class ModelEntry(BaseModel):
    id: str
    description: str
    context_window: int
    supports_tools: bool
    input_price: float
    output_price: float
    pricing_source: str
    pricing_verified_at: str
    pricing_notes: str
    cached_input_price: float | None = None
    off_peak_input_price: float | None = None
    off_peak_output_price: float | None = None
    off_peak_cached_input_price: float | None = None
    long_context_input_price: float | None = None
    long_context_output_price: float | None = None


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
        "moonshot": settings.moonshot_api_key,
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
                    input_price=info.input_price,
                    output_price=info.output_price,
                    pricing_source=info.pricing_source,
                    pricing_verified_at=info.pricing_verified_at,
                    pricing_notes=info.pricing_notes,
                    cached_input_price=info.cached_input_price,
                    off_peak_input_price=info.off_peak_input_price,
                    off_peak_output_price=info.off_peak_output_price,
                    off_peak_cached_input_price=info.off_peak_cached_input_price,
                    long_context_input_price=info.long_context_input_price,
                    long_context_output_price=info.long_context_output_price,
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


class HotSwapRequest(BaseModel):
    adapter: str
    model: str
    #: Agents to rebind. ``None`` means every agent listed in
    #: agent-settings.json — the "switch the whole fleet" case.
    agents: list[str] | None = None


def _sync_config_yaml(name: str, adapter: str, model: str) -> None:
    """Mirror the binding into the agent's CONFIG.yaml.

    CONFIG.yaml is only the fallback source (agent-settings.json wins), but
    leaving it stale makes the two files disagree about which model an agent
    runs — confusing for anyone reading the repo, and wrong for agents that
    have no JSON entry at all.
    """
    config_path = AGENTS_DIR / name / "CONFIG.yaml"
    if not config_path.exists():
        return
    text = config_path.read_text(encoding="utf-8")
    text = re.sub(r"^adapter:\s*.*$", f"adapter: {adapter}", text, count=1, flags=re.MULTILINE)
    text = re.sub(r"^model:\s*.*$", f"model: {model}", text, count=1, flags=re.MULTILINE)
    config_path.write_text(text, encoding="utf-8")


async def _broadcast_swap(changes: list[dict[str, str]]) -> None:
    """Tell every connected client which agents just changed model.

    Titles across the UI render the active adapter/model, so they would
    otherwise stay stale until the next 2s poll — and the chat header's master
    label, which is only fetched on mount, would stay stale indefinitely.
    """
    if not changes:
        return
    try:
        from app.backend.websocket import ws_manager
        await ws_manager.push_event("model_changed", {"changes": changes})
    except Exception:
        # A swap that persisted but failed to broadcast is still a successful
        # swap — the pollers will catch up.
        pass


@router.put("/agents/{name}/config")
async def update_agent_config(name: str, payload: ConfigUpdateRequest):
    """Hot-swap one agent onto a new adapter/model. No restart required."""
    if not (AGENTS_DIR / name).is_dir():
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    try:
        _agent_settings.swap_agent_model(name, payload.adapter, payload.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Could not write agent-settings.json: {exc}"
        ) from exc

    _sync_config_yaml(name, payload.adapter, payload.model)

    change = {"agent": name, "adapter": payload.adapter, "model": payload.model}
    await _broadcast_swap([change])
    # ``name`` is kept alongside ``agent`` so older clients reading the old
    # response shape don't break on the rename.
    return {"status": "ok", "name": name, **change}


@router.post("/hot-swap")
async def hot_swap(payload: HotSwapRequest):
    """Rebind many agents (default: all of them) to one provider in a single write.

    Validated as a batch before anything is written, so a bad model id leaves
    every agent on its current provider rather than swapping half the fleet.
    """
    unknown = [n for n in (payload.agents or []) if not (AGENTS_DIR / n).is_dir()]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unknown agent(s): {unknown}")

    try:
        swapped = _agent_settings.swap_provider(
            payload.adapter, payload.model, payload.agents
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Could not write agent-settings.json: {exc}"
        ) from exc

    changes = [
        {"agent": name, "adapter": payload.adapter, "model": payload.model}
        for name in swapped
    ]
    for change in changes:
        _sync_config_yaml(change["agent"], payload.adapter, payload.model)

    await _broadcast_swap(changes)
    return {"status": "ok", "swapped": changes}
