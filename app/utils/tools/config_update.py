"""UpdateConfigTool — allows agents to modify their own CONFIG.md.

Used for self-optimization: agents can switch adapters, models, or temperature
when they determine a different configuration would better serve their task.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles

from app.config import settings
from app.utils.adapters import ADAPTER_REGISTRY

from . import BaseTool, RiskTier


class UpdateConfigTool(BaseTool):
    name = "update_config"
    description = (
        "Update your CONFIG.md to switch adapter, model, or temperature. "
        "Change takes effect on the next turn. Requires human approval."
    )
    risk_tier = RiskTier.CONFIRM
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "adapter": {
                "type": "string",
                "description": f"LLM adapter to use. One of: {', '.join(ADAPTER_REGISTRY.keys())}",
            },
            "model": {
                "type": "string",
                "description": "Model identifier (e.g. 'claude-sonnet-4-6', 'gpt-4o', 'anthropic/claude-sonnet-4-6')",
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
        "required": ["justification"],
    }

    def __init__(self, agent_dir: Path) -> None:
        self._agent_dir = agent_dir
        self._config_path = agent_dir / "CONFIG.md"
        self._health_path = agent_dir / "HEALTH.MD"

    async def execute(self, **params: Any) -> str:
        justification = params.get("justification", "")
        if not justification:
            return "Error: 'justification' parameter is required for audit trail."

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
        if self._config_path.exists():
            async with aiofiles.open(self._config_path, encoding="utf-8") as f:
                content = await f.read()

        # Update specified keys
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
        async with aiofiles.open(self._config_path, "w", encoding="utf-8") as f:
            await f.write(content)

        # Audit log to HEALTH.MD
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        change_str = ", ".join(changes)
        audit = f"[{timestamp}] SELF_OPT: {change_str} | reason: {justification}\n"
        async with aiofiles.open(self._health_path, "a", encoding="utf-8") as f:
            await f.write(audit)

        return f"Config updated: {change_str}. Change takes effect next turn."


def _set_yaml_key(content: str, key: str, value: str) -> str:
    """Set a YAML key in CONFIG.md content. Adds the key if not present."""
    pattern = re.compile(rf"^({re.escape(key)}\s*:\s*)(.*)$", re.MULTILINE)
    if pattern.search(content):
        return pattern.sub(rf"\g<1>{value}", content)
    # Append the key
    if content and not content.endswith("\n"):
        content += "\n"
    content += f"{key}: {value}\n"
    return content
