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
    create_card(kind="note", title="Credential", body=f"token={token}")
    body = get_board()["cards"][0]["body"]
    assert token not in body
    assert "[REDACTED]" in body


def test_agent_tools_use_compact_json_and_identity(isolated_db, tmp_path):
    import json
    from app.utils.tools.whiteboard import WhiteboardAddCardTool, WhiteboardListTool

    agent_dir = tmp_path / "researcher"
    agent_dir.mkdir()
    result = __import__("asyncio").run(WhiteboardAddCardTool(agent_dir).execute(title="Finding", kind="note"))
    assert json.loads(result)["created_by"] == "researcher"
    listing = __import__("asyncio").run(WhiteboardListTool().execute())
    assert "\n" not in listing
    assert json.loads(listing)["cards"][0]["title"] == "Finding"
