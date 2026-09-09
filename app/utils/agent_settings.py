"""Central agent → model binding loader.

Reads ``app/config/agent-settings.json`` and returns per-agent
primary + fallback adapter configurations. API keys are never stored on
disk — they are resolved from the environment via
:mod:`app.config.settings` every time an adapter is constructed, so there
is nothing to "fill" or "clear" on startup/shutdown.

Schema (v2)::

    {
      "version": 2,
      "default_n_fallbacks_models": 3,
      "agents": {
        "master": {
          "adapter": "anthropic",
          "model": "claude-sonnet-5",
          "temperature": 0.3,
          "max_tokens": 8096,
          "task_timeout": 1800,    // optional, seconds; falls back to settings.task_timeout (300)
          "idle_timeout": 900,     // optional, seconds; falls back to settings.agent_idle_timeout (900)
          "fallbacks": [
            {"adapter": "anthropic", "model": "claude-haiku-4-5-20251001"},
            {"adapter": "openai",    "model": "gpt-4o-mini"},
            {"adapter": "google",    "model": "gemini-2.5-flash"}
          ]
        },
        ...
      }
    }

The ``heal`` CLI is kept as a convenience wrapper that regenerates a
missing/corrupt file from a built-in default. It used to clear secrets;
that is now a no-op because no secrets live in the file.

CLI entry points:

    python -m app.utils.agent_settings show                   # print (no secrets)
    python -m app.utils.agent_settings resolve <agent_name>   # show chain for one agent
    python -m app.utils.agent_settings heal                   # regenerate from default
    python -m app.utils.agent_settings fill-keys              # alias — no-op, prints status
    python -m app.utils.agent_settings clear-keys             # alias — no-op, prints status
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from app.config import settings
from app.utils.adapters import AgentConfig

log = logging.getLogger(__name__)

# Authoritative location.
SETTINGS_PATH = settings.project_root / "app" / "config" / "agent-settings.json"

# Legacy locations that older shell scripts might still point at. We
# silently clean these up on any load so a stray leftover doesn't confuse
# operators.
_LEGACY_PATHS: list[Path] = [
    settings.agents_dir / "doctor" / "agent-settings-base.json",
    settings.agents_dir / "doctor" / "agent-settings.json",
]


# ── Built-in default ─────────────────────────────────────────────────────
# Used by ``heal`` when the live file is missing or corrupt. Kept in sync
# with app/config/agent-settings.json.

_DEFAULT_SETTINGS: dict[str, Any] = {
    "version": 2,
    "description": (
        "Central agent -> model binding with cross-provider fallbacks. "
        "No API keys are stored on disk — keys are always resolved from the "
        "environment via app.config.settings at runtime."
    ),
    "default_n_fallbacks_models": 3,
    "agents": {
        "master": {
            "adapter": "anthropic",
            "model": "claude-sonnet-5",
            "temperature": 0.3,
            "max_tokens": 8096,
            "fallbacks": [
                {"adapter": "anthropic", "model": "claude-haiku-4-5-20251001"},
                {"adapter": "openai", "model": "gpt-4o-mini"},
                {"adapter": "google", "model": "gemini-2.5-flash"},
            ],
        },
        "planning": {
            "adapter": "anthropic",
            "model": "claude-sonnet-5",
            "temperature": 0.3,
            "max_tokens": 8096,
            "fallbacks": [
                {"adapter": "anthropic", "model": "claude-haiku-4-5-20251001"},
                {"adapter": "openai", "model": "gpt-4o-mini"},
                {"adapter": "google", "model": "gemini-2.5-flash"},
            ],
        },
        "builder": {
            "adapter": "anthropic",
            "model": "claude-sonnet-5",
            "temperature": 0.2,
            "max_tokens": 8096,
            "fallbacks": [
                {"adapter": "anthropic", "model": "claude-opus-5"},
                {"adapter": "openai", "model": "gpt-5.2"},
                {"adapter": "google", "model": "gemini-2.5-pro"},
            ],
        },
        "keeper": {
            "adapter": "anthropic",
            "model": "claude-haiku-4-5-20251001",
            "temperature": 0.2,
            "max_tokens": 4096,
            "fallbacks": [
                {"adapter": "anthropic", "model": "claude-sonnet-5"},
                {"adapter": "openai", "model": "gpt-4o-mini"},
                {"adapter": "google", "model": "gemini-2.5-flash-lite"},
            ],
        },
        "cron": {
            "adapter": "anthropic",
            "model": "claude-haiku-4-5-20251001",
            "temperature": 0.2,
            "max_tokens": 4096,
            "fallbacks": [
                {"adapter": "anthropic", "model": "claude-sonnet-5"},
                {"adapter": "openai", "model": "gpt-4o-mini"},
                {"adapter": "google", "model": "gemini-2.5-flash-lite"},
            ],
        },
        "doctor": {
            "adapter": "anthropic",
            "model": "claude-haiku-4-5-20251001",
            "temperature": 0.2,
            "max_tokens": 4096,
            "fallbacks": [
                {"adapter": "openai", "model": "gpt-4o-mini"},
                {"adapter": "google", "model": "gemini-2.5-flash"},
                {"adapter": "anthropic", "model": "claude-sonnet-5"},
            ],
        },
        "model_manager": {
            "adapter": "anthropic",
            "model": "claude-haiku-4-5-20251001",
            "temperature": 0.2,
            "max_tokens": 4096,
            "fallbacks": [
                {"adapter": "openai", "model": "gpt-4o-mini"},
                {"adapter": "google", "model": "gemini-2.5-flash-lite"},
                {"adapter": "anthropic", "model": "claude-sonnet-5"},
            ],
        },
    },
}


# ── IO ────────────────────────────────────────────────────────────────────

def _cleanup_legacy() -> None:
    for p in _LEGACY_PATHS:
        if p.exists():
            try:
                p.unlink()
                log.info("agent_settings: removed legacy file %s", p)
            except OSError:
                pass


def _read() -> dict[str, Any]:
    """Load settings, falling back to the built-in default if missing/corrupt."""
    _cleanup_legacy()
    if not SETTINGS_PATH.exists():
        log.warning("agent_settings: %s missing — using built-in default", SETTINGS_PATH)
        return json.loads(json.dumps(_DEFAULT_SETTINGS))  # deep copy
    try:
        with SETTINGS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("agent_settings: unreadable %s (%s) — using built-in default", SETTINGS_PATH, exc)
        return json.loads(json.dumps(_DEFAULT_SETTINGS))
    if "agents" not in data:
        log.warning("agent_settings: %s has no 'agents' key — using built-in default", SETTINGS_PATH)
        return json.loads(json.dumps(_DEFAULT_SETTINGS))
    return data


def _write(data: dict[str, Any]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(SETTINGS_PATH.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        # ensure_ascii=False keeps the file's prose readable (and byte-stable
        # across writes) instead of re-escaping every em-dash on each swap.
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(SETTINGS_PATH)


# ── Resolution helpers ────────────────────────────────────────────────────

def _agents_map(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the ``agents`` dict, tolerating old list-shaped files."""
    agents = data.get("agents")
    if isinstance(agents, dict):
        return agents
    if isinstance(agents, list):
        # Legacy v1 shape: [{"agent": "master", "model": {...}, "fallbacks": [...]}]
        out: dict[str, dict[str, Any]] = {}
        for entry in agents:
            name = entry.get("agent")
            if not name:
                continue
            model = entry.get("model", {}) or {}
            fallbacks_v1 = entry.get("fallbacks", []) or []
            out[name] = {
                "adapter": model.get("adapter", ""),
                "model": model.get("name", ""),
                "temperature": entry.get("temperature", 0.3),
                "max_tokens": entry.get("max_tokens", 8096),
                "fallbacks": [
                    {
                        "adapter": fb.get("model", {}).get("adapter", ""),
                        "model": fb.get("model", {}).get("name", ""),
                    }
                    for fb in fallbacks_v1
                ],
            }
        return out
    return {}


