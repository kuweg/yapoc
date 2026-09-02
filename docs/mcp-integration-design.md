# MCP (Model Context Protocol) Integration Design for YAPOC

> **Status:** Draft Design  
> **Date:** 2026-05-20  
> **MCP Protocol Version:** 2025-03-26  
> **Python SDK:** `mcp` (pip install mcp)

---

## 1. Executive Summary

YAPOC is an autonomous multi-agent system with 12+ agents, an adapter-based LLM abstraction layer, a tool registry, and a FastAPI backend. This document designs how YAPOC can integrate with the **Model Context Protocol (MCP)** — an open standard that lets LLM applications discover and invoke tools, access resources, and use prompt templates from external servers.

YAPOC will act in **two roles**:

1. **MCP Host** — YAPOC agents consume tools, resources, and prompts from external MCP servers (e.g., a GitHub MCP server, a database MCP server, a web scraping MCP server).
2. **MCP Server** — YAPOC exposes its own tools and agent capabilities to external MCP clients (e.g., VS Code extensions, other MCP hosts, custom scripts).

The design is **greenfield** — no existing MCP code in the project. A new `app/utils/mcp/` package will be created, with minimal changes to existing files.

**Key design decisions:**
- Use the official Python `mcp` SDK for protocol compliance
- MCP tools are wrapped as YAPOC `BaseTool` subclasses and injected into the tool registry at runtime
- MCP server definitions live in a dedicated `mcp-servers.json` file (not mixed into agent-settings.json)
- Per-agent MCP access control via agent-settings.json `mcp_servers` allowlist
- MCP Server exposes a curated subset of YAPOC tools via SSE transport

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        YAPOC (MCP Host + Server)                    │
│                                                                     │
│  ┌─────────────┐   ┌──────────────────┐   ┌─────────────────────┐  │
│  │ YAPOC Agents │──▶│  Tool Registry   │──▶│  MCP Host Layer     │  │
│  │ (master,     │   │  (TOOL_REGISTRY) │   │  (app/utils/mcp/    │  │
│  │  planning,   │   │                  │   │   host.py)          │  │
│  │  builder...) │   │  MCP Tools are   │   │                     │  │
│  │              │   │  BaseTool subs   │   │  Connects to ext.   │  │
│  │              │   │  registered at   │   │  MCP servers via    │  │
│  │              │   │  agent build     │   │  stdio / SSE / WS   │  │
│  └─────────────┘   └──────────────────┘   └──────────┬──────────┘  │
│                                                       │             │
│  ┌────────────────────────────────────────────────────┼──────────┐  │
│  │  MCP Server Layer (app/utils/mcp/server.py)        │          │  │
│  │                                                    │          │  │
│  │  Exposes YAPOC tools to external MCP clients       │          │  │
│  │  via SSE transport on /mcp/sse                     │          │  │
│  └────────────────────────────────────────────────────┘          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                              │                    │
                              │ stdio/SSE/WS       │ SSE
                              ▼                    ▼
              ┌─────────────────────────┐  ┌──────────────────┐
              │ External MCP Servers    │  │ MCP Clients      │
              │ (GitHub, DB, Browser,   │  │ (VS Code, CLI,   │
              │  Filesystem, etc.)      │  │  other hosts)    │
              └─────────────────────────┘  └──────────────────┘
```

### New Package Structure

```
app/utils/mcp/
├── __init__.py          # Public exports
├── host.py              # MCP host client — connects to external servers
├── server.py            # MCP server — exposes YAPOC to external clients
├── config.py            # Config loading and validation for mcp-servers.json
├── registry.py          # MCP tool registration into TOOL_REGISTRY
└── types.py             # Type definitions and dataclasses
```

---

## 3. MCP Host Design (Consuming External Servers)

### 3.1 Discovery and Connection

MCP server definitions are stored in a dedicated `mcp-servers.json` file at the project root:

```json
{
  "mcp_servers": [
    {
      "name": "github",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
      },
      "tools_allowlist": ["*"],
      "auth": "none",
      "timeout_s": 30,
      "enabled": true,
      "auto_reconnect": true
    },
    {
      "name": "filesystem",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/allowed/path"],
      "tools_allowlist": ["read", "list"],
      "auth": "none",
      "timeout_s": 15,
      "enabled": true,
      "auto_reconnect": true
    },
    {
      "name": "web-scraper",
      "transport": "sse",
      "url": "http://localhost:3100/mcp",
      "tools_allowlist": ["*"],
      "auth": "api_key",
      "api_key": "${SCRAPER_API_KEY}",
      "timeout_s": 60,
      "enabled": false,
      "auto_reconnect": true
    }
  ]
}
```

**Connection lifecycle:**
- On YAPOC startup (in `lifespan`), `MCPHostManager` reads `mcp-servers.json`, connects to all `enabled: true` servers
- For **stdio** transport: spawns the child process, connects stdin/stdout via the MCP SDK's `stdio_client`
- For **SSE** transport: connects via `sse_client` to the server URL
- For **WebSocket** transport: connects via `ws_client` (future, when MCP SDK supports it)
- Failed connections are logged but do not block startup — the server is marked `status: "disconnected"` and retried on a background interval
- `auto_reconnect: true` servers are retried every 30s with exponential backoff (1s, 2s, 4s, 8s, max 60s)

### 3.2 Tool Registration into TOOL_REGISTRY

When an MCP server connects, the host layer:

1. Calls `server.list_tools()` via the MCP SDK to get all available tools
2. For each tool whose name matches the server's `tools_allowlist`:
   - Creates a `MCPToolWrapper` (a `BaseTool` subclass) that proxies calls to the MCP server
   - Registers it in `TOOL_REGISTRY` with a namespaced key: `mcp__<server_name>__<tool_name>`
3. When the server disconnects, removes all its tools from the registry

```python
# app/utils/mcp/registry.py (conceptual)

