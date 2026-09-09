"""Plugin loader — discover and register BaseTool subclasses from plugins/.

On startup, scans the `plugins/` directory for `.py` files, imports each module,
finds all BaseTool subclasses, and registers them in the TOOL_REGISTRY.

Plugins may also carry a `plugin.yaml` manifest (directory-style:
`plugins/<name>/plugin.yaml`, or flat-style: `plugins/<name>.yaml`) describing
metadata such as display_name, description, version, author, category, a
`config_schema` map, and a `tools` list. Manifest metadata is exposed via
`load_plugin_manifests()` and `list_plugins()` for a management API.

Re-runnable: callers (notably the admin reload endpoint) can invoke
`load_plugins()` again at runtime. The loader:
  - Drops cached plugin modules from `sys.modules` before re-import so edits
    to plugin files take effect.
  - Tracks plugin-owned tool names so a second run doesn't false-flag its
    own previously-registered tools as conflicts.

Core tools registered directly in `app.utils.tools.__init__.TOOL_REGISTRY`
are never overwritten — a plugin that picks a colliding name is skipped
with a warning.

Usage:
    from app.utils.tools.plugin_loader import load_plugins
    loaded = load_plugins()
    print(f"Loaded {loaded} plugin tools")
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from app.config import settings


# Names registered by the plugin loader on the most recent run. Re-runs may
# replace or remove these without treating them as core-tool conflicts.
_PLUGIN_OWNED_NAMES: set[str] = set()

# tool_name -> plugin_name ownership, populated by load_plugins() so
# list_plugins() can report which tools belong to which plugin.
_PLUGIN_TOOL_OWNERSHIP: dict[str, str] = {}


def loaded_plugin_names() -> set[str]:
    """Names of tools currently registered via the plugin loader."""
    return set(_PLUGIN_OWNED_NAMES)


# ── Manifest parsing ────────────────────────────────────────────────────────

def _parse_manifest_yaml(text: str) -> dict[str, Any]:
    """Parse a plugin.yaml manifest into a dict.

    The project does not depend on PyYAML, so this is a small hand-rolled
    parser for the simple structure manifests use: top-level scalars, a
    `config_schema` map of field-name -> {type, required, default, label},
    and a `tools` list of strings. If PyYAML happens to be importable, it is
    preferred (more robust); otherwise the fallback parser is used.
    """
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass

    return _parse_simple_yaml(text)


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Minimal YAML subset parser for plugin manifests.

    Supports:
      - top-level `key: scalar` lines (scalars kept as strings, with a few
        bool/int/float coercions)
      - a `config_schema:` block whose nested entries are `field:` maps with
        `type`, `required`, `default`, `label` keys
      - a `tools:` block whose nested entries are `- name` list items
    """
    result: dict[str, Any] = {}
    lines = text.splitlines()

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # Top-level key (no leading whitespace).
        if not line[:1].isspace() and ":" in line:
            key, _, raw_val = line.partition(":")
            key = key.strip()
            raw_val = raw_val.strip()
            if key == "config_schema" and raw_val == "":
                schema: dict[str, Any] = {}
                i += 1
                while i < n and (lines[i].strip() == "" or lines[i].strip().startswith("#")):
                    i += 1
                while i < n and lines[i][:1].isspace() and ":" in lines[i]:
                    field_line = lines[i].strip()
                    field_key, _, _ = field_line.partition(":")
                    field_key = field_key.strip()
                    # Parse the field's nested map.
                    field_map: dict[str, Any] = {}
                    i += 1
                    while i < n and lines[i].strip() == "":
                        i += 1
                    while i < n and lines[i].strip().startswith("-") is False and \
                            (lines[i][:1].isspace() and ":" in lines[i]):
                        sub = lines[i].strip()
                        sk, _, sv = sub.partition(":")
                        field_map[sk.strip()] = _coerce_scalar(sv.strip())
                        i += 1
                    schema[field_key] = field_map
                result[key] = schema
                continue
            if key == "tools" and raw_val == "":
                tools: list[str] = []
                i += 1
                while i < n:
                    s = lines[i].strip()
                    if s.startswith("-"):
                        tools.append(s[1:].strip().strip("'\""))
                    elif s and not s.startswith("#"):
                        break
                    i += 1
                result[key] = tools
                continue
            result[key] = _coerce_scalar(raw_val)
        i += 1

    return result


def _coerce_scalar(raw: str) -> Any:
    """Coerce a raw scalar string to bool/int/float/None when unambiguous."""
    if raw == "":
        return ""
    if raw in ("true", "True", "TRUE"):
        return True
    if raw in ("false", "False", "FALSE"):
        return False
    if raw in ("null", "None", "~"):
        return None
    if raw.startswith("'") and raw.endswith("'") and len(raw) >= 2:
        return raw[1:-1]
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        return raw[1:-1]
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