def agent_tools(agent_name: str) -> list[str]:
    """Return the explicit ``tools`` list for an agent from agent-settings.json.

    This is only a *fallback* — the authoritative tool source is the agent's
    ``CONFIG.yaml`` ``tools:`` block (see ``BaseAgent._load_tool_names``). Used
    when an agent has no CONFIG.yaml tools block. Returns ``[]`` if absent.
    """
    entry = _agents_map(_read()).get(agent_name, {})
    tools = entry.get("tools", [])
    return list(tools) if isinstance(tools, list) else []


def resolve_agent_mcp_servers(agent_name: str) -> list[str]:
    """Return the agent's declared MCP servers from agent-settings.json.

    Reads the ``mcp_servers`` list field (e.g. ``["playwright", "context7"]``)
    on the agent's entry, mirroring :func:`agent_tools`. Returns ``[]`` when
    the entry is absent or the value is not a list, so the caller can safely
    skip MCP setup for agents that declare none.
    """
    entry = _agents_map(_read()).get(agent_name, {})
    servers = entry.get("mcp_servers", [])
    return list(servers) if isinstance(servers, list) else []


def resolve_agent(agent_name: str) -> dict[str, Any] | None:
    """Return ``{adapter, model, temperature, max_tokens, fallbacks}`` for one agent.

    ``fallbacks`` is trimmed to ``default_n_fallbacks_models`` (env-overridable
    via ``DEFAULT_N_FALLBACKS_MODELS``). Returns ``None`` if the agent has no
    entry — the caller should fall back to CONFIG.yaml.
    """
    data = _read()
    agents = _agents_map(data)
    entry = agents.get(agent_name)
    if not entry:
        return None

    n = settings.default_n_fallbacks_models
    if n is None or n < 0:
        n = int(data.get("default_n_fallbacks_models", 3))

    fallbacks = list(entry.get("fallbacks") or [])[: max(0, n)]

    return {
        "adapter": entry.get("adapter", settings.default_adapter),
        "model": entry.get("model", settings.default_model),
        "temperature": float(entry.get("temperature", settings.default_temperature)),
        "max_tokens": int(entry.get("max_tokens", 8096)),
        "fallbacks": fallbacks,
    }


