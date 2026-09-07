"""Tests for workspace file processing and artifact source linkage."""
from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.routers.artifacts import router as artifacts_router
from app.backend.routers.uploads import router as uploads_router
from app.backend.services import artifacts, uploads
from app.utils import db


def test_resolve_upload_by_ref_accepts_id_and_file_tokens(monkeypatch, tmp_path):
    monkeypatch.setattr(uploads, "_root", lambda: tmp_path / "uploads")
    record = uploads.store_upload("note.txt", b"hello", owner="local")

    assert uploads.resolve_upload_by_ref(record["id"], "local")["id"] == record["id"]
    assert uploads.resolve_upload_by_ref(f"@file:{record['id']}", "local")["id"] == record["id"]
    assert uploads.resolve_upload_by_ref("@file:note.txt", "local")["id"] == record["id"]


def test_process_upload_queues_source_linked_task(monkeypatch, tmp_path):
    monkeypatch.setattr(uploads, "_root", lambda: tmp_path / "uploads")
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "yapoc.db")
    db._local = __import__("threading").local()
    db.init_schema()
    app = FastAPI()
    app.include_router(uploads_router)
    client = TestClient(app)
    uploaded = client.post("/upload", files=[("files", ("note.txt", b"workspace text", "text/plain"))])
    file_id = uploaded.json()["files"][0]["id"]

    response = client.post(f"/upload/{file_id}/process", json={"action": "summarize"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["file_id"] == file_id
    assert body["action"] == "summarize"
    task = db.get_queued_task(body["task_id"])
    assert task is not None
    assert uploads.project_rel_path(uploads.resolve_upload(file_id, "local")) in task["prompt"]
    metadata = json.loads(task["metadata"])
    assert metadata["source_file_id"] == file_id
    assert metadata["action"] == "summarize"


def test_process_upload_missing_file_returns_404():
    app = FastAPI()
    app.include_router(uploads_router)
    response = TestClient(app).post("/upload/missing/process", json={"action": "extract"})
    assert response.status_code == 404


def test_link_artifact_source_updates_metadata(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    generated = project_root / "data" / "generated"
    generated.mkdir(parents=True)
    path = generated / "output.md"
    path.write_text("output", encoding="utf-8")
    monkeypatch.setattr(artifacts, "_project_root", lambda: project_root)
    record = artifacts.register_artifact("data/generated/output.md")
    app = FastAPI()
    app.include_router(artifacts_router)

    response = TestClient(app).post(
        f"/artifacts/{record['id']}/link-source",
        json={"source_file_id": "upload-1", "source_file_name": "input.txt"},
    )
    assert response.status_code == 200
    assert response.json()["metadata"] == {
        "source_file_id": "upload-1",
        "source_file_name": "input.txt",
    }
