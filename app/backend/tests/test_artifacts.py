"""Tests for the durable generated-artifact registry API."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.dashboard import ApiPrefixMiddleware
from app.backend.routers.artifacts import router
from app.backend.services import artifacts


@pytest.fixture()
def artifact_env(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    generated = project_root / "data" / "generated"
    generated.mkdir(parents=True)
    (generated / "document_processor_test.md").write_text("# YAPOC\n", encoding="utf-8")
    monkeypatch.setattr(artifacts, "_project_root", lambda: project_root)
    yield generated


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_backfill_indexes_existing_generated_files(artifact_env):
    assert artifacts.backfill_scan() >= 1
    records = artifacts.list_artifacts()
    record = next(item for item in records if item["name"] == "document_processor_test.md")
    assert record["kind"] == "text"


def test_list_returns_public_expected_keys(client, artifact_env):
    response = client.get("/artifacts")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 1
    assert {"id", "name", "path", "kind", "sha256", "version", "metadata"} <= set(body["artifacts"][0])


def test_api_prefix_preserves_query_string_for_artifact_filters(artifact_env):
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(ApiPrefixMiddleware)
    response = TestClient(app).get("/api/artifacts?source_agent=backfill")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 1
    assert all(record["source_agent"] == "backfill" for record in body["artifacts"])


def test_register_new_file_and_versioning(client, artifact_env):
    path = artifact_env / "versioned.md"
    path.write_text("first", encoding="utf-8")
    relative = str(path.relative_to(artifact_env.parent.parent))
    first = client.post("/artifacts/register", json={"path": relative, "source_agent": "tester"})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["source_agent"] == "tester"
    assert first_body["version"] == 1

    path.write_text("second", encoding="utf-8")
    second = client.post("/artifacts/register", json={"path": relative, "source_agent": "tester"})
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["id"] == first_body["id"]
    assert second_body["version"] == 2
    assert len(second_body["versions"]) == 2


def test_register_traversal_rejected(client, artifact_env):
    response = client.post("/artifacts/register", json={"path": "../app/config/settings.py"})
    assert response.status_code == 400


def test_detail_versions_and_missing(client, artifact_env):
    path = artifact_env / "detail.md"
    path.write_text("detail", encoding="utf-8")
    record = client.post("/artifacts/register", json={"path": str(path.relative_to(artifact_env.parent.parent))}).json()

    detail = client.get(f"/artifacts/{record['id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == record["id"]

    versions = client.get(f"/artifacts/{record['id']}/versions")
    assert versions.status_code == 200
    assert len(versions.json()["versions"]) == 1

    assert client.get("/artifacts/missing").status_code == 404
