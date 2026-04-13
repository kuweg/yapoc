"""Agent settings heal/inspect tools — used by the Doctor agent.

In v2 of ``agent-settings.json`` the file contains no API keys, so
``heal_agent_settings`` simply regenerates it from the built-in default.
``show_agent_settings`` returns the live file directly — there are no
secrets to redact.
"""

import json
from typing import Any

from app.utils import agent_settings

from . import BaseTool, RiskTier


class HealAgentSettingsTool(BaseTool):
    name = "heal_agent_settings"
    description = (
        "Regenerate app/config/agent-settings.json from the built-in default. "
        "Use when the file is missing, corrupt, or drifted from the canonical "
        "primary + fallback chain. v2 stores no API keys, so this is always safe."
    )
    risk_tier = RiskTier.CONFIRM
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, **params: Any) -> str:
        try:
            path = agent_settings.heal()
            return f"OK: regenerated {path}"
        except Exception as exc:
            return f"ERROR: heal failed — {exc}"


class ShowAgentSettingsTool(BaseTool):
    name = "show_agent_settings"
    description = (
        "Return the current agent-settings.json with each agent's primary "
        "adapter/model and fallback chain. v2 stores no API keys so nothing "
        "needs redaction."
    )
    risk_tier = RiskTier.AUTO
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Optional: return only this agent's chain.",
            }
        },
        "required": [],
    }

    async def execute(self, **params: Any) -> str:
        try:
            name = params.get("agent_name")
            if name:
                entry = agent_settings.resolve_agent(name)
                if entry is None:
                    return f"[show_agent_settings] no entry for '{name}' (will fall back to CONFIG.md)"
                return json.dumps(entry, indent=2)
            return json.dumps(agent_settings.show(), indent=2)
        except Exception as exc:
            return f"ERROR: show failed — {exc}"
