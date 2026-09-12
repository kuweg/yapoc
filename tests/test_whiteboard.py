import pytest


@pytest.fixture
def isolated_db(tmp_path):
    import threading
    import app.utils.db as db

    old_path, old_local = db._DB_PATH, db._local
    db._DB_PATH = tmp_path / "whiteboard.db"
    db._local = threading.local()
    db.init_schema()
    yield
    conn = getattr(db._local, "conn", None)
    if conn:
        conn.close()
    db._DB_PATH, db._local = old_path, old_local


def test_cards_connections_and_cascade(isolated_db):
    from app.utils.whiteboard import create_card, create_edge, delete_card, get_board

    first = create_card(kind="decision", title="Use SQLite", body="Shared across agents", created_by="planning")
    second = create_card(kind="task", title="Build the UI", created_by="builder", x=420, y=180)
    edge = create_edge(source_id=first["id"], target_id=second["id"], created_by="master")
    board = get_board()
    assert board["revision"] == 3
    assert [card["created_by"] for card in board["cards"]] == ["planning", "builder"]
    assert board["edges"][0]["id"] == edge["id"]

    assert delete_card(first["id"])
    assert get_board()["edges"] == []


def test_revision_prevents_lost_update(isolated_db):
    from app.utils.whiteboard import WhiteboardConflictError, create_card, update_card

    card = create_card(kind="note", title="Original")
    saved = update_card(card["id"], revision=card["revision"], changes={"title": "Changed"})
    assert saved and saved["revision"] == 2
    with pytest.raises(WhiteboardConflictError, match="changed elsewhere"):
        update_card(card["id"], revision=card["revision"], changes={"title": "Stale edit"})


def test_secret_is_redacted_before_persistence(isolated_db):
    from app.utils.whiteboard import create_card, get_board

    token = "ghp_abcdefghijklmnopqrstuvwxyz123456"
    create_card(kind="note", title="Credential", body=f"token={token}", details={"api_key": token})
    card = get_board()["cards"][0]
    body = card["body"]
    assert token not in body
    assert "[REDACTED]" in body
    assert token not in str(card["details"])
    assert card["details"]["api_key"] == "[REDACTED]"


def test_agent_tools_use_compact_json_and_identity(isolated_db, tmp_path):
    import json
    from app.utils.tools.whiteboard import WhiteboardAddCardTool, WhiteboardListTool

    agent_dir = tmp_path / "researcher"
    agent_dir.mkdir()
    result = __import__("asyncio").run(WhiteboardAddCardTool(agent_dir).execute(title="Finding", kind="note"))
    assert json.loads(result)["created_by"] == "researcher"
    listing = __import__("asyncio").run(WhiteboardListTool().execute(board_id="main"))
    assert "\n" not in listing
    assert json.loads(listing)["cards"][0]["title"] == "Finding"


def test_named_architecture_canvas_and_typed_relationships(isolated_db):
    from app.utils.whiteboard import apply_design, create_board, get_board, list_boards

    canvas = create_board("Checkout architecture", "How orders become payments", "planning")
    design = apply_design(
        canvas["id"],
        [
            {"key": "api", "kind": "api", "title": "Checkout API", "details": {"endpoint": "POST /checkout"}},
            {"key": "db", "kind": "database", "title": "Orders", "details": {"engine": "PostgreSQL"}},
            {"key": "events", "kind": "queue", "title": "Order events"},
        ],
        [
            {"source": "api", "target": "db", "relationship": "writes"},
            {"source": "api", "target": "events", "relationship": "emits", "style": "dashed"},
        ],
        "planning",
    )
    assert {card["kind"] for card in design["cards"]} == {"api", "database", "queue"}
    assert {edge["relationship"] for edge in design["edges"]} == {"writes", "emits"}
    assert design["cards"][0]["details"]["endpoint"] == "POST /checkout"
    assert any(board["id"] == canvas["id"] and board["card_count"] == 3 for board in list_boards())
    assert get_board("main")["cards"] == []


