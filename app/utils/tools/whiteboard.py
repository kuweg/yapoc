"""Agent tools for contributing to the shared whiteboard."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.utils.whiteboard import create_card, get_board, update_card

from . import BaseTool


class WhiteboardListTool(BaseTool):
    name = "whiteboard_list"
    description = "Read the shared project whiteboard, including cards and connections."
    input_schema: dict[str, Any] = {"type": "object", "properties": {}, "required": []}

    async def execute(self, **params: Any) -> str:
        return json.dumps(get_board(), separators=(",", ":"))


class WhiteboardAddCardTool(BaseTool):
    name = "whiteboard_add_card"
    description = "Add a concise finding, question, task, decision, link, or artifact to the shared whiteboard."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short card title"},
            "body": {"type": "string", "description": "Useful context, kept concise"},
            "kind": {"type": "string", "enum": ["note", "decision", "question", "task", "link", "artifact"]},
            "color": {"type": "string", "enum": ["amber", "mint", "blue", "rose", "violet"]},
            "x": {"type": "number", "description": "Horizontal board position, 0-1920"},
            "y": {"type": "number", "description": "Vertical board position, 0-1200"},
        },
        "required": ["title"],
    }

    def __init__(self, agent_dir: Path) -> None:
        self._agent = agent_dir.name

    async def execute(self, **params: Any) -> str:
        card = create_card(
            title=params["title"], body=params.get("body", ""), kind=params.get("kind", "note"),
            color=params.get("color", "amber"), x=params.get("x", 80), y=params.get("y", 80),
            created_by=self._agent,
        )
        return json.dumps(card, separators=(",", ":"))


class WhiteboardUpdateCardTool(BaseTool):
    name = "whiteboard_update_card"
    description = "Update a shared whiteboard card using the revision returned by whiteboard_list."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "card_id": {"type": "string"},
            "revision": {"type": "integer", "minimum": 1},
            "title": {"type": "string"},
            "body": {"type": "string"},
            "kind": {"type": "string", "enum": ["note", "decision", "question", "task", "link", "artifact"]},
            "color": {"type": "string", "enum": ["amber", "mint", "blue", "rose", "violet"]},
        },
        "required": ["card_id", "revision"],
    }

    def __init__(self, agent_dir: Path) -> None:
        self._agent = agent_dir.name

    async def execute(self, **params: Any) -> str:
        changes = {key: params[key] for key in ("title", "body", "kind", "color") if key in params}
        card = update_card(params["card_id"], revision=int(params["revision"]), changes=changes)
        if card is None:
            return "Error: whiteboard card not found"
        return json.dumps(card, separators=(",", ":"))
