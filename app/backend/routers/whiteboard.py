"""Collaborative whiteboard HTTP API."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from app.utils import whiteboard

router = APIRouter(prefix="/whiteboard", tags=["whiteboard"])
Kind = Literal["note", "decision", "question", "task", "link", "artifact"]
Color = Literal["amber", "mint", "blue", "rose", "violet"]


class CardCreate(BaseModel):
    kind: Kind = "note"
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(default="", max_length=4000)
    color: Color = "amber"
    x: float = Field(default=80, ge=0, le=1920)
    y: float = Field(default=80, ge=0, le=1200)


class CardUpdate(BaseModel):
    revision: int = Field(ge=1)
    kind: Kind | None = None
    title: str | None = Field(default=None, min_length=1, max_length=120)
    body: str | None = Field(default=None, max_length=4000)
    color: Color | None = None
    x: float | None = Field(default=None, ge=0, le=1920)
    y: float | None = Field(default=None, ge=0, le=1200)


class EdgeCreate(BaseModel):
    source_id: str
    target_id: str
    label: str = Field(default="", max_length=80)


@router.get("")
def read_board():
    return whiteboard.get_board()


@router.post("/cards", status_code=201)
def add_card(payload: CardCreate):
    try:
        return whiteboard.create_card(**payload.model_dump(), created_by="user")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put("/cards/{card_id}")
def edit_card(card_id: str, payload: CardUpdate):
    values = payload.model_dump(exclude={"revision"}, exclude_none=True)
    try:
        card = whiteboard.update_card(card_id, revision=payload.revision, changes=values)
    except whiteboard.WhiteboardConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if card is None:
        raise HTTPException(404, "Card not found")
    return card


@router.delete("/cards/{card_id}", status_code=204)
def remove_card(card_id: str):
    if not whiteboard.delete_card(card_id):
        raise HTTPException(404, "Card not found")
    return Response(status_code=204)


@router.post("/edges", status_code=201)
def add_edge(payload: EdgeCreate):
    try:
        return whiteboard.create_edge(**payload.model_dump(), created_by="user")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/edges/{edge_id}", status_code=204)
def remove_edge(edge_id: str):
    if not whiteboard.delete_edge(edge_id):
        raise HTTPException(404, "Connection not found")
    return Response(status_code=204)
