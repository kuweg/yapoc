"""Tests for the file viewer endpoints: GET /files/download and GET /files/preview."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.routers.files import router

KNOWN_ARTIFACT = "data/generated/document_processor_test.md"


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestDownload:
    def test_download_known_artifact_200(self, client):
        resp = client.get("/files/download", params={"path": KNOWN_ARTIFACT})
        assert resp.status_code == 200
        assert "document_processor_test.md" in resp.headers.get("content-disposition", "")

    def test_download_inline_200(self, client):
        resp = client.get("/files/download", params={"path": KNOWN_ARTIFACT, "inline": 1})
        assert resp.status_code == 200

    def test_download_traversal_rejected(self, client):
        resp = client.get("/files/download", params={"path": "../app/config/settings.py"})
        assert resp.status_code == 400

    def test_download_sensitive_env_rejected(self, client):
        resp = client.get("/files/download", params={"path": ".env"})
        assert resp.status_code == 400

    def test_download_missing_404(self, client):
        resp = client.get("/files/download", params={"path": "data/generated/does_not_exist.md"})
        assert resp.status_code == 404


class TestPreview:
    def test_preview_text_kind_and_content(self, client):
        resp = client.get("/files/preview", params={"path": KNOWN_ARTIFACT})
        assert resp.status_code == 200
        data = resp.json()
        assert data["kind"] == "text"
        assert data["name"] == "document_processor_test.md"
        assert "content" in data and "# YAPOC" in data["content"]

    def test_preview_traversal_rejected(self, client):
        resp = client.get("/files/preview", params={"path": "../app/config/settings.py"})
        assert resp.status_code == 400

    def test_preview_missing_404(self, client):
        resp = client.get("/files/preview", params={"path": "data/generated/nope.md"})
        assert resp.status_code == 404