_DEFAULT_MANIFEST_FIELDS: dict[str, Any] = {
    "display_name": "",
    "description": "",
    "version": "0.1.0",
    "author": "",
    "category": "general",
    "config_schema": {},
    "tools": [],
    "enabled": True,
}


def _normalize_manifest(name: str, raw: dict[str, Any], source: str, manifest_path: Path) -> dict[str, Any]:
    """Normalize a raw manifest dict into a canonical metadata dict."""
    out: dict[str, Any] = {
        "name": name,
        "display_name": raw.get("display_name") or name,
        "description": raw.get("description") or "",
        "version": raw.get("version") or "0.1.0",
        "author": raw.get("author") or "",
        "category": raw.get("category") or "general",
        "config_schema": raw.get("config_schema") if isinstance(raw.get("config_schema"), dict) else {},
        "tools": raw.get("tools") if isinstance(raw.get("tools"), list) else [],
        "enabled": raw.get("enabled", True),
        "manifest_path": str(manifest_path),
        "source": source,
    }
    if not isinstance(out["enabled"], bool):
        out["enabled"] = True
    return out


def load_plugin_manifests() -> dict[str, dict]:
    """Scan plugins/ for plugin.yaml manifests and return metadata keyed by name.

    Supports directory-style (`plugins/<name>/plugin.yaml`) and flat-style
    (`plugins/<name>.yaml`) manifests. Directory-style is the primary
    convention. Returns a dict of plugin name -> normalized metadata dict.
    """
    plugins_dir = settings.project_root / "plugins"
    manifests: dict[str, dict] = {}

    if not plugins_dir.exists():
        return manifests

    # Directory-style: plugins/<name>/plugin.yaml
    for manifest_path in sorted(plugins_dir.glob("*/plugin.yaml")):
        name = manifest_path.parent.name
        try:
            raw = _parse_manifest_yaml(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Failed to read plugin manifest {}: {}", manifest_path, exc)
            continue
        manifests[name] = _normalize_manifest(name, raw, "directory", manifest_path)

    # Flat-style: plugins/<name>.yaml (skip if a directory manifest already
    # claimed the same name).
    for manifest_path in sorted(plugins_dir.glob("*.yaml")):
        name = manifest_path.stem
        if name in manifests:
            continue
        try:
            raw = _parse_manifest_yaml(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Failed to read plugin manifest {}: {}", manifest_path, exc)
            continue
        manifests[name] = _normalize_manifest(name, raw, "flat", manifest_path)

    return manifests


# ── Plugin listing ──────────────────────────────────────────────────────────

def _registered_tools_for_plugin(plugin_name: str) -> list[str]:
    """Tool names currently in TOOL_REGISTRY owned by the given plugin."""
    return sorted(
        tool for tool, owner in _PLUGIN_TOOL_OWNERSHIP.items() if owner == plugin_name
    )


def list_plugins() -> list[dict]:
    """Return a list of plugin metadata dicts, merging manifests and bare .py plugins.

    Each entry includes manifest fields plus `registered_tools` (tool names in
    TOOL_REGISTRY owned by this plugin) and `enabled` state. Bare `plugins/*.py`
    files with no manifest get synthesized metadata inferred from the filename
    and the tools actually registered from that file.
    """
    plugins_dir = settings.project_root / "plugins"
    manifests = load_plugin_manifests()
    result: list[dict] = []

    seen_names: set[str] = set()

    # Directory-style plugins (with manifests).
    for name, meta in manifests.items():
        entry = dict(meta)
        entry["registered_tools"] = _registered_tools_for_plugin(name)
        result.append(entry)
        seen_names.add(name)

    if plugins_dir.exists():
        # Bare .py plugins without a manifest.
        for py_file in sorted(plugins_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            stem = py_file.stem
            if stem in seen_names:
                continue
            entry = {
                "name": stem,
                "display_name": stem,
                "description": "",
                "version": "0.1.0",
                "author": "",
                "category": "general",
                "config_schema": {},
                "tools": _registered_tools_for_plugin(stem),
                "enabled": True,
                "manifest_path": None,
                "source": "bare",
            }
            entry["registered_tools"] = _registered_tools_for_plugin(stem)
            result.append(entry)
            seen_names.add(stem)

        # Directory-style plugins without a manifest (plugins/<name>/*.py).
        for subdir in sorted(plugins_dir.iterdir()):
            if not subdir.is_dir() or subdir.name.startswith("_"):
                continue
            if subdir.name in seen_names:
                continue
            entry = {
                "name": subdir.name,
                "display_name": subdir.name,
                "description": "",
                "version": "0.1.0",
                "author": "",
                "category": "general",
                "config_schema": {},
                "tools": _registered_tools_for_plugin(subdir.name),
                "enabled": True,
                "manifest_path": None,
                "source": "directory",
            }
            entry["registered_tools"] = _registered_tools_for_plugin(subdir.name)
            result.append(entry)
            seen_names.add(subdir.name)

    return result


# ── Config persistence ──────────────────────────────────────────────────────

def load_plugin_config(plugin_name: str) -> dict:
    """Read persisted config for a plugin, or {} if none exists. Never raises."""
    config_path = settings.project_root / "data" / "plugins" / plugin_name / "config.json"
    try:
        if config_path.exists():
            data = json.loads(config_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Failed to load plugin config for {}: {}", plugin_name, exc)
    return {}


def save_plugin_config(plugin_name: str, config: dict) -> None:
    """Persist plugin config to data/plugins/<plugin_name>/config.json."""
    config_path = settings.project_root / "data" / "plugins" / plugin_name / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")


# ── Plugin loading ──────────────────────────────────────────────────────────

def load_plugins() -> int:
    """Scan plugins/ for .py files, import them, register BaseTool subclasses.

    Returns the number of plugin tools registered after this run. Safe to
    invoke repeatedly — see module docstring.
    """
    from app.utils.tools import BaseTool, TOOL_REGISTRY

    plugins_dir = settings.project_root / "plugins"
    if not plugins_dir.exists():
        # Clear any stale plugin entries from prior runs; the dir is gone.
        for name in list(_PLUGIN_OWNED_NAMES):
            TOOL_REGISTRY.pop(name, None)
        _PLUGIN_OWNED_NAMES.clear()
        _PLUGIN_TOOL_OWNERSHIP.clear()
        return 0

    # Snapshot the previous plugin-owned set; we'll prune entries whose
    # source file is no longer present at the end of this run.
    previous_owned = set(_PLUGIN_OWNED_NAMES)
    seen_this_run: set[str] = set()
    loaded = 0

    def _register_module(module: Any, plugin_name: str, source_file: str) -> None:
        nonlocal loaded
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if not (
                isinstance(attr, type)
                and issubclass(attr, BaseTool)
                and attr is not BaseTool
                and hasattr(attr, "name")
                and attr.name
            ):
                continue

            tool_name = attr.name
            # Conflict iff a non-plugin tool already owns this name.
            if tool_name in TOOL_REGISTRY and tool_name not in previous_owned:
                logger.warning(
                    "Plugin tool '{}' from {} conflicts with a core tool — skipped",
                    tool_name, source_file,
                )
                continue

            TOOL_REGISTRY[tool_name] = attr
            seen_this_run.add(tool_name)
            _PLUGIN_TOOL_OWNERSHIP[tool_name] = plugin_name
            loaded += 1
            logger.info(
                "Loaded plugin tool: {} from {}", tool_name, source_file
            )

            # Namespaced alias: plugin:<plugin_name>:<short_name>
            short = tool_name
            if tool_name.startswith(plugin_name + "_"):
                short = tool_name[len(plugin_name) + 1:]
            namespaced_key = f"plugin:{plugin_name}:{short}"
            if namespaced_key in TOOL_REGISTRY and namespaced_key not in previous_owned:
                logger.warning(
                    "Plugin tool '{}' from {} conflicts with a core tool — skipped",
                    namespaced_key, source_file,
                )
            else:
                TOOL_REGISTRY[namespaced_key] = attr
                seen_this_run.add(namespaced_key)
                _PLUGIN_TOOL_OWNERSHIP[namespaced_key] = plugin_name
                loaded += 1
                logger.info(
                    "Loaded plugin tool (namespaced): {} from {}",
                    namespaced_key, source_file,
                )

    # Bare plugins: plugins/*.py
    for py_file in sorted(plugins_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue

        module_name = f"yapoc_plugin_{py_file.stem}"
        # Drop any cached module so a file edit between calls actually loads.
        sys.modules.pop(module_name, None)

        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            _register_module(module, py_file.stem, py_file.name)
        except Exception as exc:
            logger.error("Failed to load plugin {}: {}", py_file.name, exc)

    # Directory plugins: plugins/<name>/*.py
    for subdir in sorted(plugins_dir.iterdir()):
        if not subdir.is_dir() or subdir.name.startswith("_"):
            continue
        for py_file in sorted(subdir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            module_name = f"yapoc_plugin_{subdir.name}_{py_file.stem}"
            sys.modules.pop(module_name, None)
            try:
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                _register_module(module, subdir.name, py_file.name)
            except Exception as exc:
                logger.error("Failed to load plugin {}: {}", py_file.name, exc)

    # Remove plugin-owned tools whose source file disappeared between runs.
    for stale in previous_owned - seen_this_run:
        TOOL_REGISTRY.pop(stale, None)
        _PLUGIN_TOOL_OWNERSHIP.pop(stale, None)
        logger.info("Unregistered plugin tool '{}' (source removed)", stale)

    _PLUGIN_OWNED_NAMES.clear()
    _PLUGIN_OWNED_NAMES.update(seen_this_run)

    if loaded:
        logger.info("Plugin loader: {} tool(s) registered from plugins/", loaded)
    return loaded
