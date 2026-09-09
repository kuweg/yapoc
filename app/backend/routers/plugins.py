"""Plugins router — manage YAPOC plugin metadata, config, and enable state.

GET  /api/plugins                 → list all installed plugins (config redacted)
POST /api/plugins/{name}/config   → save/validate a plugin's config
POST /api/plugins/{name}/enable   → enable a plugin
POST /api/plugins/{name}/disable  → disable a plugin
POST /api/plugins/reload          → re-scan plugins/ (non-admin alias)
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger

from app.config import settings

router = APIRouter(prefix="/plugins", tags=["plugins"])

_REDACTED = "********"


def _enabled_path(plugin_name: str) -> Path:
    """Path to the persisted enabled flag for a plugin."""
    return settings.project_root / "data" / "plugins" / plugin_name / "enabled.json"


def _read_enabled(plugin_name: str, default: bool = True) -> bool:
    """Read the persisted enabled flag, falling back to ``default``."""
    path = _enabled_path(plugin_name)
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("enabled"), bool):
                return data["enabled"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read enabled flag for plugin {}: {}", plugin_name, exc)
    return default


def _write_enabled(plugin_name: str, enabled: bool) -> None:
    """Persist the enabled flag for a plugin."""
    path = _enabled_path(plugin_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"enabled": enabled}, indent=2), encoding="utf-8")


def _agent_tools_block(agent_name: str) -> list[str]:
    """Return the tool names currently listed in an agent's CONFIG.yaml tools block.

    Parses the same way ``BaseAgent._load_tool_names`` does: find the ``tools:``
    key, then collect lines matching ``re.match(r"\\s+-\\s+(.+)", line)``,
    stripping inline ``#`` comments and whitespace. Returns ``[]`` when the file
    is missing or has no tools block.
    """
    path = settings.agents_dir / agent_name / "CONFIG.yaml"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if not raw.strip():
        return []

    names: list[str] = []
    in_tools = False
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped == "tools:" or stripped.startswith("tools:"):
            after = stripped[len("tools:"):].strip()
            if after:
                names.extend(t.strip() for t in after.split(",") if t.strip())
                break
            in_tools = True
            continue
        if in_tools:
            if not stripped or stripped.startswith("#"):
                continue
            match = re.match(r"\s+-\s+(.+)", line)
            if match:
                item = match.group(1).strip()
                if "#" in item:
                    item = item.split("#", 1)[0].strip()
                if item:
                    names.append(item)
            elif not line.startswith(" "):
                break

    return names


def _plugin_wildcard(plugin_name: str) -> str:
    """Return the wildcard tool grant for a plugin."""
    return f"plugin:{plugin_name}:*"


def _plugin_owned_tools(plugin_name: str) -> list[str]:
    """Return the tool names owned by a plugin (registered_tools, falling back to tools)."""
    from app.utils.tools.plugin_loader import list_plugins

    for plugin in list_plugins():
        if plugin.get("name") == plugin_name:
            registered = plugin.get("registered_tools") or []
            if registered:
                return registered
            return plugin.get("tools") or []
    return []


def _assigned_agents(plugin_name: str) -> list[str]:
    """Return the sorted list of agent names assigned to a plugin.

    An agent is "assigned" if its tools block contains the plugin wildcard
    (``plugin:<name>:*``) OR any tool name owned by the plugin.
    """
    wildcard = _plugin_wildcard(plugin_name)
    owned = set(_plugin_owned_tools(plugin_name))

    agents_dir = settings.agents_dir
    if not agents_dir.is_dir():
        return []

    assigned: list[str] = []
    for entry in sorted(agents_dir.iterdir()):
        if not entry.is_dir() or entry.name == "__pycache__":
            continue
        tools = _agent_tools_block(entry.name)
        if wildcard in tools or any(t in owned for t in tools):
            assigned.append(entry.name)
    return assigned


def _set_agent_assignment(agent_name: str, plugin_name: str, assigned: bool) -> None:
    """Add or remove a plugin's tools from an agent's CONFIG.yaml tools block.

    - ``assigned=True`` inserts the wildcard line ``  - plugin:<name>:*`` right
      after the ``tools:`` line (before the first existing ``- `` item). Does
      nothing if the wildcard is already present or there is no tools block.
    - ``assigned=False`` removes the wildcard line and any line whose tool name
      is one of the plugin's owned tool names. Leaves the ``tools:`` key intact.
    """
    path = settings.agents_dir / agent_name / "CONFIG.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return

    wildcard = _plugin_wildcard(plugin_name)
    owned = set(_plugin_owned_tools(plugin_name))

    # Pre-scan: is the wildcard already present anywhere in the tools block?
    wildcard_present = False
    in_tools = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "tools:" or stripped.startswith("tools:"):
            in_tools = True
            continue
        if in_tools:
            m = re.match(r"\s+-\s+(.+)", line)
            if m:
                if m.group(1).strip().split("#", 1)[0].strip() == wildcard:
                    wildcard_present = True
                    break
            elif line.startswith(" "):
                continue
            else:
                break

    lines = text.splitlines()
    out: list[str] = []
    in_tools = False
    inserted = False
    changed = False

    for line in lines:
        stripped = line.strip()
        if stripped == "tools:" or stripped.startswith("tools:"):
            in_tools = True
            out.append(line)
            continue
        if in_tools:
            match = re.match(r"\s+-\s+(.+)", line)
            if match:
                item = match.group(1).strip()
                name_part = item.split("#", 1)[0].strip()
                if name_part == wildcard:
                    if not assigned:
                        changed = True
                        continue  # drop the wildcard line
                elif assigned and not wildcard_present and not inserted:
                    # Insert wildcard before the first existing item.
                    out.append(f"  - {wildcard}")
                    inserted = True
                    changed = True
                if not assigned and name_part in owned:
                    changed = True
                    continue  # drop an owned tool line
                out.append(line)
                continue
            # A non-item line inside the tools block (blank/comment/other key).
            if not stripped or stripped.startswith("#"):
                out.append(line)
                continue
            # Reached the end of the tools block.
            in_tools = False
            out.append(line)
            continue
        out.append(line)

    if assigned and in_tools and not wildcard_present and not inserted:
        # tools block was empty of items; append the wildcard right after tools:.
        # Find the tools: line index and insert after it.
        idx = next((i for i, l in enumerate(out) if l.strip() == "tools:" or l.strip().startswith("tools:")), None)
        if idx is not None:
            out.insert(idx + 1, f"  - {wildcard}")
            changed = True

    if not changed:
        return

    new_text = "\n".join(out) + ("\n" if text.endswith("\n") else "")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, path)


def _redact_config(config: dict, config_schema: dict) -> dict:
    """Return a copy of ``config`` with secret-typed fields redacted.

    A field whose ``config_schema`` entry has ``type == "secret"`` and which
    holds a value in ``config`` is replaced with ``"********"``. All other
    fields are returned as-is.
    """
    redacted = dict(config)
    for field, spec in (config_schema or {}).items():
        if not isinstance(spec, dict):
            continue
        if spec.get("type") == "secret" and field in redacted:
            redacted[field] = _REDACTED
    return redacted


def _coerce_value(field: str, spec: dict, value: Any) -> Any:
    """Coerce an incoming config value to the type declared in ``spec``."""
    field_type = spec.get("type", "string")
    if field_type == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if field_type == "number":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            text = value.strip()
            try:
                return int(text)
            except ValueError:
                try:
                    return float(text)
                except ValueError:
                    return value
        return value
    if field_type == "list":
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return [value]
    # "string" and "secret" (and anything else) accept a string.
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _validate_and_normalize_config(
    plugin_name: str, config_schema: dict, incoming: dict
) -> dict:
    """Validate ``incoming`` against ``config_schema`` and apply defaults.

    Raises HTTPException(422) when a required field is missing and has no
    default. Returns the normalized config dict.
    """
    missing: list[str] = []
    normalized: dict = {}

    for field, spec in (config_schema or {}).items():
        if not isinstance(spec, dict):
            continue
        required = bool(spec.get("required"))
        has_default = "default" in spec

        if field in incoming:
            normalized[field] = _coerce_value(field, spec, incoming[field])
        elif has_default:
            normalized[field] = spec.get("default")
        elif required:
            missing.append(field)

    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required config field(s): {', '.join(sorted(missing))}",
        )

    return normalized


@router.get("")
async def list_plugins() -> dict:
    """List all installed plugins with redacted config and persisted enabled state."""
    from app.utils.tools.plugin_loader import list_plugins, load_plugin_config
    from app.utils.tools import TOOL_REGISTRY

    plugins = list_plugins()
    result: list[dict] = []
    for plugin in plugins:
        name = plugin.get("name", "")
        config_schema = plugin.get("config_schema") or {}
        config = load_plugin_config(name)
        # Persisted enabled flag wins over the manifest default.
        plugin["enabled"] = _read_enabled(name, bool(plugin.get("enabled", True)))
        plugin["config"] = _redact_config(config, config_schema)
        plugin["assigned_agents"] = _assigned_agents(name)
        plugin["tool_details"] = [
            {"name": t, "description": (getattr(TOOL_REGISTRY.get(t), "description", "") or "")}
            for t in (plugin.get("registered_tools") or plugin.get("tools") or [])
        ]
        result.append(plugin)

    return {"plugins": result}


@router.post("/{name}/config")
async def save_plugin_config(name: str, payload: dict) -> dict:
    """Save and validate config for a plugin."""
    from app.utils.tools.plugin_loader import (
        list_plugins,
        load_plugin_config,
        save_plugin_config,
    )

    plugin = next((p for p in list_plugins() if p.get("name") == name), None)
    if plugin is None:
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")

    config_schema = plugin.get("config_schema") or {}
    normalized = _validate_and_normalize_config(name, config_schema, payload or {})

    # Merge with existing config so fields not in the schema are preserved.
    existing = load_plugin_config(name)
    merged = dict(existing)
    merged.update(normalized)

    save_plugin_config(name, merged)
    return {
        "status": "ok",
        "name": name,
        "config": _redact_config(merged, config_schema),
    }


@router.post("/{name}/enable")
async def enable_plugin(name: str) -> dict:
    """Enable a plugin by persisting its enabled flag."""
    from app.utils.tools.plugin_loader import list_plugins

    if not any(p.get("name") == name for p in list_plugins()):
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")
    _write_enabled(name, True)
    return {"status": "ok", "name": name, "enabled": True}


@router.post("/{name}/disable")
async def disable_plugin(name: str) -> dict:
    """Disable a plugin by persisting its enabled flag."""
    from app.utils.tools.plugin_loader import list_plugins

    if not any(p.get("name") == name for p in list_plugins()):
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")
    _write_enabled(name, False)
    return {"status": "ok", "name": name, "enabled": False}


@router.get("/{name}/assignments")
async def get_plugin_assignments(name: str) -> dict:
    """Return the agents currently assigned to a plugin."""
    from app.utils.tools.plugin_loader import list_plugins

    if not any(p.get("name") == name for p in list_plugins()):
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")
    return {"name": name, "agents": _assigned_agents(name)}


@router.post("/{name}/assignments")
async def set_plugin_assignments(name: str, payload: dict) -> dict:
    """Set the agents assigned to a plugin.

    Body: ``{"agents": ["agent1", "agent2", ...]}``. Every agent directory under
    ``settings.agents_dir`` is assigned/unassigned accordingly.
    """
    from app.utils.tools.plugin_loader import list_plugins

    if not any(p.get("name") == name for p in list_plugins()):
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")

    raw_agents = (payload or {}).get("agents", [])
    if not isinstance(raw_agents, list):
        raise HTTPException(status_code=422, detail="'agents' must be a list of strings")
    selected = {a for a in raw_agents if isinstance(a, str)}

    agents_dir = settings.agents_dir
    if agents_dir.is_dir():
        for entry in agents_dir.iterdir():
            if not entry.is_dir() or entry.name == "__pycache__":
                continue
            _set_agent_assignment(entry.name, name, entry.name in selected)

    return {"status": "ok", "name": name, "agents": sorted(selected)}


@router.delete("/{name}")
async def delete_plugin(name: str) -> dict:
    """Delete a plugin: remove its source files, persisted state, and tools.

    - Directory-style: removes ``plugins/<name>/``.
    - Flat-style: removes ``plugins/<name>.py`` and/or ``plugins/<name>.yaml``.
    - Persisted state: removes ``data/plugins/<name>/``.
    - Unregisters the plugin's tools by re-running ``load_plugins()``.
    """
    from app.utils.tools.plugin_loader import list_plugins, load_plugins

    if not any(p.get("name") == name for p in list_plugins()):
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")

    plugins_dir = settings.project_root / "plugins"

    # Remove the plugin's source files.
    dir_style = plugins_dir / name
    if dir_style.is_dir():
        import shutil

        shutil.rmtree(dir_style)
    else:
        for suffix in (".py", ".yaml"):
            flat_file = plugins_dir / f"{name}{suffix}"
            if flat_file.exists():
                flat_file.unlink()

    # Remove persisted state.
    state_dir = settings.project_root / "data" / "plugins" / name
    if state_dir.exists():
        import shutil

        shutil.rmtree(state_dir)

    # Unregister the plugin's tools from the live registry.
    load_plugins()

    return {"status": "ok", "name": name}


@router.post("/reload")
async def reload_plugins() -> dict:
    """Re-scan plugins/ and register any BaseTool subclasses found (non-admin)."""
    from app.utils.tools.plugin_loader import load_plugins

    count = load_plugins()
    return {"status": "ok", "plugins_loaded": count}
