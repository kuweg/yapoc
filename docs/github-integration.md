# GitHub integration

YAPOC's native `github` plugin owns repository maintenance and health workflows.
The optional official GitHub MCP server provides three interoperable repository
exploration tools through the existing MCP host. Neither is required for startup.
No account, repository, organization or branch is baked into the integration.

## Setup for a fork or clone

1. Create a fine-grained personal access token in GitHub Settings → Developer
   settings → Personal access tokens → Fine-grained tokens. Select your resource
   owner, an expiration, and **only the repositories you intend YAPOC to access**.
   Obtain organization approval when required. Do not send the token in chat.
2. In the clone's private `.env`, set the following, replacing the example
   repository names with your own. Enter `GITHUB_TOKEN` directly in the private
   environment file or inject it through your deployment's secret manager.

   ```dotenv
   GITHUB_ENABLED=true
   GITHUB_TOKEN=
   GITHUB_DEFAULT_OWNER=your-account
   GITHUB_DEFAULT_REPO=your-fork
   GITHUB_ALLOWED_REPOS=your-account/your-fork,another-owner/library
   GITHUB_SELF_REPO=your-account/your-fork
   GITHUB_WRITE_ENABLED=false
   GITHUB_POLL_INTERVAL_SECONDS=0
   GITHUB_MCP_ENABLED=false
   GITHUB_MCP_COMMAND=github-mcp-server
   ```

3. Restart the backend with `poetry run yapoc restart`. For a managed installer
   deployment, use its normal supervisor restart flow. Plugin reload alone does
   not reload environment-backed settings or agent process configuration.
4. Rebuild a production frontend with `pnpm --dir app/frontend build`.
5. Open Connections → GitHub → **Check GitHub**. Verify the repository and
   connection status. No credentials are displayed by this interface.
6. Ask master for `github_get_health_summary`. Set `repository` explicitly for
   another allowlisted repository. A default/self repository must also be allowed.

`GITHUB_SELF_REPO` is optional; absent it, default owner/repo identify the self
repository. Allowlist matching is case insensitive, exact, and denies empty
lists, wildcard patterns, URLs and traversal. The native plugin and MCP use the
same policy. The GitHub credential's repository selection is a second boundary.
These boundaries apply to these integration tools; they are not a sandbox for
other tools such as shell execution.

## Minimum permissions

Grant read permissions only for the capabilities you need:

| Capability | Repository permissions |
| --- | --- |
| Repository identity | Metadata: read (GitHub supplies this) |
| Files, branches, commits, releases, tags, code search | Contents: read |
| Issues, issue comments, labels | Issues: read |
| PRs, changed files, reviews and comments | Pull requests: read |
| Runs, jobs, job logs | Actions: read |
| Check runs and combined commit status | Checks: read; Commit statuses: read |
| Dependabot alerts (optional) | Dependabot alerts: read |

See GitHub's [fine-grained permission reference](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens).
Some health/security fields depend on repository features and token permissions.
Unavailable optional PR/job details are marked unavailable. Failed primary health
reads fail the check without breaking YAPOC. Code search uses GitHub's default
branch index; use file reads with `ref` for other branches.

## Native tools and permissions

Every tool has the `github_` prefix. The plugin loader also registers
`plugin:github:<short_name>` aliases. Lists accept bounded `page` and `per_page`.
Issue lists exclude PRs; pages can consequently contain fewer issues than the
requested page size. Filters include issue state, labels and since; PR state,
head and base; and workflow branch, status and head SHA. Code search accepts a
literal search term, not query qualifiers that could escape repository scope.

| Agent | Explicit short-name grants |
| --- | --- |
| master | get_repo, get_health_summary, list_issues, get_issue, list_pull_requests, get_pull_request, list_workflow_runs, get_workflow_run, list_workflow_jobs |
| doctor | get_health_summary, list_workflow_runs, get_workflow_run, list_workflow_jobs, get_workflow_job_logs, get_commit_checks, get_commit_status |
| evaluator | list_issues, get_issue, list_issue_comments, list_pull_requests, get_pull_request, list_pull_request_files, list_pull_request_reviews, list_pull_request_comments, get_commit_checks, get_commit_status, list_workflow_runs, get_workflow_run, list_workflow_jobs |
| builder | get_repo, list_branches, list_commits, read_file, search_code |
| keeper and other agents | None |

Additional available reads, requiring deliberate individual grants:
`github_list_labels`, `github_list_releases`, `github_list_tags`,
`github_get_community_health`, `github_list_security_alerts`.
The manifest lists the entire tool surface. Both authoritative
`app/config/agent-settings.json` and fallback agent `CONFIG.yaml` files are kept
in sync. Avoid assigning the whole GitHub plugin: a wildcard also grants its
mutation tools, although write mode and policy checks still apply.

### Controlled writes

No agent receives write tools by default. To enable one, set
`GITHUB_WRITE_ENABLED=true`, give the token the matching Issues or Pull requests
write permission, and explicitly grant only the needed tool in agent-settings
and its CONFIG.yaml fallback. Restart before using it. The existing security
agent reviews external mutations in the normal tool execution flow; it can deny
an action. Setting write mode does not bypass this gate.

