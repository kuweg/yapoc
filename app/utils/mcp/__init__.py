"""YAPOC MCP host layer.

Public exports: the config types and loaders, the :class:`MCPHostManager`
singleton, and the tool-registration helpers used to fuse external MCP
server tools into YAPOC's ``TOOL_REGISTRY``.

Importing this package never requires the optional ``mcp`` SDK — the SDK
is only imported lazily inside methods that actually connect.
"""
from __future__ import annotations

from .config import load_mcp_config
from .host import MCPHostManager, mcp_host_manager
from .registry import MCPToolWrapper, register_server_tools, unregister_server_tools
from .types import MCPServerConfig, MCPConfig

__all__ = [
    "MCPHostManager",
    "MCPToolWrapper",
    "register_server_tools",
    "unregister_server_tools",
    "load_mcp_config",
    "MCPConfig",
    "MCPServerConfig",
    "mcp_host_manager",
]
