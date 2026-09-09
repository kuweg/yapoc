from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app.backend.routers.drive_oauth import (
    _summarize_content,
    oauth_connect,
    oauth_disconnect,
    oauth_status,
)
from app.utils.tools import TOOL_REGISTRY
from app.utils.tools.plugin_loader import (
    load_plugin_config,
    load_plugin_manifests,
    load_plugins,
    save_plugin_config,
)
from plugins.drive.drive import (
    DriveCreateDocTool,
    DriveCreateFolderTool,
    DriveCreateSheetTool,
    DriveDeleteTool,
    DriveDownloadTool,
    DriveExportTool,
    DriveListTool,
    DriveMoveTool,
    DriveReadDocTool,
    DriveReadSheetTool,
    DriveRenameTool,
    DriveSearchTool,
    DriveUploadTool,
    _get_access_token,
    _summarize_ipynb,
    _summarize_text,
)


DRIVE_TOOL_NAMES = [
    "drive_list",
    "drive_search",
    "drive_upload",
    "drive_create_folder",
    "drive_rename",
    "drive_move",
    "drive_delete",
    "drive_read_doc",
    "drive_read_sheet",
    "drive_create_doc",
    "drive_create_sheet",
    "drive_export",
    "drive_download",
]


DRIVE_TOOL_CLASSES = [
    DriveListTool,
    DriveSearchTool,
    DriveUploadTool,
    DriveCreateFolderTool,
    DriveRenameTool,
    DriveMoveTool,
    DriveDeleteTool,
    DriveReadDocTool,
    DriveReadSheetTool,
    DriveCreateDocTool,
    DriveCreateSheetTool,
    DriveExportTool,
    DriveDownloadTool,
]


def test_drive_plugin_manifest_loads() -> None:
    manifests = load_plugin_manifests()
    assert "drive" in manifests

    drive_manifest = manifests["drive"]
    schema = drive_manifest.get("config_schema", {})

    for key in ["client_id", "client_secret", "refresh_token", "access_token", "user_email"]:
        assert key in schema

    tools = drive_manifest.get("tools", [])
    assert sorted(tools) == sorted(DRIVE_TOOL_NAMES)


def test_drive_tools_register() -> None:
    load_plugins()
    for name in DRIVE_TOOL_NAMES:
        assert name in TOOL_REGISTRY


def test_drive_tools_have_schema() -> None:
    for cls in DRIVE_TOOL_CLASSES:
        tool = cls()
        assert isinstance(tool.name, str) and tool.name.strip()
        assert isinstance(tool.description, str) and tool.description.strip()
        assert isinstance(tool.input_schema, dict) and tool.input_schema
        assert tool.input_schema.get("type") == "object"


def test_get_access_token_requires_config() -> None:
    original_cfg = load_plugin_config("drive")
    try:
        save_plugin_config("drive", {})
        with pytest.raises(RuntimeError):
            _get_access_token()
    finally:
        save_plugin_config("drive", original_cfg)


@pytest.mark.asyncio
async def test_oauth_status_endpoint_shape() -> None:
    result = await oauth_status()

    expected_keys = {
        "connected",
        "user_email",
        "has_client_id",
        "has_client_secret",
        "has_refresh_token",
    }
    assert expected_keys.issubset(result.keys())

    assert isinstance(result["connected"], bool)
    assert isinstance(result["has_client_secret"], bool)

    for value in result.values():
        assert isinstance(value, (bool, str, type(None)))
        if isinstance(value, str):
            lower = value.lower()
            assert "secret" not in lower
            assert "token" not in lower


@pytest.mark.asyncio
async def test_oauth_connect_requires_credentials() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await oauth_connect({"client_id": "", "client_secret": ""})
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_oauth_disconnect_clears_tokens() -> None:
    original_cfg = load_plugin_config("drive")
    try:
        save_plugin_config(
            "drive",
            {"refresh_token": "x", "access_token": "y", "user_email": "a@b.c"},
        )

        await oauth_disconnect()
        cfg = load_plugin_config("drive")

        assert "refresh_token" not in cfg
        assert "access_token" not in cfg
        assert "user_email" not in cfg
    finally:
        save_plugin_config("drive", original_cfg)


def test_summarize_ipynb_structure() -> None:
    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}},
        "cells": [
            {"cell_type": "markdown", "source": ["# Title\n", "Some markdown text"]},
            {"cell_type": "code", "source": ["import os\n", "print(os.environ)"], "outputs": [{"output_type": "stream", "text": ["SECRET_VALUE=abc123\n"]}]},
            {"cell_type": "code", "source": ["x = 1"], "outputs": []},
        ],
    }
    summary = _summarize_ipynb(nb)
    assert "nbformat: 4.5" in summary
    assert "kernelspec:" in summary
    assert "python3" in summary
    assert "markdown=1" in summary
    assert "code=2" in summary
    assert "[markdown]" in summary
    assert "[code]" in summary
    # outputs must not leak data
    assert "SECRET_VALUE" not in summary
    assert "abc123" not in summary
    assert "outputs: 1 (stream)" in summary


