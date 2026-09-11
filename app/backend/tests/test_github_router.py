"""Tests for the read-only GitHub observation router.

These tests inject a fake httpx transport into ``gh.client`` so no real
network access is performed. The fake transport inspects ``request.url.path``
and returns canned JSON, mirroring the GitHub REST API shapes the router
consumes.
"""
from __future__ import annotations

import base64

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from fastapi.testclient import TestClient

from app.config import settings
from app.utils.github import client as gh
from app.backend.routers.github import router

REPO = "kuweg/yapoc"


class FakeTransport(httpx.AsyncBaseTransport):
    """Routes on ``request.url.path`` and returns canned GitHub JSON."""

    def __init__(self):
        self.calls = []

    async def handle_async_request(self, request):
        self.calls.append(str(request.url))
        path = request.url.path
        return self._response(path, request)

    def _response(self, path, request):
        body = self._body(path)
        if body is None:
            return httpx.Response(404, json={"message": "Not Found"}, request=request)
        return httpx.Response(200, json=body, request=request)

    def _body(self, path):
        repo = f"/repos/{REPO}"
        if path == repo:
            return {
                "full_name": REPO,
                "default_branch": "main",
                "name": "yapoc",
                "owner": {"login": "kuweg"},
            }
        if path == f"{repo}/git/trees/main":
            return {
                "sha": "tree_sha",
                "truncated": False,
                "tree": [
                    {"path": "a.py", "type": "blob", "sha": "x", "size": 10},
                    {"path": "src", "type": "tree", "sha": "y"},
                ],
            }
        if path == f"{repo}/contents/a.py":
            return {
                "path": "a.py",
                "sha": "x",
                "encoding": "base64",
                "content": base64.b64encode(b"print('hi')").decode(),
            }
        if path == f"{repo}/branches":
            return [{"name": "main", "commit": {"sha": "abc"}, "protected": True}]
        if path == f"{repo}/commits":
            return [{
                "sha": "abc",
                "commit": {"message": "msg", "author": {"name": "n", "date": "2026-01-01T00:00:00Z"}},
                "author": {"login": "u", "avatar_url": "a"},
                "html_url": "http://x",
            }]
        if path == f"{repo}/pulls":
            return [{
                "number": 1, "title": "t", "state": "open", "draft": False,
                "user": {"login": "u"}, "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z", "html_url": "http://x",
                "head": {"ref": "f", "sha": "s"}, "base": {"ref": "main"},
                "merged": False,
            }]
        if path == f"{repo}/issues":
            return [{
                "number": 1, "title": "t", "state": "open", "user": {"login": "u"},
                "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
                "html_url": "http://x", "labels": [{"name": "bug"}], "comments": 0,
            }]
        if path == f"{repo}/actions/runs":
            return {"workflow_runs": [{
                "id": 1, "name": "CI", "status": "completed", "conclusion": "success",
                "head_branch": "main", "head_sha": "s", "event": "push",
                "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
                "html_url": "http://x",
            }]}
        if path == f"{repo}/actions/runs/1/jobs":
            return {"jobs": [{
                "id": 1, "name": "build", "status": "completed", "conclusion": "success",
                "started_at": "2026-01-01T00:00:00Z", "completed_at": "2026-01-01T00:00:00Z",
                "steps": [{"name": "s", "status": "completed", "conclusion": "success"}],
            }]}
        if path == f"{repo}/releases":
            return [{"id": 1, "tag_name": "v1", "name": "v1",
                     "published_at": "2026-01-01T00:00:00Z", "html_url": "http://x",
                     "prerelease": False}]
        if path == f"{repo}/tags":
            return [{"name": "v1", "commit": {"sha": "abc"}}]
        if path == f"{repo}/pulls/1/files":
            return [{"filename": "a.py", "status": "modified", "additions": 1,
                     "deletions": 0, "changes": 1}]
        if path == f"{repo}/pulls/1/reviews":
            return [{"id": 1, "user": {"login": "u"}, "state": "APPROVED",
                     "submitted_at": "2026-01-01T00:00:00Z", "body": None}]
        if path == f"{repo}/pulls/1/comments":
            return [{"id": 1, "user": {"login": "u"}, "body": "c",
                     "created_at": "2026-01-01T00:00:00Z", "path": "a.py"}]
        if path == f"{repo}/commits/s/check-runs":
            return {"check_runs": [{"name": "CI", "status": "completed", "conclusion": "success"}]}
        if path == f"{repo}/issues/1/comments":
            return [{"id": 1, "user": {"login": "u"}, "body": "c",
                     "created_at": "2026-01-01T00:00:00Z"}]
        return None


