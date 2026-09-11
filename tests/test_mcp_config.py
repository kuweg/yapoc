"""Tests for the MCP host config loader and chrome-devtools integration.

Verifies that ``mcp-servers.json`` parses correctly, that the
``chrome-devtools`` stdio server entry is present and well-formed, and that
the ``mcp`` agent is granted the expected ``mcp__chrome_devtools__*`` tools
and ``chrome-devtools`` in its ``mcp_servers`` allowlist.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from app.utils.mcp.config import load_mcp_config
from app.utils.mcp.types import MCPServerConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_agent_settings() -> dict:
    path = PROJECT_ROOT / "app" / "config" / "agent-settings.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_chrome_devtools_server_entry_parses() -> None:
    """The chrome-devtools stdio entry must parse with the expected shape."""
    config = load_mcp_config(PROJECT_ROOT)
    servers = {s.name: s for s in config.mcp_servers}
    assert "chrome-devtools" in servers, "chrome-devtools missing from mcp-servers.json"

    cd: MCPServerConfig = servers["chrome-devtools"]
    assert cd.transport == "stdio"
    assert cd.command == "npx"
    assert cd.args and cd.args[0] == "-y"
    assert any("chrome-devtools-mcp" in a for a in cd.args), "missing package arg"
    assert cd.enabled is True
    assert cd.auto_reconnect is True
    # No secrets: auth must be none and no api_key/token resolved.
    assert cd.auth == "none"
    assert cd.api_key == ""
    assert cd.token == ""


def test_mcp_agent_grants_chrome_devtools() -> None:
    """The mcp agent must allowlist chrome-devtools and its core tools."""
    settings = _load_agent_settings()
    mcp_agent = settings["agents"]["mcp"]
    assert "chrome-devtools" in mcp_agent.get("mcp_servers", [])

    tools = mcp_agent.get("tools", [])
    chrome_tools = [t for t in tools if t.startswith("mcp__chrome_devtools__")]
    assert chrome_tools, "no mcp__chrome_devtools__* tools granted to mcp agent"
    # Core navigation/debugging tools must be present.
    for expected in (
        "mcp__chrome_devtools__navigate_page",
        "mcp__chrome_devtools__take_snapshot",
        "mcp__chrome_devtools__take_screenshot",
        "mcp__chrome_devtools__evaluate_script",
        "mcp__chrome_devtools__list_network_requests",
    ):
        assert expected in tools, f"{expected} not granted to mcp agent"


def test_no_secrets_in_mcp_servers_json() -> None:
    """mcp-servers.json must not contain resolved secrets (only ${VAR} refs)."""
    raw = (PROJECT_ROOT / "mcp-servers.json").read_text(encoding="utf-8")
    # No literal bearer tokens / keys should be present.
    for forbidden in ("Bearer ", "sk-", "api_key="):
        assert forbidden not in raw, f"possible secret leak: {forbidden!r}"


def test_server_args_resolve_env_references(monkeypatch, tmp_path) -> None:
    """``args`` must go through ${VAR:-default} resolution like other fields.

    The chrome-devtools entry carries the browser path as
    ``${CHROME_PATH:-/usr/bin/chromium}`` so the same config works on a machine
    where Chrome lives elsewhere. Before this, args were passed through
    verbatim and the literal "${CHROME_PATH:-...}" string reached the browser
    launcher, which failed with an unhelpful "could not find executable".
    """
    cfg_path = tmp_path / "mcp-servers.json"
    cfg_path.write_text(
        json.dumps(
            {
                "mcp_servers": [
                    {
                        "name": "probe",
                        "transport": "stdio",
                        "command": "npx",
                        "args": ["--executablePath", "${PROBE_BROWSER:-/usr/bin/chromium}"],
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("PROBE_BROWSER", raising=False)
    servers = {s.name: s for s in load_mcp_config(tmp_path).mcp_servers}
    assert servers["probe"].args[-1] == "/usr/bin/chromium", "default not applied"

    monkeypatch.setenv("PROBE_BROWSER", "/opt/google/chrome/chrome")
    servers = {s.name: s for s in load_mcp_config(tmp_path).mcp_servers}
    assert servers["probe"].args[-1] == "/opt/google/chrome/chrome", "env not honoured"


def test_dotenv_resolution_does_not_pollute_restart_environment(monkeypatch, tmp_path) -> None:
    """A changed .env must not be shadowed by values copied into os.environ."""
    (tmp_path / "mcp-servers.json").write_text(
        json.dumps({"mcp_servers": [{
            "name": "probe",
            "command": "probe",
            "env": {"TOKEN": "${RESTART_TOKEN}"},
        }]}),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("RESTART_TOKEN=first\n", encoding="utf-8")
    monkeypatch.delenv("RESTART_TOKEN", raising=False)

    first = load_mcp_config(tmp_path).mcp_servers[0]
    assert first.env["TOKEN"] == "first"
    assert "RESTART_TOKEN" not in os.environ

    (tmp_path / ".env").write_text("RESTART_TOKEN=second\n", encoding="utf-8")
    second = load_mcp_config(tmp_path).mcp_servers[0]
    assert second.env["TOKEN"] == "second"
    assert "RESTART_TOKEN" not in os.environ


def test_chrome_devtools_pins_a_browser_path() -> None:
    """The entry must specify an executable path.

    chrome-devtools-mcp looks for Google Chrome at /opt/google/chrome/chrome and
    does NOT fall back to Chromium or download a browser. Without an explicit
    --executablePath every tool call fails with "Could not find Google Chrome
    executable for channel 'stable'".
    """
    config = load_mcp_config(PROJECT_ROOT)
    cd = {s.name: s for s in config.mcp_servers}["chrome-devtools"]
    assert "--executablePath" in cd.args, "no browser path pinned"
    path = cd.args[cd.args.index("--executablePath") + 1]
    assert path and not path.startswith("${"), f"unresolved path: {path}"
