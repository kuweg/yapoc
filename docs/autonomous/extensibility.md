# Extensibility — Plugins, MCP, Dynamic Tools

OpenClaw has plugins (npm), skills (ClawHub), MCP (via mcporter).
Claude Code has MCP servers, hooks, custom slash commands.
YAPOC needs its own extensibility story — one that fits the agent hierarchy.

---

## Current state

The tool registry is closed. 20 tools, hardcoded in `app/utils/tools/__init__.py`.
Adding a tool means editing Python code, registering it in the registry,
adding it to agent CONFIG.md files, and restarting.

This is fine for core tools. It does not scale for user-specific or project-specific needs.

---

## Three layers of extensibility

### Layer 1: Workspace skills (easiest, no code)

**Inspired by:** OpenClaw skills, Claude Code CLAUDE.md

A skill is a markdown file in the workspace that an agent can read and follow.
No Python code needed. The LLM reads the instructions and uses existing tools
to accomplish them.

```
app/projects/skills/
├── deploy.md        → "How to deploy this project"
├── review-pr.md     → "Steps to review a pull request"
├── run-tests.md     → "Test execution procedure and expected behavior"
└── style-guide.md   → "Coding conventions for this project"
```

Skills are injected into the agent's context when referenced by name.
Master can read the skill list and delegate accordingly.

```
User: "deploy the latest changes"
Master: reads skills/deploy.md → follows the deployment procedure using existing tools
```

**Implementation:**
- `file_list` on `app/projects/skills/` to discover skills
- `file_read` on the skill file to load instructions
- Prompt instruction in master: "check skills/ for relevant procedures before improvising"
- No new code needed — just conventions

### Layer 2: Python tool plugins (code, hot-loadable)

**Inspired by:** OpenClaw plugin API

A tool plugin is a Python file that defines one or more tools following
the `BaseTool` interface. Placed in a plugins directory, loaded on startup.

```
plugins/
├── jira_sync.py     → JiraSyncTool (syncs Dashboard tickets with Jira)
├── slack_notify.py  → SlackNotifyTool (posts to Slack channels)
└── db_query.py      → DbQueryTool (runs read-only SQL against a project database)
```

Each plugin file:

```python
# plugins/slack_notify.py

from app.utils.tools import BaseTool, RiskTier

class SlackNotifyTool(BaseTool):
    name = "slack_notify"
    description = "Send a message to a Slack channel"
    risk = RiskTier.CONFIRM
    parameters = {
        "channel": {"type": "string", "description": "Slack channel name"},
        "message": {"type": "string", "description": "Message text"}
    }

    async def execute(self, channel: str, message: str) -> str:
        # implementation
        ...
```

**Implementation:**
- Plugin directory: `plugins/` (configurable in settings)
- Discovery: on startup, scan directory for `.py` files
- Loading: import each module, find `BaseTool` subclasses, register in `TOOL_REGISTRY`
- Hot-reload: file watcher on `plugins/` → re-import changed files without restart
- Security: plugins run in the same process (trusted), but tools still respect RiskTier

### Layer 3: MCP servers (external processes, protocol-based)

**Inspired by:** Claude Code MCP, OpenClaw mcporter

MCP (Model Context Protocol) lets external processes expose tools to the agent.
Each MCP server runs as a separate process and communicates via stdio or HTTP.

```yaml
# app/config/settings.py or a dedicated mcp.yaml

mcp_servers:
  - name: github
    command: "npx @modelcontextprotocol/server-github"
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"

  - name: postgres
    command: "npx @modelcontextprotocol/server-postgres"
    env:
      DATABASE_URL: "${DATABASE_URL}"

  - name: filesystem
    command: "npx @modelcontextprotocol/server-filesystem"
    args: ["--root", "/home/user/projects"]
```

**Implementation:**
- MCP client in `app/utils/mcp_client.py`
- On startup: spawn configured MCP servers as subprocesses
- Discover tools from each server via MCP `tools/list`
- Register discovered tools in `TOOL_REGISTRY` with a `mcp:` prefix
  (e.g., `mcp:github:create_issue`)
- Tool calls proxied through MCP client to the server process
- All MCP tools default to `RiskTier.CONFIRM` (external process = untrusted)

---

## How agents discover and use extended tools

Tools from all three layers merge into the same `TOOL_REGISTRY`.
Agents see them in their tool list based on CONFIG.md.

```yaml
# app/agents/builder/CONFIG.md

tools:
  # Core tools
  - file_read
  - file_write
  - shell_exec
  # Plugin tools
  - slack_notify
  # MCP tools
  - mcp:github:create_issue
  - mcp:postgres:query
```

From the agent's perspective, there is no difference between a core tool,
a plugin tool, and an MCP tool. They all have the same interface:
name, description, parameters, execute.

---

## Skill registry (future, inspired by ClawHub)

When the plugin ecosystem matures, a registry of community-contributed tools:

- Hosted repository of tool plugins (like ClawHub, but for YAPOC)
- Install via: `yapoc plugins install slack-notify`
- Plugins downloaded to `plugins/`, auto-registered
- Versioned, with dependency declarations

This is a later concern. The foundation (Layer 1 + 2) is sufficient for now.

---

## Implementation priority

```
Now:      Layer 1 (workspace skills) — zero code, convention only
Phase 2:  Layer 2 (Python plugins) — hot-loadable tools
Phase 3:  Layer 3 (MCP servers) — external process tools
Later:    Skill registry — community plugins
```

Layer 1 is free — it works with existing tools today.
Layer 2 requires a plugin loader (~100 lines of code).
Layer 3 requires an MCP client (significant, but well-specified protocol).
