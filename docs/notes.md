# Notes

Open **Notes** in the Workspace section of the sidebar, or use the command
palette. Notes are ordinary UTF-8 Markdown files in `app/projects/notes/`.
YAPOC's agents can read and edit the same files with their existing file tools.
This folder is separate from agent-owned memory and is excluded from Git by
the existing `app/projects/` ignore rule.

## Write and connect

- Create a named note or import a `.md` file. Its filename is the note's link target.
- Choose Preview, Edit, or Split. Changes autosave after a short pause; Save
  and Ctrl+S / Cmd+S save immediately. Unsaved drafts are also retained in the
  current browser where storage is available.
- Write `[[Project plan]]`, `[[Project plan|a friendly label]]`, or
  `[[Project plan#Next steps]]`. Ordinary `[plan](Project%20plan.md)` links
  also navigate within Notes. Clicking an unresolved wikilink offers to create it.
- Use Insert note link to pick a target. The footer shows incoming backlinks
  and outgoing wikilinks. Code examples do not create wikilink graph edges.
- Open Links graph to explore the connections. Drag nodes, pan, zoom, or click
  a node to open it. Linked notes only focuses on the selected note's neighborhood.
- Download exports the current draft as Markdown. Trash moves the saved file
  into `.trash` rather than permanently deleting it; restore it with filesystem
  tools and refresh the note list.

The renderer uses YAPOC's React Markdown stack: CommonMark, GitHub-style tables,
task lists, strikethrough, fenced code with syntax highlighting, plus wikilinks,
`==highlights==`, and `> [!NOTE]`-style callouts. It does not embed Obsidian's
application or plugin runtime. Raw HTML is not executed. Obsidian embeds,
Dataview, MathJax, and automatic link rewriting on filesystem rename are not
implemented. The graph indexes wikilinks and local Markdown note links.

## Use notes with Master

**Add to chat** appends an editable `@note:...` reference to the current composer
and returns to the conversation. It preserves the existing draft and does not
send a message. The backend resolves the reference when the task is submitted.

**Pin as context** associates a note with the current conversation, creating a
conversation if needed. Pinned notes appear above the chat composer. Each new
task receives their latest saved contents, filename, and path. Click a chip to
open the note; use its × action to unpin. A new conversation starts without pins.
Pins are saved with the session in the current browser.

**Save as note**, beneath an assistant response, opens a named-note creation
form with the response as Markdown. This makes it easy to retain a result,
connect it to existing knowledge, and bring it into another task.

Notes are reference material, not global system instructions. They are included
in the submitted task only. An already running task keeps the snapshot it
started with; stream reconnection reuses that snapshot instead of resubmitting
or changing its context. Unpinning a note prevents future attachment but does
not erase information already used in the conversation's history.

## Persistence and limits

The editor reads the shared folder on refresh and checks a content revision on
every save. If another browser or agent changes a file, the UI preserves your
draft and reports a conflict. Download the draft or explicitly discard it and
reload the saved version before reconciling changes.

Individual notes are limited to 200 KB in the editor. Tasks accept up to 12
selected notes and 64,000 characters of serialized note context. Missing or
oversized notes reject task creation with a visible error rather than silently
omitting reference material. The graph displays up to 250 nodes at once.
The library search matches names, excerpts, and outgoing link names.

API: `GET/POST /notes`, `GET/PUT /notes/{filename}`, and
`POST /notes/{filename}/trash`. Updates and trash requests require the current
`revision`. `/task` and `/task/stream` accept a `note_ids` array; their durable
metadata records which note revisions were attached.

## Verification

```bash
poetry run pytest app/backend/tests/test_notes.py -q
cd app/frontend
pnpm exec tsc -b --pretty false
pnpm exec vite build --outDir /tmp/yapoc-notes-build
cd ../..
poetry run python scripts/check_notes_browser.py --dist /tmp/yapoc-notes-build
```

The browser scenario uses the real notes API with a temporary folder and a
simulated task queue. It does not run agents or modify the user's notes.
