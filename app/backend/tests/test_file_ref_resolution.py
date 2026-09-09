"""Tests for @file:<id> reference resolution.

A full `@file:<hex32>` reference pasted directly into chat never populates the
frontend's upload list (the autocomplete only fires for `@file <name>`), so the
backend must resolve such references from the prompt text itself as a fallback.
"""
from __future__ import annotations

from app.backend.services import uploads


def test_resolve_file_refs_in_text_by_id(monkeypatch, tmp_path):
    monkeypatch.setattr(uploads, "_root", lambda: tmp_path / "uploads")
    rec = uploads.store_upload("resume.pdf", b"%PDF-1.4 resume bytes", owner="local")
    file_id = rec["id"]

    ids = uploads.resolve_file_refs_in_text(
        f"Please review @file:{file_id} and summarize", owner="local"
    )
    assert ids == [file_id]


def test_resolve_file_refs_in_text_by_name(monkeypatch, tmp_path):
    monkeypatch.setattr(uploads, "_root", lambda: tmp_path / "uploads")
    rec = uploads.store_upload("resume.pdf", b"%PDF-1.4 resume bytes", owner="local")

    ids = uploads.resolve_file_refs_in_text("look at @file:resume.pdf now", owner="local")
    assert ids == [rec["id"]]


def test_resolve_file_refs_dedupes(monkeypatch, tmp_path):
    monkeypatch.setattr(uploads, "_root", lambda: tmp_path / "uploads")
    rec = uploads.store_upload("resume.pdf", b"%PDF-1.4 resume bytes", owner="local")
    file_id = rec["id"]

    ids = uploads.resolve_file_refs_in_text(
        f"see @file:{file_id} and again @file:{file_id}", owner="local"
    )
    assert ids == [file_id]


def test_resolve_file_refs_unknown_id_ignored(monkeypatch, tmp_path):
    monkeypatch.setattr(uploads, "_root", lambda: tmp_path / "uploads")
    ids = uploads.resolve_file_refs_in_text(
        "review @file:deadbeefdeadbeefdeadbeefdeadbeef", owner="local"
    )
    assert ids == []


def test_resolve_file_refs_no_refs(monkeypatch, tmp_path):
    monkeypatch.setattr(uploads, "_root", lambda: tmp_path / "uploads")
    ids = uploads.resolve_file_refs_in_text("just a normal message", owner="local")
    assert ids == []
