"""Collaborative architecture-canvas HTTP API."""
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from app.utils import whiteboard

router = APIRouter(prefix="/whiteboard", tags=["whiteboard"])
Kind = Literal["note", "decision", "question", "task", "link", "artifact", "actor", "component", "service", "api", "database", "queue", "event", "interface", "module", "boundary", "external", "process", "condition", "terminator", "input_output", "document", "data_store", "subprocess", "manual_input", "preparation", "connector", "delay"]
Color = Literal["amber", "mint", "blue", "rose", "violet"]
Relationship = Literal["related", "depends_on", "calls", "reads", "writes", "emits", "subscribes", "contains", "implements", "extends", "blocks", "flows_to"]
EdgeStyle = Literal["solid", "dashed", "dotted"]
EdgeDirection = Literal["none", "forward", "backward", "both"]
EdgeRouting = Literal["straight", "curved", "orthogonal"]
EdgeColor = Literal["default", "amber", "mint", "blue", "rose", "violet"]


class BoardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)


class BoardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)


class CardCreate(BaseModel):
    board_id: str = "main"
    kind: Kind = "component"
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(default="", max_length=4000)
    color: Color = "amber"
    x: float = Field(default=80, ge=0, le=3840)
    y: float = Field(default=80, ge=0, le=2400)
    width: float = Field(default=230, ge=160, le=600)
    height: float = Field(default=160, ge=100, le=500)
    details: dict[str, Any] = Field(default_factory=dict)


class CardUpdate(BaseModel):
    revision: int = Field(ge=1)
    kind: Kind | None = None
    title: str | None = Field(default=None, min_length=1, max_length=120)
    body: str | None = Field(default=None, max_length=4000)
    color: Color | None = None
    x: float | None = Field(default=None, ge=0, le=3840)
    y: float | None = Field(default=None, ge=0, le=2400)
    width: float | None = Field(default=None, ge=160, le=600)
    height: float | None = Field(default=None, ge=100, le=500)
    details: dict[str, Any] | None = None


class EdgeCreate(BaseModel):
    board_id: str = "main"
    source_id: str
    target_id: str
    relationship: Relationship = "related"
    label: str = Field(default="", max_length=80)
    style: EdgeStyle = "solid"
    direction: EdgeDirection = "forward"
    routing: EdgeRouting = "straight"
    color: EdgeColor = "default"
    thickness: float = Field(default=2, ge=1, le=6)


class EdgeUpdate(BaseModel):
    revision: int = Field(ge=1)
    relationship: Relationship | None = None
    label: str | None = Field(default=None, max_length=80)
    style: EdgeStyle | None = None
    direction: EdgeDirection | None = None
    routing: EdgeRouting | None = None
    color: EdgeColor | None = None
    thickness: float | None = Field(default=None, ge=1, le=6)


class ExportRequest(BaseModel):
    format: Literal["markdown", "mermaid", "json"] = "markdown"
    destination: Literal["download", "notes", "workspace", "artifact"] = "download"


def _bad_request(call):
    try: return call()
    except KeyError as exc: raise HTTPException(404, exc.args[0] if exc.args else "Not found") from exc
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


@router.get("")
def read_default_board(): return _bad_request(lambda: whiteboard.get_board("main"))


@router.get("/boards")
def read_boards(): return {"boards": whiteboard.list_boards()}


@router.post("/boards", status_code=201)
def add_board(payload: BoardCreate): return _bad_request(lambda: whiteboard.create_board(**payload.model_dump(), created_by="user"))


@router.get("/boards/{board_id}")
def read_board(board_id: str): return _bad_request(lambda: whiteboard.get_board(board_id))


@router.patch("/boards/{board_id}")
def edit_board(board_id: str, payload: BoardUpdate):
    board = _bad_request(lambda: whiteboard.update_board(board_id, **payload.model_dump(exclude_none=True)))
    if board is None: raise HTTPException(404, "Canvas not found")
    return board


@router.delete("/boards/{board_id}", status_code=204)
def remove_board(board_id: str):
    deleted = _bad_request(lambda: whiteboard.delete_board(board_id))
    if not deleted: raise HTTPException(404, "Canvas not found")
    return Response(status_code=204)


@router.post("/cards", status_code=201)
def add_card(payload: CardCreate): return _bad_request(lambda: whiteboard.create_card(**payload.model_dump(), created_by="user"))


@router.put("/cards/{card_id}")
def edit_card(card_id: str, payload: CardUpdate):
    try: card = whiteboard.update_card(card_id, revision=payload.revision, changes=payload.model_dump(exclude={"revision"}, exclude_none=True))
    except whiteboard.WhiteboardConflictError as exc: raise HTTPException(409, str(exc)) from exc
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    if card is None: raise HTTPException(404, "Card not found")
    return card


@router.delete("/cards/{card_id}", status_code=204)
def remove_card(card_id: str):
    if not whiteboard.delete_card(card_id): raise HTTPException(404, "Card not found")
    return Response(status_code=204)


@router.post("/edges", status_code=201)
def add_edge(payload: EdgeCreate): return _bad_request(lambda: whiteboard.create_edge(**payload.model_dump(), created_by="user"))


@router.put("/edges/{edge_id}")
def edit_edge(edge_id: str, payload: EdgeUpdate):
    try: edge = whiteboard.update_edge(edge_id, revision=payload.revision, changes=payload.model_dump(exclude={"revision"}, exclude_none=True))
    except whiteboard.WhiteboardConflictError as exc: raise HTTPException(409, str(exc)) from exc
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    if edge is None: raise HTTPException(404, "Connection not found")
    return edge


@router.delete("/edges/{edge_id}", status_code=204)
def remove_edge(edge_id: str):
    if not whiteboard.delete_edge(edge_id): raise HTTPException(404, "Connection not found")
    return Response(status_code=204)


@router.post("/boards/{board_id}/export")
def export_board(board_id: str, payload: ExportRequest):
    return _bad_request(lambda: whiteboard.export_board(board_id, payload.format, payload.destination, "user"))