class MCPToolWrapper(BaseTool):
    """Wraps an MCP server tool as a YAPOC BaseTool."""

    def __init__(self, server_name: str, mcp_tool: Tool, host_manager: "MCPHostManager"):
        self.name = f"mcp__{server_name}__{mcp_tool.name}"
        self.description = f"[MCP:{server_name}] {mcp_tool.description}"
        self.input_schema = mcp_tool.inputSchema
        self._server_name = server_name
        self._mcp_tool = mcp_tool
        self._host_manager = host_manager

    async def execute(self, **params) -> str:
        result = await self._host_manager.call_tool(
            server_name=self._server_name,
            tool_name=self._mcp_tool.name,
            arguments=params,
        )
        # Convert MCP content blocks to a flat string
        return "\n".join(
            block.text for block in result.content
            if hasattr(block, "text")
        )
```

**Tool name mapping:**

| MCP Tool Definition | YAPOC Tool Name |
|---|---|
| `name: "create_issue"` | `mcp__github__create_issue` |
| `name: "read_file"` | `mcp__filesystem__read_file` |

This namespacing prevents collisions between different MCP servers and with native YAPOC tools.

### 3.3 Resource Access

MCP resources (files, data blobs, etc.) are accessed via a dedicated `MCPResourceTool` that wraps `server.read_resource()`. Resources are not auto-registered — agents must explicitly request them via the tool.

```python
class MCPReadResourceTool(BaseTool):
    name = "mcp_read_resource"
    description = "Read a resource from an MCP server. Usage: mcp_read_resource(server='github', uri='repo://owner/repo/file.md')"
    input_schema = {
        "type": "object",
        "properties": {
            "server": {"type": "string", "description": "MCP server name"},
            "uri": {"type": "string", "description": "Resource URI"},
        },
        "required": ["server", "uri"],
    }
```

### 3.4 Prompt Templates

MCP prompts (reusable prompt templates from servers) are accessed via `MCPGetPromptTool`. They are not auto-injected into agent prompts — agents call this tool when they need a template.

### 3.5 Per-Agent MCP Access Control

Which MCP servers an agent can access is configured in `agent-settings.json`:

```json
{
  "agents": {
    "builder": {
      "adapter": "deepseek",
      "model": "deepseek-chat",
      "tools": ["...", "mcp__github__*", "mcp__filesystem__read_file"],
      "mcp_servers": ["github", "filesystem"],
      ...
    }
  }
}
```

- `tools` list: agents can be granted specific MCP tools by name or wildcard (`mcp__github__*`)
- `mcp_servers` list: restricts which MCP servers the agent can connect to (for dynamic tool discovery)
- If both are absent, the agent has no MCP access
- The `build_tools()` function in `app/utils/tools/__init__.py` is extended to resolve `mcp__*` tool names from the `MCPHostManager`

### 3.6 Error Handling

| Scenario | Behavior |
|---|---|
| MCP server unreachable on connect | Log warning, mark `status: "disconnected"`, retry with backoff |
| MCP server disconnects mid-session | All its tools return `"Error: MCP server '{name}' is disconnected"` |
| Tool call timeout | Raise `MCPTimeoutError` after `timeout_s`, agent sees error in tool result |
| Invalid tool arguments | MCP SDK returns validation error, propagated to agent |
| Server returns error content block | Wrapped into tool result string with `is_error=True` flag |

---

## 4. MCP Server Design (Exposing YAPOC)

### 4.1 What YAPOC Exposes

The MCP Server exposes a curated subset of YAPOC's capabilities:

**Tools exposed (configurable):**
- `file_read`, `file_list` — read-only file access
- `web_search`, `fetch_page` — web research
- `search_memory` — search agent memory across sessions
- `list_agents` — list active agents and their status
- `get_agent_status` — get a specific agent's status and recent output
- `list_sessions` — list recent chat sessions
- `get_session` — get session transcript/digest
- `run_task` — submit a task to a YAPOC agent (requires auth)

**Resources exposed:**
- `yapoc://agents/{name}/status` — agent STATUS.json content
- `yapoc://agents/{name}/memory` — agent MEMORY.MD content (last 50 lines)
- `yapoc://agents/{name}/notes` — agent NOTES.MD content
- `yapoc://sessions/{id}` — session transcript
- `yapoc://health` — system health overview

