"""YAPOC stdio MCP server — lets external MCP clients hire YAPOC.

This package contains a thin stdio MCP server (FastMCP) plus a small HTTP
client that talks to the already-running YAPOC backend over HTTP. It does not
re-implement master or the dispatcher — it just forwards tasks to the backend's
``POST /mcp/run`` endpoint and delegates everything else to master.
"""
