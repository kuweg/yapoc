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
          "model": "claude-sonnet-4-6",
          "temperature": 0.3,
          "max_tokens": 8096,
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
            "model": "claude-sonnet-4-6",
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
            "model": "claude-sonnet-4-6",
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
            "model": "claude-sonnet-4-6",
            "temperature": 0.2,
            "max_tokens": 8096,
            "fallbacks": [
                {"adapter": "anthropic", "model": "claude-opus-4-6"},
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
                {"adapter": "anthropic", "model": "claude-sonnet-4-6"},
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
                {"adapter": "anthropic", "model": "claude-sonnet-4-6"},
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
                {"adapter": "anthropic", "model": "claude-sonnet-4-6"},
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
                {"adapter": "anthropic", "model": "claude-sonnet-4-6"},
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
        json.dump(data, f, indent=2)
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


def resolve_agent(agent_name: str) -> dict[str, Any] | None:
    """Return ``{adapter, model, temperature, max_tokens, fallbacks}`` for one agent.

    ``fallbacks`` is trimmed to ``default_n_fallbacks_models`` (env-overridable
    via ``DEFAULT_N_FALLBACKS_MODELS``). Returns ``None`` if the agent has no
    entry — the caller should fall back to CONFIG.md.
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
                print(f"[agent-settings] no entry for '{argv[1]}' — will fall back to CONFIG.md")
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