**Prompts exposed:**
- `agent_status` — template for checking agent health
- `system_overview` — template for getting a system summary

### 4.2 Authentication

MCP clients authenticate via:
1. **API Key** (default): Bearer token in `Authorization` header, validated against `MCP_API_KEY` in `.env`
2. **No auth** (dev mode): When `MCP_API_KEY` is empty, all connections are accepted (with a startup warning)

### 4.3 Transport

The MCP Server uses **SSE (Server-Sent Events)** transport, served on the existing FastAPI backend:

```
GET  /mcp/sse          → SSE endpoint (client connects here)
POST /mcp/messages     → Message endpoint (client sends JSON messages here)
```

This is added as a new router: `app/backend/routers/mcp.py`.

### 4.4 Server Lifecycle

- The MCP server starts in the FastAPI `lifespan` context manager
- On startup: creates `MCPServer` instance, registers tools/resources/prompts
- On shutdown: gracefully closes all active MCP sessions
- The server is stateless per-connection — each SSE connection gets its own session

### 4.5 Tool Translation (MCP → YAPOC)

When an MCP client calls a YAPOC tool:

1. MCP SDK receives the `tools/call` request
2. `MCPServer` looks up the tool name in its registry
3. The tool is executed via YAPOC's existing tool infrastructure (same `BaseTool.execute()` path)
4. The result string is wrapped into MCP `TextContent` blocks
5. If the tool errors, it's wrapped into MCP `ErrorContent` blocks

```python
# Translation: MCP inputSchema → YAPOC ToolDefinition
mcp_tool_def = ToolDefinition(
    name=tool.name,
    description=tool.description,
    input_schema=tool.input_schema,  # Already JSON Schema
)

# Translation: YAPOC string result → MCP content
mcp_result = {
    "content": [
        {"type": "text", "text": result_string}
    ]
}
```

---

## 5. Playwright MCP for Self-Management

### 5.1 Overview