def resolve_runner_settings(agent_name: str) -> dict[str, int]:
    """Return explicit runner overrides from ``agent-settings.json``.

    Only keys actually present in the per-agent entry are returned. This lets
    callers fall back field-by-field to the agent's ``CONFIG.yaml`` runner
    block, then global settings. In particular, an absent ``max_turns`` must
    not be converted to ``settings.max_turns`` here, or it would mask a
    ``CONFIG.yaml`` value. Explicit JSON values remain authoritative.
    """
    entry = _agents_map(_read()).get(agent_name) or {}

    def _coerce_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    resolved: dict[str, int] = {}
    for key in ("max_turns", "task_timeout", "idle_timeout"):
        if key not in entry:
            continue
        value = _coerce_int(entry[key])
        if value is not None:
            resolved[key] = value
    return resolved


def build_adapter_chain(agent_name: str) -> list[AgentConfig] | None:
    """Return primary + fallback ``AgentConfig``s for an agent.

    The list is ordered: index 0 is the primary, remaining entries are
    fallbacks in priority order. Temperature/max_tokens are inherited from
    the primary entry across all fallbacks (fallbacks intentionally don't
    override them — if you need per-model tuning, set it in the primary).
    """
    entry = resolve_agent(agent_name)
    if not entry:
        return None

    chain: list[AgentConfig] = [
        AgentConfig(
            adapter=entry["adapter"],
            model=entry["model"],
            temperature=entry["temperature"],
            max_tokens=entry["max_tokens"],
        )
    ]
    for fb in entry["fallbacks"]:
        adapter = fb.get("adapter", "")
        model = fb.get("model", "")
        if not adapter or not model:
            continue
        chain.append(
            AgentConfig(
                adapter=adapter,
                model=model,
                temperature=entry["temperature"],
                max_tokens=entry["max_tokens"],
            )
        )
    return chain



# ── Live config generation ────────────────────────────────────────────────
#
# Agents run in separate processes (see app/agents/base/runner_entry.py), so a
# hot swap has to be observable across process boundaries without any IPC. The
# settings file's mtime is exactly that: bumped by every :func:`_write`, cheap
# to stat every turn, and identical for every reader on the box.

def config_generation() -> int:
    """Return a monotonic-ish token that changes whenever the file is written.

    Used by long-running agents to notice a model swap mid-task without
    re-reading (and re-parsing) the JSON on every turn. Returns ``0`` when the
    file is absent, so a later ``heal()`` still registers as a change.
    """
    try:
        return SETTINGS_PATH.stat().st_mtime_ns
    except OSError:
        return 0


# ── Hot swap ──────────────────────────────────────────────────────────────

def validate_binding(adapter: str, model: str) -> None:
    """Raise ``ValueError`` unless ``adapter``/``model`` is a known pairing.

    Imported lazily: :mod:`app.utils.adapters.models` pulls in every provider
    catalogue, which is far more than a plain ``resolve_agent`` caller needs.
    """
    from app.utils.adapters import ADAPTER_REGISTRY
    from app.utils.adapters.models import PROVIDER_MODELS

    if adapter not in ADAPTER_REGISTRY:
        raise ValueError(
            f"Unknown adapter '{adapter}'. Available: {sorted(ADAPTER_REGISTRY)}"
        )
    known = PROVIDER_MODELS.get(adapter, [])
    # An empty catalogue means the provider enumerates models at runtime
    # (ollama/lmstudio pull from a local daemon) — don't block those.
    if known and model not in known:
        raise ValueError(
            f"Model '{model}' is not offered by adapter '{adapter}'. Available: {known}"
        )


