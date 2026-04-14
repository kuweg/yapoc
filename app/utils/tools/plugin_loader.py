"""Plugin loader — discover and register BaseTool subclasses from plugins/.

On startup, scans the `plugins/` directory for `.py` files, imports each module,
finds all BaseTool subclasses, and registers them in the TOOL_REGISTRY.

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


def load_plugins() -> int:
    """Scan plugins/ for .py files, import them, register BaseTool subclasses.

    Returns the number of tools registered.
    """
    from app.utils.tools import BaseTool, TOOL_REGISTRY

    plugins_dir = settings.project_root / "plugins"
    if not plugins_dir.exists():
        return 0

    loaded = 0
    for py_file in sorted(plugins_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue

        module_name = f"yapoc_plugin_{py_file.stem}"
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
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseTool)
                    and attr is not BaseTool
                    and hasattr(attr, "name")
                    and attr.name
                ):
                    if attr.name in TOOL_REGISTRY:
                        logger.warning(f"Plugin tool '{attr.name}' from {py_file.name} "
                                     f"conflicts with existing tool — skipped")
                        continue
                    TOOL_REGISTRY[attr.name] = attr
                    loaded += 1
                    logger.info(f"Loaded plugin tool: {attr.name} from {py_file.name}")

        except Exception as exc:
            logger.error(f"Failed to load plugin {py_file.name}: {exc}")

    if loaded:
        logger.info(f"Plugin loader: {loaded} tool(s) registered from plugins/")
    return loaded
