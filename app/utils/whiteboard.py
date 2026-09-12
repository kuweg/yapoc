"""YAPOC architecture canvas persistence, interchange, and export."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from uuid import uuid4

from app.config import settings
from app.utils.db import get_db
from app.utils.secrets import scrub

KINDS = {
    "note", "decision", "question", "task", "link", "artifact", "actor",
    "component", "service", "api", "database", "queue", "event", "interface",
    "module", "boundary", "external", "process", "condition", "terminator",
    "input_output", "document", "data_store", "subprocess", "manual_input",
    "preparation", "connector", "delay",
}
COLORS = {"amber", "mint", "blue", "rose", "violet"}
RELATIONSHIPS = {"related", "depends_on", "calls", "reads", "writes", "emits", "subscribes", "contains", "implements", "extends", "blocks", "flows_to"}
EDGE_STYLES = {"solid", "dashed", "dotted"}
EDGE_DIRECTIONS = {"none", "forward", "backward", "both"}
EDGE_ROUTINGS = {"straight", "curved", "orthogonal"}
EDGE_COLORS = {"default", *COLORS}


class WhiteboardConflictError(RuntimeError): pass


def _now() -> str: return datetime.now(timezone.utc).isoformat()
def _clean(value: Any, limit: int) -> str: return scrub(str(value or "")).strip()[:limit]
def _safe_id(value: str, fallback: str = "design") -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-_")[:64] or fallback


def _decode_card(row: Any) -> dict[str, Any]:
    card = dict(row)
    try: card["details"] = json.loads(card.get("details") or "{}")
    except (TypeError, json.JSONDecodeError): card["details"] = {}
    return card


def _safe_details(value: Any, depth: int = 0) -> Any:
    """Redact string leaves without applying regexes to JSON syntax."""
    if depth > 6: return "[truncated]"
    if isinstance(value, dict):
        return {_clean(key, 80): _safe_details(item, depth + 1) for key, item in list(value.items())[:80]}
    if isinstance(value, list): return [_safe_details(item, depth + 1) for item in value[:80]]
    if isinstance(value, str): return _clean(value, 2000)
    if value is None or isinstance(value, (bool, int, float)): return value
    return _clean(value, 500)


def _encode_details(value: Any) -> str:
    encoded = json.dumps(_safe_details(value or {}), separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode("utf-8")) > 12_000: raise ValueError("Structured details exceed 12 KB")
    return encoded


def _bump(db: Any, board_id: str) -> int:
    now = _now()
    db.execute("""INSERT INTO whiteboard_state(board,revision,updated_at) VALUES(?,1,?)
        ON CONFLICT(board) DO UPDATE SET revision=revision+1,updated_at=excluded.updated_at""", (board_id, now))
    db.execute("UPDATE whiteboards SET updated_at=? WHERE id=?", (now, board_id))
    return int(db.execute("SELECT revision FROM whiteboard_state WHERE board=?", (board_id,)).fetchone()[0])


def list_boards() -> list[dict[str, Any]]:
    rows = get_db().execute("""SELECT b.*,COALESCE(s.revision,0) revision,
        (SELECT count(*) FROM whiteboard_cards c WHERE c.board_id=b.id) card_count
        FROM whiteboards b LEFT JOIN whiteboard_state s ON s.board=b.id ORDER BY b.updated_at DESC""").fetchall()
    return [dict(row) for row in rows]


def _normalize_board_ref(value: str) -> str:
    return re.sub(r"[\s_-]+", " ", unquote(value).strip().casefold()).strip()


def resolve_board(reference: str) -> dict[str, Any]:
    """Resolve an exact canvas id or normalized name without guessing."""
    value = unquote(reference).strip()
    db = get_db()
    row = db.execute("SELECT * FROM whiteboards WHERE id=?", (value,)).fetchone()
    if row: return dict(row)
    key = _normalize_board_ref(value)
    matches = [board for board in list_boards() if _normalize_board_ref(board["name"]) == key]
    if not matches: raise KeyError(f'Whiteboard canvas "{value}" was not found')
    if len(matches) > 1: raise ValueError(f'Whiteboard canvas name "{value}" is ambiguous; use its canvas id')
    return matches[0]


def build_whiteboard_context(task: str) -> tuple[str, list[dict[str, str]]]:
    """Snapshot explicitly mentioned canvases into a task's durable prompt."""
    pattern = re.compile(r'@whiteboard:(?:"([^"\n]+)"|([^\s@"]+))', re.IGNORECASE)
    references = [quoted or bare for quoted, bare in pattern.findall(task or "")]
    if not references: return "", []
    resolved: list[dict[str, str]] = []
    seen: set[str] = set()
    chunks: list[str] = []
    payload_bytes = 0
    for reference in references:
        canvas = resolve_board(reference)
        board_id = canvas["id"]
        if board_id in seen: continue
        if len(seen) >= 3: raise ValueError("A task may reference at most three whiteboard canvases")
        seen.add(board_id)
        board = get_board(board_id)
        resolved.append({"id": board_id, "name": canvas["name"]})
        payload = json.dumps(board, separators=(",", ":"), ensure_ascii=False)
        payload_bytes += len(payload.encode("utf-8"))
        if payload_bytes > 240_000:
            raise ValueError("Referenced whiteboard context exceeds 240 KB; split the design across smaller canvases")
        chunks.append(
            "\n\n--- Referenced YAPOC whiteboard canvas ---\n"
            f'Canvas: {canvas["name"]}\nCanvas ID: {board_id}\n'
            "Read this design as user-provided implementation intent. When adding or updating "
            f"nodes and connections, pass board_id={json.dumps(board_id)} so work stays on this canvas. "
            "Do not create a replacement canvas unless the user explicitly requests one.\n"
            f"Structured design (compact JSON):\n{payload}"
        )
    return "".join(chunks), resolved


