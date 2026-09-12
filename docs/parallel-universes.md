# Parallel Universes

In Conversation, open **+ → Try parallel approaches**. An expanded task also has
**Try parallel approaches**. Describe one objective, two approaches, shared
requirements and a required check command. The default check builds YAPOC's
frontend. Time and estimated spending limits apply to each attempt; the total
spending allowance is split equally. Pricing must be known for the builder's
configured model. Billing is observed after a model response, so an in-flight
response can overshoot the estimate. Each run also has a 30-turn/200,000-token
limit. No model calls happen until the user starts a comparison.

A single comparison card appears in the conversation. Open it for side-by-side
Preview, Changes, Checks and Activity tabs. Phones use A/B tabs. Each universe
has its own builder identity and person on the Builder floor. Click the person
for its flow or the letter badge for the comparison. Stop A, B, or both without
stopping the ordinary builder. Only one comparison runs at a time in this first
release. New comparisons do not delete previous results.

## Isolation and existing work

The backend uses a temporary Git index to capture the same baseline for both
attempts, including nonignored uncommitted files. It does not change the user's
index, branch or working files. Known credential paths, runtime data and agent
memory are excluded. Each run gets a Git worktree and branch, independent
context, logs, usage and dependencies. The existing BaseAgent tool loop and
security classification are reused, with a fixed tool set: file read/list/write/
edit and sandboxed shell. No plugin, MCP, notification, deployment or delegation
tools are supplied. The trusted worker code runs from the host installation;
candidate Python code cannot replace that worker's imports.

The worker selects its workspace before importing agent modules so module-level
paths and stores belong to that workspace. Agent configuration is frozen at
launch; live ordinary agents retain their existing configuration and paths.
Only Linux with working bubblewrap/prlimit can start these isolated comparisons.
macOS/Windows users need the Linux runtime; native unsandboxed execution is not
used for universes. The Git worktree backend requires a Git checkout; seeded
Docker workspaces without Git history must first be initialized as repositories.

Static frontend previews use separate loopback ports, a sandboxed iframe and
blocked application-API connections. They are for local browser use, not full
backend environments. Backend-dependent interactions are unavailable. After a
restart, **Start preview** reopens a completed preview. A maximum of four preview
servers stays open; starting another closes the oldest server, retaining files.
No generated preview is loaded into the main dashboard's origin.

## Choosing and recovery

Choose a completed candidate whose required check passed. Selection refuses if
HEAD or the user's baseline files have changed in the meantime; start another
comparison with those edits rather than silently discarding them. It creates
`yapoc/integration/<comparison-id>` from the chosen candidate and repeats the
check in an isolated integration worktree. The branch is ready for review when
the check passes. **It never checks out, merges, pushes or deploys that branch
automatically.** The baseline includes the user's uncommitted changes; review the
whole branch before merging. Git hooks are disabled for service-owned operations.

Cancellation preserves partial files and activity. Backend shutdown cancels
workers and checks; unexpected restarts show unfinished work as interrupted.
There is no automatic retry that could double spending or repeat side effects.
Metadata and worktrees live under `data/universes/<id>/`. Existing data is retained.
The normal task dispatcher does not consume these runs or recover them as master
tasks. Optional metadata errors do not prevent ordinary agents from loading.

Revision-in-place, branching a third alternative, automated evaluation and
combining alternatives are deferred. Start a new comparison to revise the brief.
The initial release supports two isolated builders and an explicit integration
branch; it does not create two live application backends.

## Validation

`poetry run pytest app/backend/tests/test_universes.py -q` uses temporary Git
repositories and mocked model responses, with no paid API calls. It checks dirty
snapshot preservation, independent edits, guarded integration, failed checks,
restart presentation, restricted worker tools and preview traversal protection.

`npm --prefix app/frontend run build` checks TypeScript and creates the release UI.
`poetry run python scripts/check_universes_browser.py --dist app/frontend/dist`
checks launch, independent cancellation, comparison tabs, selection and mobile.
The agent-building regression is `scripts/check_office_browser.py`.

## Rejecting and removing attempts

In Compare, **Discard both** stops both attempts, closes their previews, and
removes their residents from the building. Files and comparison history remain
available for review, but discarded candidates cannot be chosen.

**Clean up saved work** then asks you to confirm **Delete saved work**. This
permanently removes the comparison's two worktrees, candidate branches and history.
It preserves the main workspace and unrelated branches. Cleanup refuses moved
worktrees or branches checked out elsewhere; resolve those manually before retrying.
Comparisons with an integration branch cannot be discarded or cleaned up through
these controls, preserving the result you already chose.
