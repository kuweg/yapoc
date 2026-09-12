"""Shared, revisioned whiteboard persistence for the UI and agent tools."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.utils.db import get_db
from app.utils.secrets import scrub

KINDS = {"note", "decision", "question", "task", "link", "artifact"}
COLORS = {"amber", "mint", "blue", "rose", "violet"}


class WhiteboardConflictError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: str, limit: int) -> str:
    return scrub(str(value or "")).strip()[:limit]


def _bump(db: Any) -> int:
    now = _now()
    db.execute(
        """INSERT INTO whiteboard_state(board, revision, updated_at)
           VALUES('main', 1, ?)
           ON CONFLICT(board) DO UPDATE SET revision=revision+1, updated_at=excluded.updated_at""",
        (now,),
    )
    return int(db.execute("SELECT revision FROM whiteboard_state WHERE board='main'").fetchone()[0])


def get_board() -> dict[str, Any]:
    db = get_db()
    cards = [dict(row) for row in db.execute("SELECT * FROM whiteboard_cards ORDER BY created_at")]
    edges = [dict(row) for row in db.execute("SELECT * FROM whiteboard_edges ORDER BY created_at")]
    state = db.execute("SELECT revision, updated_at FROM whiteboard_state WHERE board='main'").fetchone()
    return {
        "revision": int(state["revision"]) if state else 0,
        "updated_at": state["updated_at"] if state else None,
        "cards": cards,
        "edges": edges,
    }


def create_card(*, kind: str, title: str, body: str = "", color: str = "amber",
                x: float = 80, y: float = 80, created_by: str = "user") -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError("Unsupported card kind")
    if color not in COLORS:
        raise ValueError("Unsupported card color")
    clean_title = _clean(title, 120)
    if not clean_title:
        raise ValueError("Card title is required")
    card_id, now = str(uuid4()), _now()
    db = get_db()
    with db:
        db.execute(
            """INSERT INTO whiteboard_cards
               (id, kind, title, body, color, x, y, created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (card_id, kind, clean_title, _clean(body, 4000), color,
             max(0.0, min(float(x), 1920.0)), max(0.0, min(float(y), 1200.0)),
             _clean(created_by, 40) or "user", now, now),
        )
        _bump(db)
    return dict(db.execute("SELECT * FROM whiteboard_cards WHERE id=?", (card_id,)).fetchone())


def update_card(card_id: str, *, revision: int, changes: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"kind", "title", "body", "color", "x", "y"}
    fields: dict[str, Any] = {}
    for key, value in changes.items():
        if key not in allowed or value is None:
            continue
        if key == "kind":
            if value not in KINDS:
                raise ValueError("Unsupported card kind")
            fields[key] = value
        elif key == "color":
            if value not in COLORS:
                raise ValueError("Unsupported card color")
            fields[key] = value
        elif key == "title":
            fields[key] = _clean(value, 120)
            if not fields[key]:
                raise ValueError("Card title is required")
        elif key == "body":
            fields[key] = _clean(value, 4000)
        else:
            limit = 1920.0 if key == "x" else 1200.0
            fields[key] = max(0.0, min(float(value), limit))
    if not fields:
        row = get_db().execute("SELECT * FROM whiteboard_cards WHERE id=?", (card_id,)).fetchone()
        return dict(row) if row else None
    fields.update(updated_at=_now())
    assignments = ", ".join(f"{key}=?" for key in fields)
    db = get_db()
    with db:
        cursor = db.execute(
            f"UPDATE whiteboard_cards SET {assignments}, revision=revision+1 WHERE id=? AND revision=?",
            (*fields.values(), card_id, revision),
        )
        if cursor.rowcount == 0:
            exists = db.execute("SELECT 1 FROM whiteboard_cards WHERE id=?", (card_id,)).fetchone()
            if exists:
                raise WhiteboardConflictError("This card changed elsewhere. Refresh and try again.")
            return None
        _bump(db)
    return dict(db.execute("SELECT * FROM whiteboard_cards WHERE id=?", (card_id,)).fetchone())


def delete_card(card_id: str) -> bool:
    db = get_db()
    with db:
        cursor = db.execute("DELETE FROM whiteboard_cards WHERE id=?", (card_id,))
        if cursor.rowcount:
            _bump(db)
    return bool(cursor.rowcount)


def create_edge(*, source_id: str, target_id: str, label: str = "", created_by: str = "user") -> dict[str, Any]:
    if source_id == target_id:
        raise ValueError("A card cannot connect to itself")
    db = get_db()
    count = db.execute(
        "SELECT count(*) FROM whiteboard_cards WHERE id IN (?, ?)", (source_id, target_id)
    ).fetchone()[0]
    if count != 2:
        raise KeyError("Card not found")
    edge_id, now = str(uuid4()), _now()
    try:
        with db:
            db.execute(
                "INSERT INTO whiteboard_edges(id, source_id, target_id, label, created_by, created_at) VALUES(?,?,?,?,?,?)",
                (edge_id, source_id, target_id, _clean(label, 80), _clean(created_by, 40) or "user", now),
            )
            _bump(db)
    except Exception as exc:
        if "UNIQUE constraint" in str(exc):
            raise ValueError("These cards are already connected") from exc
        raise
    return dict(db.execute("SELECT * FROM whiteboard_edges WHERE id=?", (edge_id,)).fetchone())


def delete_edge(edge_id: str) -> bool:
    db = get_db()
    with db:
        cursor = db.execute("DELETE FROM whiteboard_edges WHERE id=?", (edge_id,))
        if cursor.rowcount:
            _bump(db)
    return bool(cursor.rowcount)