def swap_agent_model(
    agent_name: str,
    adapter: str,
    model: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Rebind one agent to ``adapter``/``model`` and persist it.

    Takes effect without a restart: every reader goes through :func:`_read`,
    which has no cache, and running agents re-resolve their adapter each turn
    off :func:`config_generation`. Returns the agent's resolved entry.

    Creates the entry (with no fallbacks) when the agent isn't listed yet, so
    dynamically created agents can be rebound the same way as the built-ins.
    """
    validate_binding(adapter, model)

    data = _read()
    agents = _agents_map(data)
    entry = agents.get(agent_name)
    if entry is None:
        entry = {
            "adapter": adapter,
            "model": model,
            "temperature": settings.default_temperature,
            "max_tokens": 8096,
            "fallbacks": [],
        }
        agents[agent_name] = entry
    entry["adapter"] = adapter
    entry["model"] = model
    if temperature is not None:
        entry["temperature"] = float(temperature)
    if max_tokens is not None:
        entry["max_tokens"] = int(max_tokens)

    # ``_agents_map`` may have normalised a legacy list-shaped file into a new
    # dict — write the normalised map back, not the original value.
    data["agents"] = agents
    _write(data)
    log.info("agent_settings: hot-swapped %s -> %s/%s", agent_name, adapter, model)
    return resolve_agent(agent_name) or dict(entry)


def swap_provider(
    adapter: str,
    model: str,
    agent_names: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Rebind several agents to the same ``adapter``/``model`` in one write.

    ``agent_names`` defaults to every agent currently listed in the file. The
    whole batch is validated before anything is written, so a bad model id
    leaves the file untouched rather than half-swapped. Returns the resolved
    entry per agent, keyed by name.
    """
    validate_binding(adapter, model)

    data = _read()
    agents = _agents_map(data)
    targets = list(agent_names) if agent_names is not None else list(agents)
    if not targets:
        return {}

    for name in targets:
        entry = agents.get(name)
        if entry is None:
            entry = {
                "adapter": adapter,
                "model": model,
                "temperature": settings.default_temperature,
                "max_tokens": 8096,
                "fallbacks": [],
            }
            agents[name] = entry
        entry["adapter"] = adapter
        entry["model"] = model

    data["agents"] = agents
    _write(data)
    log.info(
        "agent_settings: hot-swapped %d agent(s) -> %s/%s", len(targets), adapter, model
    )
    return {name: (resolve_agent(name) or {}) for name in targets}

# ── Public commands ───────────────────────────────────────────────────────

def show() -> dict[str, Any]:
    """Return the full settings dict. No secrets to redact — none are stored."""
    return _read()


def heal() -> Path:
    """Regenerate the settings file from the built-in default."""
    _write(_DEFAULT_SETTINGS)
    return SETTINGS_PATH


# Legacy lifecycle shims — kept so old shell scripts keep working.

def fill_keys() -> Path:
    """No-op shim — keys are never written to disk in v2."""
    _cleanup_legacy()
    # Still ensure the file exists so callers can assert on it.
    if not SETTINGS_PATH.exists():
        heal()
    return SETTINGS_PATH


def clear_keys() -> Path | None:
    """No-op shim — keys are never written to disk in v2."""
    _cleanup_legacy()
    return SETTINGS_PATH if SETTINGS_PATH.exists() else None


# ── CLI dispatch ──────────────────────────────────────────────────────────

def _main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m app.utils.agent_settings {show|resolve <agent>|heal|fill-keys|clear-keys}")
        return 2
    cmd = argv[0]
    try:
        if cmd == "show":
            print(json.dumps(show(), indent=2))
        elif cmd == "resolve":
            if len(argv) < 2:
                print("usage: python -m app.utils.agent_settings resolve <agent_name>")
                return 2
            entry = resolve_agent(argv[1])
            if entry is None:
                print(f"[agent-settings] no entry for '{argv[1]}' — will fall back to CONFIG.yaml")
                return 1
            print(json.dumps(entry, indent=2))
        elif cmd == "heal":
            path = heal()
            print(f"[agent-settings] healed -> {path}")
        elif cmd == "fill-keys":
            path = fill_keys()
            print(f"[agent-settings] v2 stores no keys on disk — nothing to fill. file: {path}")
        elif cmd == "clear-keys":
            clear_keys()
            print("[agent-settings] v2 stores no keys on disk — nothing to clear.")
        else:
            print(f"unknown command: {cmd}")
            return 2
    except Exception as exc:
        print(f"[agent-settings] ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
