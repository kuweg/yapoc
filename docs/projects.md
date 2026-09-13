# Projects

Projects link existing books, notes, whiteboards, workspace files, web links and
artifacts to a purpose. Open **Projects** in the sidebar, choose **New project**,
and write a name, description and brief. Use **Sources** to link resources.
Resources can belong to several projects; unlinking or deleting a project never
deletes its underlying resources or conversations.

Choose **New project conversation** from Overview, or link a local conversation
in Conversations. A conversation belongs to one project. Normal conversations
remain independent. Opening a project does not reassign an existing conversation.
Results shows artifacts with an explicit source-session link to its conversations.
No provenance is guessed and opening a result does not apply changes.

## Context

The composer displays the project associated with the current conversation.
Expand its context controls to inspect the brief, source references and included
note excerpts. Uncheck an item to exclude it from the next accepted message.
Exclusions reset after the task stream accepts the request; a failed request
keeps them available for retry. Explicit mentions and pinned notes still follow
their existing paths and can independently reference an excluded project source.

The brief is included by default. Notes can be marked **Always include** (up to
eight, first 4000 characters each, with revision and truncation metadata). Other
resources contribute identifiers and labels only. No whole-book injection or
automatic URL fetching happens here. Agents inspect references with existing
tools and are instructed to cite source locations; this is not a new retrieval
or citation-validation subsystem. Current source content is resolved when sent.
An unavailable always-included note requires excluding it or updating the source.

The backend verifies conversation membership and records project ID/revision and
exclusions in task metadata. The actual brief/source snapshot is part of the
durable queued prompt. SSE reconnection replays that existing task even if the
project is subsequently changed or deleted. Existing permissions and tool policy
continue to apply. Source content is identified as reference material, not system
instructions.

## Continuing work

After using a workspace, return to Projects to save its layout, pane ratio,
conversation and selected book/note/canvas in browser storage. **Continue** or
**Continue workspace** restores that snapshot. Reading position remains in the
existing Books store. Workspace preferences are device-local; project metadata
lives on the backend. Conversation history retains its existing local-history
limits; Projects does not introduce cross-device conversation synchronization.

## Storage and operation

Metadata is stored in `data/projects.sqlite3`, under the configured execution
root, and is covered by the existing data ignore rule. Back up this file together
with the actual resources. SQLite transactions and revision checks prevent silent
concurrent overwrites; on conflict, refresh and reapply your edit. The UI's source
directory has an explicit gitignore exception, not a blanket unignore of projects.
No credentials, new dependencies or environment variables are required.

API: `GET/POST /projects`, `PUT /projects/{id}`, and
`DELETE /projects/{id}?revision=N`. Task submissions optionally accept
`project_id` and `project_excluded`. Project routes precede the dashboard fallback.
Backend restart is required when installing this change; rebuild/refresh the UI.

## Initial release scope

This release delivers project CRUD, briefs, linked sources, conversations, results,
visible context controls and workspace restoration. Milestone planning/review,
a project-wide animated room and project covers remain the next phase. The
existing conversation common room continues to work without changing agent
execution. There is no new background agent or polling loop.

## Validation

- `poetry run pytest app/backend/tests/test_projects.py app/backend/tests/test_notes.py -q`
- `npm --prefix app/frontend run build`
- `poetry run python scripts/check_projects_browser.py`
- `poetry run python scripts/check_workspace_features_browser.py`

The Projects browser test mocks mutations and task execution. Backend tests use
an isolated temporary database and cover revision conflicts, shared resources,
conversation membership, bounded context, exclusions, missing notes,
non-destructive deletion and durable task replay.
