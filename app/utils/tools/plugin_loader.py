"""Plugin loader — discover and register BaseTool subclasses from plugins/.

On startup, scans the `plugins/` directory for `.py` files, imports each module,
finds all BaseTool subclasses, and registers them in the TOOL_REGISTRY.

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
import sys
from pathlib import Path

from loguru import logger

from app.config import settings


# Names registered by the plugin loader on the most recent run. Re-runs may
# replace or remove these without treating them as core-tool conflicts.
_PLUGIN_OWNED_NAMES: set[str] = set()


def loaded_plugin_names() -> set[str]:
    """Names of tools currently registered via the plugin loader."""
    return set(_PLUGIN_OWNED_NAMES)


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
        return 0

    # Snapshot the previous plugin-owned set; we'll prune entries whose
    # source file is no longer present at the end of this run.
    previous_owned = set(_PLUGIN_OWNED_NAMES)
    seen_this_run: set[str] = set()
    loaded = 0

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

            # Find all BaseTool subclasses in the module
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
                        tool_name, py_file.name,
                    )
                    continue

                TOOL_REGISTRY[tool_name] = attr
                seen_this_run.add(tool_name)
                loaded += 1
                logger.info(
                    "Loaded plugin tool: {} from {}", tool_name, py_file.name
                )

        except Exception as exc:
            logger.error("Failed to load plugin {}: {}", py_file.name, exc)

    # Remove plugin-owned tools whose source file disappeared between runs.
    for stale in previous_owned - seen_this_run:
        TOOL_REGISTRY.pop(stale, None)
        logger.info("Unregistered plugin tool '{}' (source removed)", stale)

    _PLUGIN_OWNED_NAMES.clear()
    _PLUGIN_OWNED_NAMES.update(seen_this_run)

    if loaded:
        logger.info("Plugin loader: {} tool(s) registered from plugins/", loaded)
    return loaded