**Playwright MCP** (Microsoft's official MCP server for browser automation, `@playwright/mcp`) runs as a sidecar process alongside YAPOC. It gives YAPOC agents the ability to control a real browser (Chromium) — navigate pages, click elements, fill forms, take screenshots, and evaluate JavaScript.

This capability enables YAPOC to **"manage itself"** by interacting with its own FastAPI dashboard UI. After code changes, config updates, or agent deployments, YAPOC can open its own dashboard, verify agent status indicators, run E2E tests, and capture visual evidence — all autonomously.

### 5.2 Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        YAPOC Process                             │
│                                                                  │
│  ┌─────────────┐   ┌──────────────────┐   ┌──────────────────┐  │
│  │ YAPOC Agent  │──▶│  Tool Registry   │──▶│  MCP Host Layer  │  │
│  │ (Researcher, │   │                  │   │  (host.py)       │  │
│  │  tester,     │   │ mcp__playwright__│   │                  │  │
│  │  etc.)       │   │   * tools        │   │  stdio transport │  │
│  └─────────────┘   └──────────────────┘   └────────┬─────────┘  │
│                                                     │            │
│  ┌──────────────────────────────────────────────────┼─────────┐  │
│  │  FastAPI Backend (port 8000)                     │         │  │
│  │  ┌──────────────────────┐                        │         │  │
│  │  │ Dashboard UI (React) │◀──── browser opens ────┘         │  │
│  │  │ /api/health          │                                   │  │
│  │  │ /api/agents          │                                   │  │
│  │  │ /api/metrics         │                                   │  │
│  │  └──────────────────────┘                                   │  │
│  └─────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ stdio (subprocess)
                              ▼
              ┌─────────────────────────────────────┐
              │  Playwright MCP Server               │
              │  (@playwright/mcp)                   │
              │                                      │
              │  ┌─────────────────────────────────┐ │
              │  │ Chromium Browser (headless)     │ │
              │  │ → Navigate to http://localhost: │ │
              │  │   8000/                         │ │
              │  │ → Click, fill, screenshot,      │ │
              │  │   evaluate JS                   │ │
              │  └─────────────────────────────────┘ │
              └─────────────────────────────────────┘
```

**Key architectural decisions:**

- Playwright MCP runs as a **subprocess** using stdio transport, managed by the MCP Host layer
- A new **`browser` capability module** wraps Playwright MCP tools for any agent that needs them
- The **Researcher agent** gets the browser module by default for investigation tasks
- A new **`tester` temporary agent type** can be spawned for focused E2E verification
- Playwright MCP tools are namespaced as `mcp__playwright__*` in the tool registry
- The browser process is launched on demand and killed after each test session to conserve resources

### 5.3 Tool Mapping

| Playwright MCP Tool | YAPOC Use Case | Namespaced Name |
|---|---|---|
| `browser_navigate` | Open YAPOC dashboard pages | `mcp__playwright__browser_navigate` |
| `browser_click` | Click UI elements (agent status tabs, buttons) | `mcp__playwright__browser_click` |
| `browser_fill` | Fill forms (submit test tasks) | `mcp__playwright__browser_fill` |
| `browser_snapshot` | Capture accessibility tree for debugging | `mcp__playwright__browser_snapshot` |
| `browser_screenshot` | Take screenshots for visual diff | `mcp__playwright__browser_screenshot` |
| `browser_evaluate` | Run JS to hit API endpoints, parse JSON responses | `mcp__playwright__browser_evaluate` |

### 5.4 Use Cases

#### Use Case 1: Self-healing UI checks

After config/code changes, YAPOC opens its own dashboard and verifies agent status pages show green indicators.

**Workflow:**
1. Cron or Master spawns a `tester` agent with the browser capability
2. Tester navigates to `http://localhost:8000/`
3. Tester clicks through each agent tab on the dashboard
4. Tester uses `browser_snapshot` to capture the accessibility tree and check status indicators
5. Tester reports any agents showing error states
6. If errors found, tester notifies the Doctor agent for investigation
7. After Doctor resolves issues, tester re-verifies

**Example tool sequence:**
```
mcp__playwright__browser_navigate(url="http://localhost:8000/")
mcp__playwright__browser_snapshot()
→ "Agent status: master=🟢, planning=🟢, builder=🟢, keeper=🔴, cron=🟢"
→ Keeper shows red → notify Doctor
```

#### Use Case 2: E2E regression testing

After Builder modifies code, verify the full task lifecycle works end-to-end.

**Workflow:**
1. Restart backend (via `server_restart` tool or shell command)
2. Wait for backend to be ready (poll `/api/health` via `browser_evaluate`)
3. Open dashboard in browser
4. Submit a test task via the UI
5. Verify the task appears in the task list
6. Wait for agent to complete
7. Verify the result appears in the UI
8. Take screenshot as evidence

**Example tool sequence:**
```
# Step 1: Restart backend
shell_exec(command="systemctl restart yapoc-backend", timeout=10)

# Step 2: Wait for health
mcp__playwright__browser_evaluate(
  script="fetch('/api/health').then(r => r.json()).then(d => JSON.stringify(d))"
)
→ '{"status":"ok","agents":12}'

# Step 3-4: Open dashboard and submit task
mcp__playwright__browser_navigate(url="http://localhost:8000/")
mcp__playwright__browser_click(selector="button[data-testid='new-task']")
mcp__playwright__browser_fill(selector="textarea[name='task-input']", value="Test task")
mcp__playwright__browser_click(selector="button[type='submit']")

# Step 5-7: Verify task lifecycle
mcp__playwright__browser_snapshot()
→ "Task 'Test task' status: running"
# ... wait ...
mcp__playwright__browser_snapshot()
→ "Task 'Test task' status: completed"

# Step 8: Evidence
mcp__playwright__browser_screenshot()
→ [saved as evidence.png]
```

#### Use Case 3: Visual diff on UI changes

Detect unintended visual regressions after frontend changes.

**Workflow:**
1. Before UI changes: take screenshot of each page → save as baseline
2. After UI changes: take screenshots from same URLs
3. Use `browser_evaluate` to compare pixel data or use an external diff tool
4. Flag any unexpected visual changes

**Example:**
```
# Baseline capture (before changes)
mcp__playwright__browser_navigate(url="http://localhost:8000/agents")
mcp__playwright__browser_screenshot()
→ [save as baseline/agents.png]

# After changes
mcp__playwright__browser_navigate(url="http://localhost:8000/agents")
mcp__playwright__browser_screenshot()
→ [save as current/agents.png]

# Compare
shell_exec(command="compare baseline/agents.png current/agents.png diff.png")
→ "Images differ by 12.3% — 45 pixels changed"
```

#### Use Case 4: Backend API smoke tests

Use `browser_evaluate` to hit API endpoints directly without navigating the UI.

**Workflow:**
```
# Health check
mcp__playwright__browser_evaluate(
  script="fetch('/api/health').then(r => r.json()).then(d => JSON.stringify(d))"
)
→ '{"status":"ok","agents":12,"uptime":3600}'

# Agent list
mcp__playwright__browser_evaluate(
  script="fetch('/api/agents').then(r => r.json()).then(d => JSON.stringify(d))"
)
→ '{"agents":["master","planning","builder","keeper","cron","doctor","researcher",...]}'

# Metrics
mcp__playwright__browser_evaluate(
  script="fetch('/api/metrics').then(r => r.json()).then(d => JSON.stringify(d))"
)
→ '{"tasks_completed":142,"avg_duration_s":45.2,"error_rate":0.03}'
```

#### Use Case 5: User simulation for debugging

Replay user-reported bug sequences step by step to identify where behavior diverges.

**Workflow:**
1. Load the bug report and extract the sequence of UI actions
2. Navigate to the starting page
3. Execute each step using `browser_click`, `browser_fill`, `browser_navigate`
4. After each step, call `browser_snapshot` to capture the accessibility tree
5. Compare with expected state at each step
6. Identify where behavior diverges from expectations

### 5.5 Agent Integration

#### Researcher Agent

The Researcher agent gets `mcp__playwright__*` tools by default in `agent-settings.json`. This allows it to:

- Investigate live UI issues reported by users
- Verify dashboard state during research tasks
- Capture evidence (screenshots, accessibility trees) for bug reports
- Cross-reference UI state with backend API responses

**Configuration addition:**
```json
{
  "agents": {
    "researcher": {
      ...existing config...,
      "mcp_servers": ["playwright"]
    }
  }
}
```

#### New Tester Agent Type

The `tester` is a **temporary agent** spawned by Master or Cron for focused E2E verification. It:

- Gets the full Playwright MCP toolset
- Gets file tools for saving evidence (screenshots, logs)
- Has a specialized PROMPT.MD that instructs it on E2E testing workflows
- Self-destructs after reporting results back to the spawning agent

**Configuration in `agent-settings.json`:**
```json
{
  "agents": {
    "tester": {
      "adapter": "deepseek",
      "model": "deepseek-chat",
      "tools": [
        "mcp__playwright__browser_navigate",
        "mcp__playwright__browser_click",
        "mcp__playwright__browser_fill",
        "mcp__playwright__browser_snapshot",
        "mcp__playwright__browser_screenshot",
        "mcp__playwright__browser_evaluate",
        "file_write",
        "file_read",
        "file_list",
        "notify_parent"
      ],
      "mcp_servers": ["playwright"],
      "temperature": 0.2,
      "max_tokens": 8096
    }
  }
}
```

**Tester PROMPT.MD structure:**
```
You are the Tester agent of YAPOC — a temporary E2E verification agent.

## Role
You are spawned for a single purpose: verify that YAPOC's UI and backend
are working correctly after changes. You have access to a real browser
via Playwright MCP tools.

## Your Tools
- mcp__playwright__browser_navigate — Open URLs
- mcp__playwright__browser_click — Click elements
- mcp__playwright__browser_fill — Fill form fields
- mcp__playwright__browser_snapshot — Get accessibility tree
- mcp__playwright__browser_screenshot — Take screenshots
- mcp__playwright__browser_evaluate — Run JavaScript in browser context

## Workflow
1. Navigate to the target URL
2. Perform the specified actions
3. Verify expected outcomes using snapshots or evaluate
4. Report results via notify_parent
5. Self-destruct (temporary agent)

## Rules
- Always wait for page loads between actions
- Use snapshot for structural verification
- Use screenshot for visual evidence
- Use evaluate for API-level checks
- Report failures with specific details (URL, selector, expected vs actual)
```

### 5.6 Playwright MCP Server Config

The Playwright MCP server is defined in `mcp-servers.json`:

```json
{
  "mcp_servers": [
    ...existing servers...,
    {
      "name": "playwright",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@playwright/mcp"],
      "tools_allowlist": ["*"],
      "auth": "none",
      "timeout_s": 60,
      "enabled": true,
      "auto_reconnect": true
    }
  ]
}
```

**Notes:**
- Uses `npx -y @playwright/mcp` to run without explicit installation (fetches on first use)
- All tools are allowlisted since they are all browser-control tools with no external access
- 60-second timeout accommodates slow page loads and complex E2E sequences
- `auto_reconnect: true` ensures the browser is available after transient failures

### 5.7 Self-Healing Automation Loop

After any config/code change, a cron-like mechanism triggers self-healing:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Self-Healing Loop                             │
│                                                                  │
│  1. Change detected (config edit, code deploy, agent update)     │
│     │                                                            │
│     ▼                                                            │
│  2. Cron agent triggers self-healing check                       │
│     │                                                            │
│     ▼                                                            │
│  3. Cron spawns tester agent with browser module                 │
│     │                                                            │
│     ▼                                                            │
│  4. Tester runs self-healing UI check workflow:                  │
│     ├─ Navigate to dashboard                                     │
│     ├─ Check each agent status                                   │
│     └─ Report results                                            │
│     │                                                            │
│     ▼                                                            │
│  5. All green? ──Yes──▶ Report success, tester self-destructs    │
│     │                                                             │
│     No                                                            │
│     ▼                                                            │
│  6. Tester reports issues to Doctor agent                        │
│     │                                                            │
│     ▼                                                            │
│  7. Doctor investigates and spawns Builder to fix                │
│     │                                                            │
│     ▼                                                            │
│  8. After fix, tester re-verifies (loop back to step 4)          │
│     │                                                            │
│     ▼                                                            │
│  9. Loop continues until all agents show green or max retries    │
│     exceeded                                                     │
└─────────────────────────────────────────────────────────────────┘
```

**Configuration parameters:**
- `SELF_HEAL_INTERVAL`: How often to run the check (default: after every config/code change event)
- `SELF_HEAL_MAX_RETRIES`: Maximum number of fix-verify cycles (default: 3)
- `SELF_HEAL_RETRY_DELAY`: Wait time between retry cycles (default: 30s)

### 5.8 Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **Headless browser resource usage** | Playwright uses significant memory (200-400MB per instance) | Only run when needed (not continuously); kill browser after each test session; use `--headless` mode |
| **Port conflicts** | YAPOC may not be running on port 8000 | Make the dashboard URL configurable via `YAPOC_DASHBOARD_URL` env var; default to `http://localhost:8000` |
| **Flaky tests** | Browser automation can be timing-dependent | Implement retry logic (3 attempts with 2s delay); use generous timeouts (10s per action); use `browser_snapshot` for debugging failures |
| **npx dependency** | Requires Node.js and network access to fetch `@playwright/mcp` | Document Node.js as prerequisite; consider pre-installing via `npm install -g @playwright/mcp` for offline use |
| **Browser version mismatch** | Playwright may download a different Chromium version | Pin Playwright version in `mcp-servers.json` args; use `PLAYWRIGHT_BROWSERS_PATH` env var |
| **Concurrent browser sessions** | Multiple agents could open browsers simultaneously | Use a semaphore in the MCP Host layer to limit to one browser session at a time; queue requests |

---

## 6. Configuration Format Specification

### `mcp-servers.json` (project root)

```json
{
  "mcp_servers": [
    {
      "name": "string (required, unique identifier)",
      "transport": "string (required: 'stdio' | 'sse' | 'websocket')",
      "command": "string (required for stdio, the executable)",
      "args": ["string array (optional, command arguments)"],
      "env": {
        "KEY": "string (optional, environment variables; ${VAR} references .env)"
      },
      "url": "string (required for sse/websocket)",
      "tools_allowlist": ["string array, '*' for all"],
      "resources_allowlist": ["string array, '*' for all"],
      "auth": "string ('none' | 'api_key' | 'token')",
      "api_key": "string (optional, for auth='api_key'; ${VAR} references .env)",
      "token": "string (optional, for auth='token'; ${VAR} references .env)",
      "timeout_s": 30,
      "enabled": true,
      "auto_reconnect": true
    }
  ]
}
```

### Changes to `agent-settings.json`

Each agent entry gains an optional `mcp_servers` field:

```json
{
  "agents": {
    "builder": {
      ...existing fields...,
      "mcp_servers": ["github", "filesystem"]
    }
  }
}
```

### Changes to `.env`

```
# MCP Server (YAPOC as MCP server)
MCP_API_KEY=your-api-key-here
MCP_SERVER_ENABLED=true
MCP_SERVER_PORT=8000  # shares the existing FastAPI port
```

---

## 7. Implementation Plan

### Phase 1: Foundation (2-3 days)

| Task | Files | Effort |
|---|---|---|
| Install `mcp` Python SDK | `pyproject.toml` | 15 min |
| Create `app/utils/mcp/` package with `__init__.py` and `types.py` | New files | 1 hr |
| Implement `config.py` — load and validate `mcp-servers.json` | New file | 2 hr |
| Implement `MCPHostManager` class with connection lifecycle | `host.py` | 4 hr |
| Add `MCP_API_KEY` and `MCP_SERVER_ENABLED` to `Settings` | `app/config/settings.py` | 30 min |
| Write unit tests for config loading | `tests/` | 2 hr |

**Deliverable:** MCP config loads, host manager can connect to a stdio MCP server.

### Phase 1b: Playwright MCP Setup (1-2 days)

| Task | Files | Effort |
|---|---|---|
| Install Playwright MCP (`npx @playwright/mcp`) | — | 15 min |
| Add Playwright MCP server config to `mcp-servers.json` | `mcp-servers.json` | 15 min |
| Add `tester` agent type to `agent-settings.json` | `app/config/agent-settings.json` | 30 min |
| Add `mcp_servers: ["playwright"]` to researcher agent config | `app/config/agent-settings.json` | 15 min |
| Write tester agent PROMPT.MD | `app/agents/tester/PROMPT.MD` | 1 hr |
| Create tester agent CONFIG.yaml | `app/agents/tester/CONFIG.yaml` | 30 min |
| Add `YAPOC_DASHBOARD_URL` env var to Settings | `app/config/settings.py` | 15 min |
| Write E2E test workflows for tester agent | `app/agents/tester/` | 2 hr |
| Write integration tests for Playwright MCP tool wrapping | `tests/` | 2 hr |

**Deliverable:** Playwright MCP server runs as a sidecar; Researcher and tester agents can control a browser to verify YAPOC's own UI.

### Phase 2: MCP Host — Tool Registration (2-3 days)

| Task | Files | Effort |
|---|---|---|
| Implement `MCPToolWrapper` BaseTool subclass | `registry.py` | 2 hr |
| Implement `register_server_tools()` and `unregister_server_tools()` | `registry.py` | 2 hr |
| Integrate tool registration into `build_tools()` in `app/utils/tools/__init__.py` | `app/utils/tools/__init__.py` | 1 hr |
| Add `mcp_servers` field to agent config in `agent-settings.json` | `app/config/agent-settings.json` | 30 min |
| Implement `MCPReadResourceTool` and `MCPGetPromptTool` | `host.py` | 2 hr |
| Add MCP host startup/shutdown to FastAPI lifespan | `app/backend/main.py` | 1 hr |
| Write integration tests with a test MCP server | `tests/` | 3 hr |

**Deliverable:** YAPOC agents can use tools from external MCP servers.

### Phase 3: MCP Server — Exposing YAPOC (2-3 days)

| Task | Files | Effort |
|---|---|---|
| Implement `MCPServer` class | `server.py` | 4 hr |
| Create `app/backend/routers/mcp.py` with SSE + message endpoints | New file | 3 hr |
| Register MCP router in `app/backend/main.py` | `app/backend/main.py` | 15 min |
| Implement tool → MCP tool translation | `server.py` | 2 hr |
| Implement resource and prompt handlers | `server.py` | 2 hr |
| Add authentication middleware | `server.py` | 1 hr |
| Write integration tests with MCP client SDK | `tests/` | 3 hr |

**Deliverable:** External MCP clients can discover and call YAPOC tools.

### Phase 4: Production Hardening (2-3 days)

| Task | Files | Effort |
|---|---|---|
| Implement reconnection with exponential backoff | `host.py` | 2 hr |
| Add health-check endpoint for MCP servers | `host.py` + router | 1 hr |
| Add audit logging for all MCP tool calls | `host.py`, `server.py` | 1 hr |
| Implement sandbox isolation for external MCP tool execution | `host.py` | 2 hr |
| Add MCP admin router (list servers, reconnect, toggle) | `app/backend/routers/mcp_admin.py` | 2 hr |
| Add MCP status to health dashboard | Frontend | 2 hr |
| Performance testing and optimization | — | 3 hr |
| Documentation and examples | `docs/mcp-usage.md` | 2 hr |

**Deliverable:** Production-ready MCP integration with monitoring and recovery.

---

## 8. Security Considerations

### 8.1 MCP Server Allowlist/Blocklist

- `mcp-servers.json` is the single source of truth for which external servers YAPOC connects to
- No agent can connect to an MCP server not listed in this file
- A `blocked_servers` list can be added for emergency revocation without deleting the config

### 8.2 Tool-Level Permissions

- Each MCP server has a `tools_allowlist` — only matching tools are registered
- Each agent has an `mcp_servers` list — only tools from those servers are available
- The `tools` list in agent config can further restrict to specific MCP tools
- Write/delete MCP tools should be explicitly allowlisted, never wildcarded by default

### 8.3 Credential Management

- API keys and tokens in `mcp-servers.json` use `${VAR}` syntax referencing `.env`
- The raw `mcp-servers.json` file should be in `.gitignore` if it contains resolved secrets
- MCP server credentials are never exposed to agents — the host layer handles auth transparently
- The MCP Server (YAPOC exposing itself) uses a single `MCP_API_KEY` from `.env`

### 8.4 Audit Logging

Every MCP tool call is logged with:
- Timestamp
- Agent name (for host-side calls) or client ID (for server-side calls)
- MCP server name
- Tool name
- Input arguments (PII-sensitive fields can be redacted)
- Duration
- Success/failure status

Logs go to a dedicated `logs/mcp-audit.log` file (rotating, 30-day retention).

### 8.5 Sandbox Isolation

- External MCP tools accessed via stdio run as child processes of the YAPOC process
- The `timeout_s` per-server setting prevents runaway external tools
- For high-risk MCP servers (filesystem, shell), consider running in a Docker container or with subuid namespace isolation
- MCP server processes inherit YAPOC's resource limits (ulimit, cgroups if available)

---

## 9. Open Questions / Future Work

1. **MCP SDK maturity**: The Python `mcp` SDK is actively evolving. Pin to a specific version and monitor for breaking changes.

2. **Streaming tool calls**: MCP supports streaming results for long-running tools. YAPOC's `BaseTool.execute()` is currently synchronous (returns a single string). Streaming MCP tool results would require changes to the tool interface.

3. **WebSocket transport**: The MCP spec defines WebSocket transport, but the Python SDK may not support it yet. Fall back to SSE for now.

4. **MCP prompt auto-injection**: Should MCP prompts be auto-injected into agent system prompts, or only available via explicit tool calls? Current design favors explicit calls for security.

5. **Multi-tenant MCP Server**: If YAPOC serves multiple external clients, each needs isolated sessions. The current SSE-per-connection model handles this, but resource cleanup needs attention.

6. **MCP discovery (mcp.json)**: The MCP spec defines a discovery mechanism where hosts find `mcp.json` files. Future work could add auto-discovery of locally installed MCP servers.

7. **Tool result size limits**: MCP tool results can be large. YAPOC's existing `truncate_tool_output` mechanism should be applied to MCP tool results as well.

8. **Bidirectional MCP**: Could YAPOC agents act as MCP servers for each other? This would allow agent-to-agent tool sharing without going through the central tool registry.

---

## Appendix: File Change Summary

### New Files

| File | Purpose |
|---|---|
| `app/utils/mcp/__init__.py` | Package exports |
| `app/utils/mcp/types.py` | Type definitions (dataclasses for MCP server config, connection state) |
| `app/utils/mcp/config.py` | Load and validate `mcp-servers.json` |
| `app/utils/mcp/host.py` | `MCPHostManager` — connect to external MCP servers, manage lifecycle |
| `app/utils/mcp/registry.py` | `MCPToolWrapper`, `register_server_tools()`, `unregister_server_tools()` |
| `app/utils/mcp/server.py` | `MCPServer` — expose YAPOC tools to MCP clients |
| `app/backend/routers/mcp.py` | FastAPI router for MCP SSE + message endpoints |
| `app/backend/routers/mcp_admin.py` | Admin endpoints for MCP server management |
| `mcp-servers.json` | MCP server definitions (template, add to `.gitignore` if secrets resolved) |
| `docs/mcp-usage.md` | Usage guide and examples |
| `app/agents/tester/PROMPT.MD` | Tester agent system prompt for E2E verification workflows |
| `app/agents/tester/CONFIG.yaml` | Tester agent configuration (tools, model, MCP servers) |

### Modified Files

| File | Changes |
|---|---|
| `app/config/settings.py` | Add `MCP_API_KEY`, `MCP_SERVER_ENABLED`, `YAPOC_DASHBOARD_URL` fields |
| `app/config/agent-settings.json` | Add optional `mcp_servers` list per agent; add `tester` agent type; add `mcp_servers: ["playwright"]` to researcher |
| `app/utils/tools/__init__.py` | Extend `build_tools()` to resolve `mcp__*` tool names |
| `app/backend/main.py` | Add MCP host startup/shutdown in lifespan, include MCP routers |
| `pyproject.toml` | Add `mcp` dependency |
| `.env.example` | Add MCP-related environment variables |
| `mcp-servers.json` | Add `playwright` server entry with `npx -y @playwright/mcp` |
