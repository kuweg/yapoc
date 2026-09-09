"""ListTools tool — report the live tool registry to the calling agent."""

import json
from typing import Any

from app.utils.tools import BaseTool


class ListToolsTool(BaseTool):
    name = "list_tools"
    description = "Return the live list of available tools from the tool registry, optionally filtered to what the calling agent is actually granted."
    input_schema = {
        "type": "object",
        "properties": {
            "filter": {
                "type": "string",
                "description": "Optional filter: 'granted' to return only tools the calling agent is granted, or 'all' (default) to return every registered tool name.",
            },
        },
        "required": [],
    }

    def __init__(self, agent_dir=None, session_id=None):
        self._caller = agent_dir.name if agent_dir else "master"

    async def execute(self, **params: Any) -> str:
        from app.utils.tools import TOOL_REGISTRY

        filter_value = params.get("filter", "all")

        if filter_value == "granted":
            names = await self._granted_names()
        else:
            names = sorted(TOOL_REGISTRY.keys())

        return json.dumps(
            {"count": len(names), "tools": names},
            separators=(",", ":"),
        )

    async def _granted_names(self) -> list[str]:
        """Resolve the caller's granted tool names, wildcard-expanded."""
        from app.utils.tools import TOOL_REGISTRY

        names: list[str] = []
        try:
            from app.config import settings
            from app.agents.base import BaseAgent

            agent = BaseAgent(settings.agents_dir / self._caller)
            names = await agent._load_tool_names()
        except Exception:
            names = []

        if not names:
            try:
                from app.utils.agent_settings import agent_tools

                names = agent_tools(self._caller)
            except Exception:
                names = []

        try:
            from app.utils.tools import resolve_tool_names

            names = resolve_tool_names(names)
        except Exception:
            pass

        return sorted(n for n in names if n in TOOL_REGISTRY)