def create_board(name: str, description: str = "", created_by: str = "user") -> dict[str, Any]:
    name = _clean(name, 100)
    if not name: raise ValueError("Canvas name is required")
    board_id, now = f"{_safe_id(name)}-{uuid4().hex[:8]}", _now(); db = get_db()
    with db:
        db.execute("INSERT INTO whiteboards(id,name,description,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?)", (board_id, name, _clean(description, 1000), _clean(created_by, 40) or "user", now, now))
        db.execute("INSERT INTO whiteboard_state(board,revision,updated_at) VALUES(?,0,?)", (board_id, now))
    return get_board(board_id)["canvas"]


def update_board(board_id: str, *, name: str | None = None, description: str | None = None) -> dict[str, Any] | None:
    fields: dict[str, str] = {}
    if name is not None:
        fields["name"] = _clean(name, 100)
        if not fields["name"]: raise ValueError("Canvas name is required")
    if description is not None: fields["description"] = _clean(description, 1000)
    db = get_db()
    if not fields:
        row = db.execute("SELECT * FROM whiteboards WHERE id=?", (board_id,)).fetchone(); return dict(row) if row else None
    fields["updated_at"] = _now()
    with db: cursor = db.execute(f"UPDATE whiteboards SET {', '.join(f'{key}=?' for key in fields)} WHERE id=?", (*fields.values(), board_id))
    row = db.execute("SELECT * FROM whiteboards WHERE id=?", (board_id,)).fetchone(); return dict(row) if cursor.rowcount and row else None


def delete_board(board_id: str) -> bool:
    if board_id == "main": raise ValueError("The default canvas cannot be deleted")
    db = get_db()
    with db:
        db.execute("DELETE FROM whiteboard_edges WHERE board_id=?", (board_id,)); db.execute("DELETE FROM whiteboard_cards WHERE board_id=?", (board_id,)); db.execute("DELETE FROM whiteboard_state WHERE board=?", (board_id,)); cursor = db.execute("DELETE FROM whiteboards WHERE id=?", (board_id,))
    return bool(cursor.rowcount)


def get_board(board_id: str = "main") -> dict[str, Any]:
    db = get_db(); canvas = db.execute("SELECT * FROM whiteboards WHERE id=?", (board_id,)).fetchone()
    if not canvas: raise KeyError("Canvas not found")
    cards = [_decode_card(row) for row in db.execute("SELECT * FROM whiteboard_cards WHERE board_id=? ORDER BY created_at", (board_id,))]
    edges = [dict(row) for row in db.execute("SELECT * FROM whiteboard_edges WHERE board_id=? ORDER BY created_at", (board_id,))]
    state = db.execute("SELECT revision,updated_at FROM whiteboard_state WHERE board=?", (board_id,)).fetchone()
    return {"canvas": dict(canvas), "revision": int(state["revision"]) if state else 0, "updated_at": state["updated_at"] if state else canvas["updated_at"], "cards": cards, "edges": edges}