@pytest.fixture()
def fake_transport():
    return FakeTransport()


@pytest.fixture()
def app_client(fake_transport, monkeypatch):
    # Configure settings so the repo is allowed and the client is enabled.
    monkeypatch.setattr(settings, "github_enabled", True)
    monkeypatch.setattr(settings, "github_token", SecretStr("github_pat_testtoken123"))
    monkeypatch.setattr(settings, "github_allowed_repos", REPO)
    monkeypatch.setattr(settings, "github_default_owner", "kuweg")
    monkeypatch.setattr(settings, "github_default_repo", "yapoc")
    monkeypatch.setattr(settings, "github_self_repo", REPO)
    monkeypatch.setattr(settings, "github_write_enabled", False)

    original = gh.client.transport
    gh.client.transport = fake_transport
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    gh.client.transport = original


class TestStatus:
    def test_status_200(self, app_client):
        resp = app_client.get("/integrations/github")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert "repositories" in data
        assert "write_enabled" in data


class TestRepo:
    def test_repo_200(self, app_client):
        resp = app_client.get("/integrations/github/repo")
        assert resp.status_code == 200
        assert resp.json()["full_name"] == REPO


class TestTree:
    def test_tree_200(self, app_client):
        resp = app_client.get("/integrations/github/tree", params={"sha": "main"})
        assert resp.status_code == 200
        tree = resp.json()["tree"]
        assert isinstance(tree, list)
        assert len(tree) == 2


class TestContents:
    def test_contents_decoded_200(self, app_client):
        resp = app_client.get("/integrations/github/contents", params={"path": "a.py"})
        assert resp.status_code == 200
        assert resp.json()["content"] == "print('hi')"


class TestBranches:
    def test_branches_200(self, app_client):
        resp = app_client.get("/integrations/github/branches")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "main"


class TestCommits:
    def test_commits_200(self, app_client):
        resp = app_client.get("/integrations/github/commits")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestPulls:
    def test_pulls_200(self, app_client):
        resp = app_client.get("/integrations/github/pulls")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_pull_files_200(self, app_client):
        resp = app_client.get("/integrations/github/pulls/1/files")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_pull_reviews_200(self, app_client):
        resp = app_client.get("/integrations/github/pulls/1/reviews")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_pull_comments_200(self, app_client):
        resp = app_client.get("/integrations/github/pulls/1/comments")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestChecks:
    def test_check_runs_200(self, app_client):
        resp = app_client.get("/integrations/github/commits/s/check-runs")
        assert resp.status_code == 200
        assert len(resp.json()["check_runs"]) == 1


class TestIssues:
    def test_issues_200(self, app_client):
        resp = app_client.get("/integrations/github/issues")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_issue_comments_200(self, app_client):
        resp = app_client.get("/integrations/github/issues/1/comments")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestActions:
    def test_workflow_runs_200(self, app_client):
        resp = app_client.get("/integrations/github/actions/runs")
        assert resp.status_code == 200
        assert len(resp.json()["workflow_runs"]) == 1

    def test_workflow_jobs_200(self, app_client):
        resp = app_client.get("/integrations/github/actions/runs/1/jobs")
        assert resp.status_code == 200
        assert len(resp.json()["jobs"]) == 1


class TestReleasesTags:
    def test_releases_200(self, app_client):
        resp = app_client.get("/integrations/github/releases")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_tags_200(self, app_client):
        resp = app_client.get("/integrations/github/tags")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestSecurity:
    def test_disallowed_repo_400(self, app_client):
        resp = app_client.get("/integrations/github/repo", params={"repository": "evil/other"})
        assert resp.status_code == 400

    def test_path_traversal_422(self, app_client):
        resp = app_client.get("/integrations/github/contents", params={"path": "../secret"})
        assert resp.status_code == 422

    def test_bad_ref_422(self, app_client):
        resp = app_client.get("/integrations/github/tree", params={"sha": "../.."})
        assert resp.status_code == 422