def test_summarize_ipynb_no_secret_leak() -> None:
    nb = {
        "nbformat": 4,
        "nbformat_minor": 0,
        "metadata": {"kernelspec": {"name": "python3"}},
        "cells": [
            {"cell_type": "code", "source": ["password = 'hunter2'"], "outputs": [{"output_type": "execute_result", "data": {"text/plain": ["hunter2"]}}]},
        ],
    }
    summary = _summarize_ipynb(nb)
    # source preview is allowed (it's the user's own code), but output data must not appear
    assert "hunter2" in summary  # from source preview
    assert "execute_result" in summary  # output type is listed
    # ensure output data dict is not dumped
    assert "text/plain" not in summary


def test_summarize_text_truncates() -> None:
    long_text = "a" * 10000
    summary = _summarize_text(long_text)
    assert len(summary) < 10000
    assert "(truncated)" in summary


def test_summarize_content_notebook() -> None:
    from plugins.drive.drive import _summarize_ipynb, _summarize_text
    nb = {"nbformat": 4, "nbformat_minor": 0, "metadata": {}, "cells": [{"cell_type": "code", "source": ["print(1)"], "outputs": []}]}
    content = json.dumps(nb).encode("utf-8")
    result = _summarize_content(content, "application/x-ipynb+json", _summarize_ipynb, _summarize_text)
    assert "nbformat: 4.0" in result
    assert "[code]" in result


def test_summarize_content_binary() -> None:
    from plugins.drive.drive import _summarize_ipynb, _summarize_text
    content = b"\x00\x01\x02\x03\x04"
    result = _summarize_content(content, "application/octet-stream", _summarize_ipynb, _summarize_text)
    assert "Binary file" in result
    assert "5 bytes" in result


def test_summarize_content_text() -> None:
    from plugins.drive.drive import _summarize_ipynb, _summarize_text
    content = b"hello world\nthis is a text file"
    result = _summarize_content(content, "text/plain", _summarize_ipynb, _summarize_text)
    assert "hello world" in result


@pytest.mark.asyncio
async def test_drive_download_tool_notebook(monkeypatch) -> None:
    """DriveDownloadTool.execute must summarize .ipynb content without leaking outputs."""
    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}},
        "cells": [
            {"cell_type": "markdown", "source": ["# Title\n", "Some markdown"]},
            {"cell_type": "code", "source": ["print('hi')"], "outputs": [{"output_type": "stream", "text": ["SECRET=abc\n"]}]},
        ],
    }
    raw = json.dumps(nb).encode("utf-8")

    import plugins.drive.drive as drive_mod

    monkeypatch.setattr(drive_mod, "_download_file", lambda file_id: raw)
    tool = DriveDownloadTool()
    result = await tool.execute(file_id="abc123", mime_type="application/x-ipynb+json")

    assert "nbformat: 4.5" in result
    assert "[markdown]" in result
    assert "[code]" in result
    assert "SECRET" not in result
    assert "abc" not in result


@pytest.mark.asyncio
async def test_drive_download_tool_notebook_by_content(monkeypatch) -> None:
    """Notebook detection must work even when mime_type is empty/unknown."""
    nb = {"nbformat": 4, "nbformat_minor": 0, "metadata": {}, "cells": [{"cell_type": "code", "source": ["x = 1"], "outputs": []}]}
    raw = json.dumps(nb).encode("utf-8")

    import plugins.drive.drive as drive_mod

    monkeypatch.setattr(drive_mod, "_download_file", lambda file_id: raw)
    tool = DriveDownloadTool()
    result = await tool.execute(file_id="abc123", mime_type="")

    assert "nbformat: 4.0" in result
    assert "[code]" in result


@pytest.mark.asyncio
async def test_drive_download_tool_binary(monkeypatch) -> None:
    """Binary content must be reported by size, not decoded."""
    import plugins.drive.drive as drive_mod

    monkeypatch.setattr(drive_mod, "_download_file", lambda file_id: b"\x00\x01\x02\x03\x04")
    tool = DriveDownloadTool()
    result = await tool.execute(file_id="abc123", mime_type="application/octet-stream")

    assert "Binary file" in result
    assert "5 bytes" in result


@pytest.mark.asyncio
async def test_drive_download_tool_text(monkeypatch) -> None:
    """Plain text content must return a truncated preview."""
    import plugins.drive.drive as drive_mod

    monkeypatch.setattr(drive_mod, "_download_file", lambda file_id: b"hello world\nthis is text")
    tool = DriveDownloadTool()
    result = await tool.execute(file_id="abc123", mime_type="text/plain")

    assert "hello world" in result


@pytest.mark.asyncio
async def test_drive_download_tool_requires_file_id() -> None:
    tool = DriveDownloadTool()
    result = await tool.execute(file_id="")
    assert result == "file_id is required"
