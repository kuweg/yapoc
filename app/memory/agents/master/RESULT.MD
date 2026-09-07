Chrome MCP UI inspection was blocked because Chrome DevTools MCP tools were not exposed to the document processor.

Verified:
- `http://localhost:8000` is reachable and returned `HTTP/1.1 200 OK` from Uvicorn.
- No application code was changed.

Artifacts:
- `app/projects/artifacts/chrome_mcp_inspection_unavailable.txt`
- `app/projects/artifacts/local_ui_http_headers.txt`

Without the MCP browser tools, no screenshot, DOM/accessibility snapshot, or visual UI/agent-graph review could be produced.