Available mutations: `github_create_issue`, `github_comment_on_issue`,
`github_comment_on_pull_request`, `github_update_labels`,
`github_create_draft_pull_request`, `github_update_draft_pull_request`.
Labels are added without replacing existing labels; remove one per request.
Draft creation requires existing head/base branches in the selected repository
and always sets `draft=true`; cross-repository heads are refused.
Draft updates require an open draft and can change only title/body. No tool
merges, pushes, creates/deletes branches, changes settings/secrets, dispatches
workflows or marks a draft ready. A concurrent human change can race the draft
check; GitHub has no conditional draft-update transaction here.

Writes emit a `github_audit` record containing action, repository, target ID and
outcome. Submitted bodies/titles are absent from those records and mutation
results. The existing security audit also omits GitHub payloads. PAT settings
are excluded from settings dumps/repr; API errors never expose remote error
bodies, headers or exception text. Output redaction strips the configured token
and recognizable GitHub token formats. Repository content remains untrusted.

## Health and notifications

The summary samples 30 runs, 100 open issue endpoint entries and 100 open PRs.
It includes stale counts (30 days by default), label distribution, open issues
created in the last seven days, failed runs and their SHAs, failed steps for up
to three runs, and check/review inspection for five PRs. Failed step names are
leads for investigation, not established root causes. Review states and check
results are evidence, not a definitive branch-protection mergeability verdict.

Pass a known local task/build commit as `head_sha` to correlate workflow runs;
YAPOC does not guess a SHA from task prose. Doctor can retrieve failed-job logs
and investigate. Log downloads follow only HTTPS GitHub Actions/Azure Blob
storage destinations, carry no GitHub authorization header to storage, and
return at most 200 KB. Standard GitHub API redirects are refused.
See [GitHub job log behavior](https://docs.github.com/en/rest/actions/workflow-jobs).

The summary's `message` is suitable for master's existing Telegram completion
and alert tools and normal task results. This integration sends no unsolicited
Telegram messages. The dashboard shows backend-process health checks; last
successful check/summary are in memory and reset at restart. Agent subprocess
checks return their own results without updating the backend's cache.

GET status never contacts GitHub. The check button throttles attempts to one per
minute. Optional `GITHUB_POLL_INTERVAL_SECONDS>0` uses the existing scheduler,
clamps intervals to at least 300 seconds, runs one check at a time, and logs only
changed health signals. Polling is disabled by default. Failures do not stop the
scheduler or backend. There is no persistent historical issue trend store;
recent open-issue counts explicitly describe the sampled cohort.

## Optional MCP

Install a reviewed release of the [official GitHub MCP server](https://github.com/github/github-mcp-server)
and place its `github-mcp-server` executable on YAPOC's PATH (or set
`GITHUB_MCP_COMMAND` to its absolute executable path). Use the official binary
installation instructions for your platform; YAPOC does not download or run a
container automatically.

Set `GITHUB_MCP_ENABLED=true` and restart. The existing MCP loader adds a reserved
`github` server using stdio, `--read-only`, and just `get_file_contents`,
`list_branches`, `list_commits`. The token goes to the child environment as
`GITHUB_PERSONAL_ACCESS_TOKEN`, never command arguments. Child stderr is suppressed.
No new MCP subsystem or REST implementation is involved. `mcp-servers.json`
entries named `github` are ignored in favor of this environment-backed policy.

Grant individual tools such as `mcp__github__get_file_contents` to an agent that
needs interoperable exploration. No initial GitHub MCP grants are added.
Existing MCP wildcard grants resolve only the restricted read surface.
Every host call rechecks explicit owner/repo and accepted arguments before
invoking the server, including calls outside the registry wrapper. Resources,
search across repositories, generic dispatch and dynamic toolsets are not
exposed by this integration. Extra resources are not allowlisted. Disabling
MCP leaves the native plugin functional. `GITHUB_ENABLED=false` disables both.

## Troubleshooting

- Disabled/unconfigured: check variable names and restart; inspect safe status,
  never print `.env` or ask an agent to show the token.
- Repository denied: add the exact `owner/repo` to both YAPOC's allowlist and the
  token's selected repositories. Do not broaden permissions as a first step.
- Authentication failed: privately replace an expired/revoked token.
- Permission denied/not found: verify selected repositories, organization
  approval, feature availability and the specific read permission.
- Rate limit: wait and retry later; increase polling interval. Writes are never
  retried automatically because a network failure may follow a successful write.
- Logs unavailable: check Actions read permission, retention and download host.
- MCP disconnected: check the installed executable and its version's supported
  tool names. The SDK/server is optional; native reads remain available. The
  connection error is deliberately generic to avoid credential disclosure.
- Settings still appear unconfigured after editing `.env`: restart the backend.
  The MCP config reader does not copy `.env` values into `os.environ`; this
  prevents an in-process restart from inheriting stale file values. Real process
  environment variables still intentionally take precedence over `.env`.
- Oversized response: narrow filters or lower page size. Files have a 2 MB API
  response limit; base64 overhead counts against it.

Enterprise API endpoints, persistent issue analytics, automatic local-SHA
inference and automatic Telegram delivery are intentionally outside this first
implementation. Use explicit health tasks and existing notification workflows.
