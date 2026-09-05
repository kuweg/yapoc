"""Type definitions for the YAPOC MCP host layer.

Holds only pure-Python dataclasses with zero third-party imports so this
module always imports cleanly, even when the optional ``mcp`` SDK is not
installed.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MCPServerConfig:
    """Per-server configuration read from ``mcp-servers.json``.

    Mirrors the schema in ``docs/mcp-integration-design.md`` section 6.
    All fields carry defaults so partially-populated server entries still
    validate.
    """

    name: str = ""
    transport: str = "stdio"  # "stdio" | "sse" | "websocket"
    command: str = ""  # required for stdio transport
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""  # required for sse/websocket transport
    tools_allowlist: list[str] = field(default_factory=lambda: ["*"])
    resources_allowlist: list[str] = field(default_factory=lambda: ["*"])
    auth: str = "none"  # "none" | "api_key" | "token"
    api_key: str = ""
    token: str = ""
    timeout_s: int = 30
    enabled: bool = True
    auto_reconnect: bool = True


@dataclass
class MCPConfig:
    """Top-level wrapper around the list of MCP server definitions."""

    mcp_servers: list[MCPServerConfig] = field(default_factory=list)
