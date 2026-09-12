import asyncio
import socket

import pytest

from app.backend.routers import link_previews


def test_public_target_rejects_private_and_credentials():
    addresses = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80)),
    ]
    with pytest.raises(ValueError, match="Public addresses"):
        link_previews.validate_target("http://example.test/", addresses)
    with pytest.raises(ValueError, match="Unsupported URL"):
        link_previews.validate_target("https://user:secret@example.test/", addresses)
    with pytest.raises(ValueError, match="Unsupported port"):
        link_previews.validate_target("https://example.test:8443/", addresses)


def test_public_target_rejects_mixed_dns_answers():
    addresses = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.4", 443)),
    ]
    with pytest.raises(ValueError, match="Public addresses"):
        link_previews.validate_target("https://example.test/", addresses)


def test_metadata_parses_open_graph_and_resolves_image(monkeypatch):
    page = b'''<html><head><title>Fallback</title>
        <meta property="og:title" content="YAPOC page">
        <meta name="description" content="A useful preview">
        <meta property="og:image" content="/cover.png"></head></html>'''
    async def fetch(url, limit):
        return "https://example.test/docs/start", "text/html", page

    monkeypatch.setattr(link_previews, "fetch_public", fetch)
    assert asyncio.run(link_previews.metadata("https://example.test")) == {
        "title": "YAPOC page",
        "description": "A useful preview",
        "image": "https://example.test/cover.png",
    }


def test_preview_failure_is_safe_and_cached(monkeypatch):
    link_previews._cache.clear()
    calls = 0

    async def fail(_url):
        nonlocal calls
        calls += 1
        raise OSError("secret upstream detail")

    monkeypatch.setattr(link_previews, "metadata", fail)
    assert asyncio.run(link_previews.preview("https://example.test")) == {}
    assert asyncio.run(link_previews.preview("https://example.test")) == {}
    assert calls == 1
