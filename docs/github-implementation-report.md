# GitHub implementation report

## Files changed

New native implementation:
- `plugins/github/github.py`, `plugins/github/plugin.yaml`
- `app/utils/github/__init__.py`, `client.py`, `logging.py`, `mcp.py`, `observability.py`
- `app/backend/routers/github.py`
- `app/frontend/src/components/GitHubIntegrationStatus.tsx`
- `tests/test_github_plugin.py`
- `docs/github-integration.md`, this report

Existing integration points updated:
- `.env.example`, `app/config/settings.py`
- `app/config/agent-settings.json`
- `app/agents/master/CONFIG.yaml`, `doctor/CONFIG.yaml`, `evaluator/CONFIG.yaml`, `builder/CONFIG.yaml`
- `app/agents/base/__init__.py` (GitHub security-gate failures deny execution)
- `app/backend/main.py` (router and optional existing-scheduler job)
- `app/frontend/src/components/ObservabilityTab.tsx`
- `app/utils/mcp/config.py`, `host.py`, `registry.py`, `types.py`
- `app/utils/tools/security_policy.py`, `security_gate.py`
- `tests/test_tool_retry.py` (own the event loop instead of relying on a closed global loop)
- `README.md` (setup-guide link)

Other pre-existing working-tree changes were preserved.

## Configuration added

`GITHUB_TOKEN`, `GITHUB_ENABLED`, `GITHUB_DEFAULT_OWNER`, `GITHUB_DEFAULT_REPO`,
`GITHUB_ALLOWED_REPOS`, `GITHUB_WRITE_ENABLED`, `GITHUB_SELF_REPO`,
`GITHUB_POLL_INTERVAL_SECONDS`, `GITHUB_MCP_ENABLED`, `GITHUB_MCP_COMMAND`.

Integration, writes, MCP and polling default off. The token uses excluded,
non-repr `SecretStr` settings. It is consumed only at authentication/redaction
boundaries, never exposed as a tool argument or returned configuration value.

## Tools and agent access

31 native tools: 25 reads plus six controlled mutations. Every tool also has
its standard `plugin:github:` alias. The complete names are in
`plugins/github/plugin.yaml`; [the setup guide](github-integration.md#native-tools-and-permissions)
lists each initial agent's exact grants. Master has nine reads, doctor seven,
evaluator thirteen, builder five; keeper has none. No agent receives a native
write grant or new GitHub MCP grant by default.

The MCP host can register `mcp__github__get_file_contents`,
`mcp__github__list_branches`, `mcp__github__list_commits` and standard MCP plugin
aliases after connection. These remain guarded at the host call boundary.

## Responsibilities and security

Native Python plugin: GitHub API, allowlist, health summaries, bounded reads,
controlled writes, audit, dashboard status and opt-in scheduler signals.

MCP: existing host launches the separately installed official server for narrow
external-repository exploration. It does not reimplement REST or need to be
running for native operations. Reserved configuration prevents a generic
`github` server entry from overriding the integration's policy.

All native/MCP calls require explicit repository policy. Writes require the
config switch, an agent tool grant and the existing external-action security
gate. Failure of GitHub's gate refuses execution. Drafts always start as drafts;
updates check for an open draft and modify title/body only. No destructive
operations are exposed. API bodies/exceptions and signed storage URLs are not
logged. Write audits omit payloads. Credentials are not forwarded to log storage.

## Validation

- `poetry run pytest tests/test_github_plugin.py tests/test_mcp_config.py tests/test_security_policy.py -q`: 156 passed before the final fail-closed regression test.
- `poetry run pytest tests/test_github_plugin.py tests/test_security_policy.py tests/test_tool_retry.py -q`: 157 passed with the fail-closed test and event-loop fix.
- `poetry run pytest tests/ app/backend/tests/ -q --maxfail=0`: **709 passed**, two pre-existing warnings, 20.95 seconds (outside sandbox).
- `pnpm --dir app/frontend build`: passed TypeScript and Vite production build;
  Vite reported a large-bundle warning and Node a module.register deprecation warning.
- `poetry run python -m compileall -q app/utils/github plugins/github app/utils/mcp app/backend/routers/github.py`: passed.
- `git diff --check`: passed.
- Plugin loader smoke check: all 31 manifest tools and 31 aliases registered.

The sandboxed full suite stalled in existing async context file reads. The
unsandboxed run completed, revealing five event-loop assumptions in the existing
retry tests; their helper now uses `asyncio.run`. A subsequent run found a
constructor mistake in the new regression test, which was corrected. No live
GitHub token, real GitHub API call, or MCP server is needed by these tests.

Backend restart is required: settings are instantiated/cached at import, plugins
load at startup, and agents use process-local configuration. Use
`poetry run yapoc restart` (or the deployment supervisor's restart flow).
This change does not restart the user's running deployment automatically.

## Exact fork/clone setup

1. Create a fine-grained GitHub PAT selecting your repositories and only needed
   read permissions: Metadata, Contents, Issues, Pull requests, Actions, Checks,
   Commit statuses; Dependabot alerts is optional.
2. Privately place the PAT in `.env` as `GITHUB_TOKEN`; set `GITHUB_ENABLED=true`.
3. Set `GITHUB_DEFAULT_OWNER` and `GITHUB_DEFAULT_REPO` to your fork. Set
   `GITHUB_ALLOWED_REPOS` to comma-separated exact `owner/repo` entries including
   your fork. Optionally set `GITHUB_SELF_REPO` to another allowed repository.
4. Keep `GITHUB_WRITE_ENABLED=false`, `GITHUB_MCP_ENABLED=false`, and
   `GITHUB_POLL_INTERVAL_SECONDS=0` for initial setup.
5. Run `poetry run yapoc restart` and `pnpm --dir app/frontend build` for a
   production UI. Open Observability and select **Check GitHub**.
6. Optionally install the official MCP server executable, set
   `GITHUB_MCP_COMMAND` to its path, set `GITHUB_MCP_ENABLED=true`, restart, and
   grant only the needed `mcp__github__...` read tools.
7. For writes, deliberately grant the required individual tool and corresponding
   token permission, enable write mode, and restart. The normal security gate
   still decides whether each action may run.

Full configuration examples, sources, troubleshooting and permission details
are in [the integration guide](github-integration.md).

## Deliberate limits

Health summaries are bounded samples with explicit limits, not exhaustive
repository analytics. Failed step names are investigative leads, not confirmed
root causes. Known commit SHAs can correlate local failures; automatic SHA
inference and a persistent historical trend store are deferred to avoid guessing
or inventing data. Backend status cache is process-local and resets on restart.

Telegram delivery uses existing agent notification tools; no new unsolicited
sender is installed. Enterprise API endpoints and additional MCP tools/resources
are deferred to keep this initial policy narrow. Real-token connectivity and a
live official MCP handshake were not exercised. A human changing draft status
concurrently can race the draft-update precheck; GitHub supplies no atomic
conditional draft update in this implementation.
