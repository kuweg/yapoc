"""MCP bridge plugin — makes external MCP server tools assignable to agents.

External MCP servers (defined in ``mcp-servers.json``) are connected by the
MCP host layer (``app/utils/mcp/``) and their tools are registered into
``TOOL_REGISTRY`` under ``mcp__<server>__<tool>`` by
``register_server_tools()``.

That same function ALSO registers a namespaced alias
``plugin:mcp:<server>__<tool>`` for each tool (see ``app/utils/mcp/registry.py``),
so assigning this plugin to an agent via the plugin assignment UI — which
writes the wildcard grant ``plugin:mcp:*`` into the agent's CONFIG.yaml
``tools:`` block — resolves to every connected MCP server tool.

This plugin file exists so the "MCP Bridge" appears in the Plugins tab (via
``plugins/mcp_bridge.yaml``) and can be assigned like any other plugin. It
performs no registration of its own: the alias registration lives in the MCP
registry layer, which runs after the MCP host connects at startup.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Namespace under which MCP tools are exposed for plugin assignment. Keep in
# sync with the alias key registered in app/utils/mcp/registry.py.
PLUGIN_NAMESPACE = "plugin:mcp"
