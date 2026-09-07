I'll start by researching the existing MCP architecture and the chrome-devtools-mcp repository before deciding on an integration pattern.I see there's an `mcp-servers.json` file already. Let me inspect it and the broader MCP-related config.There's a `docs/mcp-integration-design.md`. Let me read it, plus find where `mcp-servers.json` is consumed in the codebase.The `yapoc` module isn't available in this environment. Let me use grep via a different approach — check how `mcp-servers.json` is actually consumed in code.The MCP host layer already exists. Let me read the actual implementation files.Now I understand the architecture well. The MCP host layer is fully implemented. Let me check how it's wired into the backend startup (main.py lifespan) and how `build_tools` resolves `mcp__*` names.I now have a complete understanding of the architecture. The MCP host layer is fully implemented and wired. The integration pattern is clear: **add a new stdio server entry to `mcp-servers.json`** for chrome-devtools-mcp, which the existing `MCPHostManager` will spawn and register as `mcp__chrome_devtools__*` tools.

Let me research the chrome-devtools-mcp repository to get the exact command/args and tool names.I now have full understanding. The pattern is clear and well-established: the `mcp` agent already has `mcp_servers: ["playwright", "context7"]` and `mcp__*` tools. I need to:

1. Add a `chrome-devtools` server entry to `mcp-servers.json`
2. Add `chrome-devtools` to the `mcp` agent's `mcp_servers` list (and optionally grant specific `mcp__chrome_devtools__*` tools)
3. Document usage

Let me verify the exact chrome-devtools-mcp package name and command. The official package is `chrome-devtools-mcp` published by ChromeDevTools, run via `npx chrome-devtools-mcp@latest`. Let me confirm the tool names it exposes.I have everything I need. The integration pattern is clear and consistent with the existing Playwright/context7 integration. Now let me check the docs directory for any existing MCP usage doc and check the `.env.example` for MCP-related vars.I now have complete understanding. The `.env.example` doesn't have MCP vars (they're in settings.py with defaults). The integration is straightforward and follows the exact established pattern.

Let me verify the exact chrome-devtools-mcp package details. The official package is `chrome-devtools-mcp` (npm), run via `npx chrome-devtools-mcp@latest`. It exposes tools like `navigate_page`, `take_screenshot`, `take_snapshot`, `click`, `fill`, `evaluate_script`, `list_pages`, `new_page`, `select_page`, `list_console_messages`, `list_network_requests`, `get_network_request`, `performance_start_trace`, `performance_stop_trace`, `performance_analyze_insight`, etc.

Let me check the existing tests directory to understand test conventions for MCP.The `mcp` SDK is installed and `npx`/`node` are available. Now I have everything I need to implement. Let me check the existing test for agent_settings to understand how config tests are structured, and check if there's a test for the MCP config loader.I have complete understanding now. There are no existing MCP tests. My plan is clear. Let me now implement the integration. This is a well-defined, mechanical set of changes that I can do directly (config edits + docs + a test), following the exact established pattern.

The changes are:
1. **`mcp-servers.json`** — add `chrome-devtools` stdio server entry
2. **`app/config/agent-settings.json`** — add `chrome-devtools` to `mcp` agent's `mcp_servers` + grant specific `mcp__chrome_devtools__*` tools
3. **`app/agents/mcp/CONFIG.yaml`** — mirror the tool additions (fallback)
4. **`docs/mcp-usage.md`** — new usage doc (or extend existing)
5. **`tests/test_mcp_config.py`** — test that the config loader parses the chrome-devtools entry correctly
6. **`.env.example`** — document optional chrome channel var

Let me first verify the exact tool names chrome-devtools-mcp exposes by checking its npm package metadata (without installing it globally).The package is `chrome-devtools-mcp` v1.8.0, with bin `chrome-devtools-mcp`. The standard invocation is `npx chrome-devtools-mcp@latest`. Let me verify the tool names it exposes by checking the package's README/tool definitions via npm.I now have complete, authoritative information. The tool names are confirmed. The standard invocation is `npx -y chrome-devtools-mcp@latest`, and I should add `--headless` and `--no-usage-statistics` for autonomous/headless use (consistent with the existing Playwright entry which uses `--headless`).

