"""Tests for Workspace upload API routing and owner-scoped persistence."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.dashboard import ApiPrefixMiddleware
from app.backend.routers.uploads import router
from app.backend.services import uploads


def test_workspace_upload_api_prefix_lists_and_serves_uploaded_file(monkeypatch, tmp_path):
    """The packaged dashboard's /api prefix must reach the upload router."""
    monkeypatch.setattr(uploads, "_root", lambda: tmp_path / "uploads")
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(ApiPrefixMiddleware)
    client = TestClient(app)

    created = client.post(
        "/api/upload",
        files=[("files", ("workspace-note.txt", b"workspace content", "text/plain"))],
    )
    assert created.status_code == 200
    body = created.json()
    assert body["errors"] == []
    assert len(body["files"]) == 1
    file_id = body["files"][0]["id"]

    listed = client.get("/api/upload")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["files"]] == [file_id]

    served = client.get(f"/api/upload/{file_id}?inline=1")
    assert served.status_code == 200
    assert served.content == b"workspace content"