def test_portable_exports_and_workspace_destination(isolated_db, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.utils import whiteboard
    from app.utils.whiteboard import apply_design, create_board, export_board, render_board

    monkeypatch.setattr(whiteboard, "settings", SimpleNamespace(project_root=tmp_path))
    canvas = create_board("Event design")
    apply_design(canvas["id"], [{"key": "producer", "kind": "service", "title": "Producer"},
          {"key": "topic", "kind": "queue", "title": "Topic"}],
        [{"source": "producer", "target": "topic", "relationship": "emits"}], "master")
    markdown, markdown_name, _ = render_board(canvas["id"], "markdown")
    mermaid, _, _ = render_board(canvas["id"], "mermaid")
    payload, _, _ = render_board(canvas["id"], "json")
    assert "```mermaid" in markdown and "Producer" in markdown
    assert "emits" in mermaid
    assert __import__("json").loads(payload)["schema_version"] == 2
    exported = export_board(canvas["id"], "markdown", "workspace", "master")
    assert exported["path"].startswith("app/projects/designs/")
    assert (tmp_path / exported["path"]).is_file()

    import app.backend.services.notes as notes
    import app.backend.services.artifacts as artifacts
    monkeypatch.setattr(notes, "create_note", lambda title, content: {
        "path": f"app/projects/notes/{title}.md", "title": title, "content": content,
    })
    monkeypatch.setattr(artifacts, "register_artifact", lambda path, **kwargs: {
        "id": "artifact-1", "path": str(path.relative_to(tmp_path)), "metadata": kwargs.get("metadata"),
    })
    note = export_board(canvas["id"], "markdown", "notes", "master")
    artifact = export_board(canvas["id"], "json", "artifact", "master")
    assert note["reference"].startswith('@note:"event-design')
    assert artifact["artifact_id"] == "artifact-1"
    assert (tmp_path / artifact["path"]).is_file()


def test_default_canvas_cannot_be_deleted(isolated_db):
    from app.utils.whiteboard import delete_board
    with pytest.raises(ValueError, match="default canvas"):
        delete_board("main")


def test_logic_shapes_and_configurable_directed_edges(isolated_db):
    from app.utils.whiteboard import create_card, create_edge, get_board, render_board, update_edge

    condition = create_card(kind="condition", title="Payment accepted?")
    process = create_card(kind="process", title="Create order", x=420)
    edge = create_edge(
        source_id=condition["id"], target_id=process["id"], relationship="flows_to",
        label="yes", direction="both", routing="orthogonal", style="dotted",
        color="mint", thickness=4,
    )
    assert edge["direction"] == "both"
    assert edge["routing"] == "orthogonal"
    assert edge["thickness"] == 4

    saved = update_edge(edge["id"], revision=edge["revision"], changes={
        "direction": "backward", "routing": "curved", "style": "dashed",
        "color": "rose", "thickness": 3, "label": "retry",
    })
    assert saved and saved["revision"] == 2
    assert saved["direction"] == "backward"
    assert saved["label"] == "retry"
    assert {card["kind"] for card in get_board()["cards"]} == {"condition", "process"}
    mermaid, _, _ = render_board("main", "mermaid")
    assert "<-.-" in mermaid


def test_invalid_edge_configuration_is_refused(isolated_db):
    from app.utils.whiteboard import create_card, create_edge, update_edge

    first = create_card(kind="terminator", title="Start")
    second = create_card(kind="document", title="Request")
    with pytest.raises(ValueError, match="direction"):
        create_edge(source_id=first["id"], target_id=second["id"], direction="sideways")
    edge = create_edge(source_id=first["id"], target_id=second["id"])
    with pytest.raises(ValueError, match="routing"):
        update_edge(edge["id"], revision=1, changes={"routing": "spiral"})
