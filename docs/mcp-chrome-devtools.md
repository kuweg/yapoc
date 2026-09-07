# Chrome DevTools MCP Integration

YAPOC integrates [ChromeDevTools/chrome-devtools-mcp](https://github.com/ChromeDevTools/chrome-devtools-mcp)
as an external MCP server, giving agents DevTools-level browser debugging:
network request inspection, console message capture, performance tracing,
Lighthouse audits, and memory/heap snapshots — beyond the simple
click/fill/screenshot automation already available via Playwright MCP.

## How it works

YAPOC's MCP **host layer** (`app/utils/mcp/`) reads `mcp-servers.json` at
startup, spawns each enabled `stdio` server as a subprocess, and registers
its tools into `TOOL_REGISTRY` under namespaced keys:

```
mcp__<server_name>__<tool_name>
```

For chrome-devtools-mcp the server name is `chrome-devtools`, so its tools
appear as `mcp__chrome_devtools__*` (e.g. `mcp__chrome_devtools__navigate_page`).

## Configuration

### `mcp-servers.json` (project root)

```json
{
  "name": "chrome-devtools",
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "chrome-devtools-mcp@latest", "--headless", "--no-usage-statistics",
           "--isolated", "--executablePath", "${CHROME_PATH:-/usr/bin/chromium}"],
  "tools_allowlist": ["*"],
  "auth": "none",
  "timeout_s": 120,
  "enabled": true,
  "auto_reconnect": true
}
```

- `--executablePath` is **required** on this machine. chrome-devtools-mcp looks
  for Google Chrome at `/opt/google/chrome/chrome` and does not fall back to
  Chromium or download a browser; without it every tool call fails with
  `Could not find Google Chrome executable for channel 'stable'`. Verified
  against Chromium 151 driving the live YAPOC UI.
- `${CHROME_PATH:-/usr/bin/chromium}` is resolved by the config loader
  (`app/utils/mcp/config.py`), so setting `CHROME_PATH` overrides it on a
  machine where Chrome lives elsewhere.
- `--isolated` gives each run a throwaway profile, so state never leaks between
  verification runs.
- `npx -y chrome-devtools-mcp@latest` fetches and runs the latest release
  without a manual install (requires Node.js ≥ 22 and network access on
  first run).
- `--headless` runs Chrome without a visible window (autonomous use).
- `--no-usage-statistics` opts out of Google's telemetry (also disabled
  automatically when `CI` or `CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS` is set).

### Agent access (`app/config/agent-settings.json`)

The `mcp` agent is the single home for MCP tool execution. It is granted:

- `"mcp_servers": ["playwright", "context7", "chrome-devtools"]`
- A curated set of `mcp__chrome_devtools__*` tools (navigation, snapshot,
  screenshot, click/fill, evaluate_script, console/network inspection,
  performance tracing).

To grant another agent access, add `"chrome-devtools"` to its `mcp_servers`
list and the desired `mcp__chrome_devtools__*` names to its `tools` list.

## Available tools

| Category | Tools |
|---|---|
| Navigation | `navigate_page`, `new_page`, `list_pages`, `select_page`, `close_page`, `wait_for` |
| Input | `click`, `fill`, `fill_form`, `hover`, `press_key`, `type_text`, `drag`, `upload_file` |
| Inspection | `take_snapshot`, `take_screenshot`, `evaluate_script` |
| Network | `list_network_requests`, `get_network_request` |
| Console | `list_console_messages`, `get_console_message` |
| Performance | `performance_start_trace`, `performance_stop_trace`, `performance_analyze_insight`, `lighthouse_audit` |
| Memory | `take_heapsnapshot`, `get_heapsnapshot_summary`, `query_heapsnapshot_objects`, … |

The full reference lives in the upstream repo's
[`docs/tool-reference.md`](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/docs/tool-reference.md).

## Usage

Delegate browser-debugging work to the `mcp` agent (or spawn it directly):

```
delegate_task(agent="mcp", task="Navigate to http://localhost:8000, capture
the console messages and network requests, and report any errors.")
```

The `mcp` agent will use `mcp__chrome_devtools__navigate_page`, then
`mcp__chrome_devtools__list_console_messages` and
`mcp__chrome_devtools__list_network_requests` to surface runtime errors.

### When to use Chrome DevTools vs Playwright

- **Playwright MCP** (`mcp__playwright__*`): simple click/fill/snapshot
  automation and E2E UI verification.
- **Chrome DevTools MCP** (`mcp__chrome_devtools__*`): in-depth debugging —
  network traffic, console output, performance traces, Lighthouse audits,
  and heap/memory analysis.

## Prerequisites

- Node.js ≥ 22 with `npx` on `PATH`.
- Network access on first run (to fetch `chrome-devtools-mcp@latest`).
- Chrome or Chrome for Testing installed (the server launches its own
  headless instance by default; it can also connect to a running Chrome via
  `--browserUrl` / `--wsEndpoint` / `--autoConnect`).

## Security

- No secrets are stored in `mcp-servers.json` — auth is `none` and the entry
  carries no API keys or tokens.
- The server runs as a child process of YAPOC and is torn down on backend
  shutdown (see `MCPHostManager.disconnect()` in the lifespan).
- Tool access is gated per-agent via `mcp_servers` + `tools` allowlists.