def create_card(*, kind: str, title: str, body: str = "", color: str = "amber", x: float = 80, y: float = 80, width: float = 230, height: float = 160, details: dict[str, Any] | None = None, board_id: str = "main", created_by: str = "user") -> dict[str, Any]:
    if kind not in KINDS: raise ValueError("Unsupported card kind")
    if color not in COLORS: raise ValueError("Unsupported card color")
    title = _clean(title, 120)
    if not title: raise ValueError("Card title is required")
    db = get_db()
    if not db.execute("SELECT 1 FROM whiteboards WHERE id=?", (board_id,)).fetchone(): raise KeyError("Canvas not found")
    encoded_details = _encode_details(details); card_id, now = str(uuid4()), _now()
    with db:
        db.execute("""INSERT INTO whiteboard_cards(id,kind,title,body,color,x,y,created_by,created_at,updated_at,board_id,details,width,height)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (card_id, kind, title, _clean(body, 4000), color, max(0., min(float(x), 3840.)), max(0., min(float(y), 2400.)), _clean(created_by, 40) or "user", now, now, board_id, encoded_details, max(160., min(float(width), 600.)), max(100., min(float(height), 500.))))
        _bump(db, board_id)
    return _decode_card(db.execute("SELECT * FROM whiteboard_cards WHERE id=?", (card_id,)).fetchone())


def update_card(card_id: str, *, revision: int, changes: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"kind", "title", "body", "color", "x", "y", "width", "height", "details"}; fields: dict[str, Any] = {}
    for key, value in changes.items():
        if key not in allowed or value is None: continue
        if key == "kind":
            if value not in KINDS: raise ValueError("Unsupported card kind")
            fields[key] = value
        elif key == "color":
            if value not in COLORS: raise ValueError("Unsupported card color")
            fields[key] = value
        elif key == "title":
            fields[key] = _clean(value, 120)
            if not fields[key]: raise ValueError("Card title is required")
        elif key == "body": fields[key] = _clean(value, 4000)
        elif key == "details": fields[key] = _encode_details(value)
        else:
            lower, upper = ((160., 600.) if key == "width" else (100., 500.)) if key in {"width", "height"} else (0., 3840. if key == "x" else 2400.)
            fields[key] = max(lower, min(float(value), upper))
    db = get_db(); current = db.execute("SELECT board_id FROM whiteboard_cards WHERE id=?", (card_id,)).fetchone()
    if not current: return None
    if not fields: return _decode_card(db.execute("SELECT * FROM whiteboard_cards WHERE id=?", (card_id,)).fetchone())
    fields["updated_at"] = _now()
    with db:
        cursor = db.execute(f"UPDATE whiteboard_cards SET {', '.join(f'{key}=?' for key in fields)},revision=revision+1 WHERE id=? AND revision=?", (*fields.values(), card_id, revision))
        if not cursor.rowcount: raise WhiteboardConflictError("This card changed elsewhere. Refresh and try again.")
        _bump(db, current["board_id"])
    return _decode_card(db.execute("SELECT * FROM whiteboard_cards WHERE id=?", (card_id,)).fetchone())


def delete_card(card_id: str) -> bool:
    db = get_db(); row = db.execute("SELECT board_id FROM whiteboard_cards WHERE id=?", (card_id,)).fetchone()
    if not row: return False
    with db:
        db.execute("DELETE FROM whiteboard_edges WHERE source_id=? OR target_id=?", (card_id, card_id)); cursor = db.execute("DELETE FROM whiteboard_cards WHERE id=?", (card_id,)); _bump(db, row["board_id"])
    return bool(cursor.rowcount)


def create_edge(*, source_id: str, target_id: str, label: str = "", relationship: str = "related", style: str = "solid", direction: str = "forward", routing: str = "straight", color: str = "default", thickness: float = 2, board_id: str = "main", created_by: str = "user") -> dict[str, Any]:
    if source_id == target_id: raise ValueError("A card cannot connect to itself")
    if relationship not in RELATIONSHIPS: raise ValueError("Unsupported relationship")
    if style not in EDGE_STYLES: raise ValueError("Unsupported connection style")
    if direction not in EDGE_DIRECTIONS: raise ValueError("Unsupported connection direction")
    if routing not in EDGE_ROUTINGS: raise ValueError("Unsupported connection routing")
    if color not in EDGE_COLORS: raise ValueError("Unsupported connection color")
    db = get_db(); rows = db.execute("SELECT id,board_id FROM whiteboard_cards WHERE id IN (?,?)", (source_id, target_id)).fetchall()
    if len(rows) != 2: raise KeyError("Card not found")
    actual_board = rows[0]["board_id"]
    if actual_board != rows[1]["board_id"] or actual_board != board_id: raise ValueError("Connections must stay inside one canvas")
    edge_id, now = str(uuid4()), _now()
    try:
        with db:
            db.execute("""INSERT INTO whiteboard_edges(
                id,source_id,target_id,label,created_by,created_at,board_id,relationship,
                style,direction,routing,color,thickness,revision,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""", (
                edge_id, source_id, target_id, _clean(label, 80),
                _clean(created_by, 40) or "user", now, board_id, relationship,
                style, direction, routing, color, max(1., min(float(thickness), 6.)), now,
            )); _bump(db, board_id)
    except Exception as exc:
        if "UNIQUE constraint" in str(exc): raise ValueError("These cards are already connected") from exc
        raise
    return dict(db.execute("SELECT * FROM whiteboard_edges WHERE id=?", (edge_id,)).fetchone())


def update_edge(edge_id: str, *, revision: int, changes: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"label", "relationship", "style", "direction", "routing", "color", "thickness"}
    fields: dict[str, Any] = {}
    enums = {
        "relationship": RELATIONSHIPS, "style": EDGE_STYLES,
        "direction": EDGE_DIRECTIONS, "routing": EDGE_ROUTINGS, "color": EDGE_COLORS,
    }
    for key, value in changes.items():
        if key not in allowed or value is None: continue
        if key == "label": fields[key] = _clean(value, 80)
        elif key == "thickness": fields[key] = max(1., min(float(value), 6.))
        else:
            if value not in enums[key]: raise ValueError(f"Unsupported connection {key}")
            fields[key] = value
    db = get_db(); current = db.execute("SELECT board_id FROM whiteboard_edges WHERE id=?", (edge_id,)).fetchone()
    if not current: return None
    if not fields: return dict(db.execute("SELECT * FROM whiteboard_edges WHERE id=?", (edge_id,)).fetchone())
    fields["updated_at"] = _now()
    with db:
        cursor = db.execute(
            f"UPDATE whiteboard_edges SET {', '.join(f'{key}=?' for key in fields)},revision=revision+1 WHERE id=? AND revision=?",
            (*fields.values(), edge_id, revision),
        )
        if not cursor.rowcount: raise WhiteboardConflictError("This connection changed elsewhere. Refresh and try again.")
        _bump(db, current["board_id"])
    return dict(db.execute("SELECT * FROM whiteboard_edges WHERE id=?", (edge_id,)).fetchone())


def delete_edge(edge_id: str) -> bool:
    db = get_db(); row = db.execute("SELECT board_id FROM whiteboard_edges WHERE id=?", (edge_id,)).fetchone()
    if not row: return False
    with db: cursor = db.execute("DELETE FROM whiteboard_edges WHERE id=?", (edge_id,)); _bump(db, row["board_id"])
    return bool(cursor.rowcount)


def apply_design(board_id: str, cards: list[dict[str, Any]], edges: list[dict[str, Any]], created_by: str, replace: bool = False) -> dict[str, Any]:
    if len(cards) > 100 or len(edges) > 200: raise ValueError("A design may contain at most 100 cards and 200 relationships")
    if replace:
        db = get_db()
        with db: db.execute("DELETE FROM whiteboard_edges WHERE board_id=?", (board_id,)); db.execute("DELETE FROM whiteboard_cards WHERE board_id=?", (board_id,)); _bump(db, board_id)
    ids: dict[str, str] = {}
    for index, card in enumerate(cards):
        created = create_card(board_id=board_id, created_by=created_by, **{k: v for k, v in card.items() if k in {"kind", "title", "body", "color", "x", "y", "width", "height", "details"}}); ids[str(card.get("key") or index)] = created["id"]
    for edge in edges:
        source = ids.get(str(edge.get("source")), str(edge.get("source", ""))); target = ids.get(str(edge.get("target")), str(edge.get("target", "")))
        create_edge(
            source_id=source, target_id=target, board_id=board_id, created_by=created_by,
            relationship=str(edge.get("relationship", "related")), label=str(edge.get("label", "")),
            style=str(edge.get("style", "solid")), direction=str(edge.get("direction", "forward")),
            routing=str(edge.get("routing", "straight")), color=str(edge.get("color", "default")),
            thickness=float(edge.get("thickness", 2)),
        )
    return get_board(board_id)


def render_board(board_id: str, format: str) -> tuple[str, str, str]:
    board = get_board(board_id); canvas, cards, edges = board["canvas"], board["cards"], board["edges"]; stem = _safe_id(canvas["name"])
    if format == "json":
        payload = {"schema_version": 2, "canvas": {"name": canvas["name"], "description": canvas["description"]}, "cards": cards, "edges": edges}
        return json.dumps(payload, ensure_ascii=False, indent=2), f"{stem}.json", "application/json"
    lines = ["flowchart LR"]; node_ids = {card["id"]: f"n{i}" for i, card in enumerate(cards)}
    for card in cards:
        title = card["title"].replace('"', "'").replace("\n", " ")
        text = f'{title}<br/><small>{card["kind"]}</small>'
        shape = {
            "condition": f'{{"{text}"}}',
            "terminator": f'(["{text}"])',
            "connector": f'(("{text}"))',
            "database": f'[("{text}")]',
            "data_store": f'[("{text}")]',
            "input_output": f'[/"{text}"/]',
        }.get(card["kind"], f'["{text}"]')
        lines.append(f'  {node_ids[card["id"]]}{shape}')
    for edge in edges:
        label = (edge.get("label") or edge.get("relationship") or "related").replace('"', "'")
        direction = edge.get("direction", "forward")
        if edge.get("style") in {"dashed", "dotted"}:
            arrow = {"none": "-.-", "forward": "-.->", "backward": "<-.-", "both": "<-.->"}[direction]
        else:
            arrow = {"none": "---", "forward": "-->", "backward": "<--", "both": "<-->"}[direction]
        lines.append(f'  {node_ids[edge["source_id"]]} {arrow}|"{label}"| {node_ids[edge["target_id"]]}')
    mermaid = "\n".join(lines) + "\n"
    if format == "mermaid": return mermaid, f"{stem}.mmd", "text/plain"
    if format != "markdown": raise ValueError("Format must be markdown, mermaid, or json")
    content = [f'# {canvas["name"]}', "", canvas["description"], "", "```mermaid", mermaid.rstrip(), "```", "", "## Components", ""]
    for card in cards:
        content.extend([f'### {card["title"]}', f'**Type:** {card["kind"]} · **Owner:** {card["created_by"]}', "", card["body"] or "_No details_", ""])
        if card.get("details"): content.extend(["```json", json.dumps(card["details"], ensure_ascii=False, indent=2), "```", ""])
    content.extend(["## Relationships", ""]); by_id = {card["id"]: card["title"] for card in cards}
    glyphs = {"none": "—", "forward": "→", "backward": "←", "both": "↔"}
    content.extend(f'- **{by_id.get(e["source_id"], "Unknown")}** —{e.get("relationship", "related")}{glyphs.get(e.get("direction", "forward"), "→")} **{by_id.get(e["target_id"], "Unknown")}**{f": {e["label"]}" if e.get("label") else ""}' for e in edges)
    return "\n".join(content).strip() + "\n", f"{stem}.md", "text/markdown"


def export_board(board_id: str, format: str, destination: str, created_by: str = "user") -> dict[str, Any]:
    content, filename, mime = render_board(board_id, format); content = scrub(content)
    if destination == "download": return {"destination": destination, "filename": filename, "mime": mime, "content": content}
    if destination == "notes":
        if format != "markdown": raise ValueError("Notes export uses Markdown format")
        from app.backend.services.notes import create_note
        try: note = create_note(Path(filename).stem, content)
        except Exception: note = create_note(f"{Path(filename).stem}-{datetime.now().strftime('%H%M%S')}", content)
        return {"destination": destination, "path": note["path"], "reference": f'@note:"{note["title"]}"'}
    if destination == "workspace":
        root = settings.project_root / "app" / "projects" / "designs"; root.mkdir(parents=True, exist_ok=True); path = root / filename; path.write_text(content, encoding="utf-8")
        return {"destination": destination, "path": str(path.relative_to(settings.project_root))}
    if destination == "artifact":
        root = settings.project_root / "data" / "generated" / "whiteboard"; root.mkdir(parents=True, exist_ok=True); path = root / filename; path.write_text(content, encoding="utf-8")
        from app.backend.services.artifacts import register_artifact
        artifact = register_artifact(path, source_agent=created_by, metadata={"whiteboard_id": board_id, "format": format})
        return {"destination": destination, "path": artifact["path"], "artifact_id": artifact["id"]}
    raise ValueError("Destination must be download, notes, workspace, or artifact")