Key facts:
- Package: `chrome-devtools-mcp` (bin `chrome-devtools-mcp`)
- Command: `npx -y chrome-devtools-mcp@latest`
- Tools (namespaced as `mcp__chrome_devtools__<tool>`): `navigate_page`, `take_screenshot`, `take_snapshot`, `click`, `fill`, `fill_form`, `evaluate_script`, `list_pages`, `new_page`, `select_page`, `close_page`, `wait_for`, `list_console_messages`, `list_network_requests`, `get_network_request`, `performance_start_trace`, `performance_stop_trace`, `performance_analyze_insight`, etc.

Now let me implement. I'll do the config changes directly (they're mechanical and well-understood), then delegate the test + docs to Builder. Actually, given the simplicity and my clear understanding, I'll do all changes directly and delegate only verification/build to Builder.

Let me start with the core config changes.Now update the `mcp` agent in agent-settings.json to add `chrome-devtools` to `mcp_servers` and grant the core tools:Now mirror the tool additions in the `mcp` agent's CONFIG.yaml (fallback source):Now let me verify the JSON is still valid and check the `mcp` agent's PROMPT.MD to see if it documents its tools (so I can update it too):I'll update the PROMPT.MD to document the new Chrome DevTools tools:Now update the workflow section to mention Chrome DevTools:Now let me write the test for the config loader and the usage documentation. First, let me write the test:Now let me write the usage documentation. Let me check if there's an existing docs/mcp-usage.md referenced in the design doc (it was planned but may not exist):Now let me run the test to verify the config loader works correctly:All 3 tests pass. Now let me verify the full integration end-to-end by actually connecting to the chrome-devtools-mcp server via the host manager (to confirm the command/args work and tools register). Let me do a quick smoke test that spawns the server and lists its tools:The end-to-end smoke test confirms the integration works: the server spawns via `npx -y chrome-devtools-mcp@latest --headless --no-usage-statistics` and exposes 29 tools. All the tool names I granted to the `mcp` agent are present and correct.

Note the server exposes 29 tools (the "slim" set is 3, full is ~50+; this is the default set). All my granted tool names are in the list. Let me verify my granted tool names all exist in the actual tool list:All 18 granted tool names are present in the server's actual tool list. The integration is complete and verified end-to-end.

Now let me do a final review of all my changes and verify the JSON files are still valid, then check if there's anything about the `.env.example` I should document (the `CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS` env var is already handled via the `--no-usage-statistics` flag, so no `.env` change is strictly needed).

Let me do a final verification of all changed files:Everything is in place. Let me run the full test suite quickly to ensure no regressions from my changes, and verify the Python files compile:All tests pass (3 new + 3 existing agent-settings tests). The integration is complete and verified.

Let me log the completion and record a memory entry, then notify parent.## Summary

Integrated ChromeDevTools `chrome-devtools-mcp` into YAPOC's MCP ecosystem end-to-end. After researching the existing architecture, I determined the correct pattern was to leverage YAPOC's already-implemented MCP host layer (`app/utils/mcp/`) by adding a stdio server entry — no new bridge code required.

## Subtasks
- **[done] Research & pattern selection** — Read `app/mcp_server/server.py`, `app/utils/mcp/{host,config,registry,types}.py`, `main.py` lifespan wiring, `mcp-servers.json`, and `docs/mcp-integration-design.md`. Confirmed the host layer already spawns stdio servers and namespaces tools as `mcp__<server>__<tool>`. Verified chrome-devtools-mcp package details (v1.8.0, `npx -y chrome-devtools-mcp@latest`, 29 default tools).
- **[done] Config integration** — Added `chrome-devtools` stdio entry to `mcp-servers.json`; granted 18 `mcp__chrome_devtools__*` tools + `chrome-devtools` in `mcp_servers` to the `mcp` agent (agent-settings.json + CONFIG.yaml).
- **[done] Prompt & docs** — Updated `app/agents/mcp/PROMPT.MD`; wrote `docs/mcp-chrome-devtools.md`.
- **[done] Tests** — Added `tests/test_mcp_config.py` (3 tests, all passing).
- **[done] Verification** — End-to-end smoke test spawned the server and confirmed all 18 granted tool names exist in the live 29-tool list; JSON valid; py_compile clean.

## Issues
None. Backend restart is required to pick up the new config (Python/config mutation) — flagged to master.