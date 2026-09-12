"""Agent tools for understanding and generating architecture canvases."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.utils import whiteboard
from . import BaseTool

KINDS = sorted(whiteboard.KINDS)
RELATIONSHIPS = sorted(whiteboard.RELATIONSHIPS)


class _AgentTool(BaseTool):
    def __init__(self, agent_dir: Path | None = None) -> None: self._agent = agent_dir.name if agent_dir else "agent"
    @staticmethod
    def compact(value: Any) -> str: return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


class WhiteboardListTool(_AgentTool):
    name = "whiteboard_list"
    description = "List architecture canvases or read one complete design, including typed nodes, structured details, and directional relationships. Always read a referenced @whiteboard before implementing its design."
    input_schema = {"type": "object", "properties": {"board_id": {"type": "string", "description": "Canvas id. Omit to list canvases."}}, "required": []}
    async def execute(self, **params: Any) -> str:
        board_id = params.get("board_id")
        return self.compact(whiteboard.get_board(board_id) if board_id else {"boards": whiteboard.list_boards()})


class WhiteboardCreateCanvasTool(_AgentTool):
    name = "whiteboard_create_canvas"
    description = "Create a named architecture canvas for a system, feature, workflow, or data model."
    input_schema = {"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}}, "required": ["name"]}
    async def execute(self, **params: Any) -> str:
        return self.compact(whiteboard.create_board(params["name"], params.get("description", ""), self._agent))


class WhiteboardAddCardTool(_AgentTool):
    name = "whiteboard_add_card"
    description = "Add a typed architecture node or design card to a canvas. Use details for contracts, fields, endpoints, constraints, or technology choices."
    input_schema = {"type": "object", "properties": {
        "board_id": {"type": "string", "default": "main"}, "title": {"type": "string"}, "body": {"type": "string"},
        "kind": {"type": "string", "enum": KINDS}, "details": {"type": "object", "additionalProperties": True},
        "color": {"type": "string", "enum": sorted(whiteboard.COLORS)}, "x": {"type": "number"}, "y": {"type": "number"},
    }, "required": ["title"]}
    async def execute(self, **params: Any) -> str:
        values = {key: params[key] for key in ("board_id", "title", "body", "kind", "details", "color", "x", "y") if key in params}
        values.setdefault("kind", "component"); values["created_by"] = self._agent
        return self.compact(whiteboard.create_card(**values))


class WhiteboardUpdateCardTool(_AgentTool):
    name = "whiteboard_update_card"
    description = "Update a design card using its current revision; stale changes are refused."
    input_schema = {"type": "object", "properties": {
        "card_id": {"type": "string"}, "revision": {"type": "integer", "minimum": 1}, "title": {"type": "string"},
        "body": {"type": "string"}, "kind": {"type": "string", "enum": KINDS}, "details": {"type": "object", "additionalProperties": True},
        "color": {"type": "string", "enum": sorted(whiteboard.COLORS)},
    }, "required": ["card_id", "revision"]}
    async def execute(self, **params: Any) -> str:
        changes = {key: params[key] for key in ("title", "body", "kind", "details", "color") if key in params}
        card = whiteboard.update_card(params["card_id"], revision=int(params["revision"]), changes=changes)
        return self.compact(card) if card else "Error: whiteboard card not found"


class WhiteboardConnectTool(_AgentTool):
    name = "whiteboard_connect"
    description = "Create a typed directional relationship between two nodes on the same canvas."
    input_schema = {"type": "object", "properties": {
        "board_id": {"type": "string", "default": "main"}, "source_id": {"type": "string"}, "target_id": {"type": "string"},
        "relationship": {"type": "string", "enum": RELATIONSHIPS}, "label": {"type": "string"},
        "style": {"type": "string", "enum": sorted(whiteboard.EDGE_STYLES)},
    }, "required": ["source_id", "target_id", "relationship"]}
    async def execute(self, **params: Any) -> str:
        values = dict(params); values["created_by"] = self._agent
        return self.compact(whiteboard.create_edge(**values))


class WhiteboardApplyDesignTool(_AgentTool):
    name = "whiteboard_apply_design"
    description = "Generate or extend a complete architecture design in one operation. Give each node a short key and use those keys as edge endpoints. Existing user content is preserved."
    input_schema = {"type": "object", "properties": {
        "board_id": {"type": "string", "default": "main"},
        "cards": {"type": "array", "maxItems": 100, "items": {"type": "object", "properties": {"key": {"type": "string"}, "title": {"type": "string"}, "kind": {"type": "string", "enum": KINDS}, "body": {"type": "string"}, "details": {"type": "object"}, "x": {"type": "number"}, "y": {"type": "number"}}, "required": ["key", "title", "kind"]}},
        "edges": {"type": "array", "maxItems": 200, "items": {"type": "object", "properties": {"source": {"type": "string"}, "target": {"type": "string"}, "relationship": {"type": "string", "enum": RELATIONSHIPS}, "label": {"type": "string"}, "style": {"type": "string", "enum": sorted(whiteboard.EDGE_STYLES)}}, "required": ["source", "target", "relationship"]}},
    }, "required": ["cards", "edges"]}
    async def execute(self, **params: Any) -> str:
        return self.compact(whiteboard.apply_design(params.get("board_id", "main"), params["cards"], params["edges"], self._agent, False))


class WhiteboardExportTool(_AgentTool):
    name = "whiteboard_export"
    description = "Export a canvas as Markdown, Mermaid, or JSON to Notes, workspace files, or the artifact gallery."
    input_schema = {"type": "object", "properties": {
        "board_id": {"type": "string", "default": "main"}, "format": {"type": "string", "enum": ["markdown", "mermaid", "json"]},
        "destination": {"type": "string", "enum": ["notes", "workspace", "artifact"]},
    }, "required": ["format", "destination"]}
    async def execute(self, **params: Any) -> str:
        return self.compact(whiteboard.export_board(params.get("board_id", "main"), params["format"], params["destination"], self._agent))
