# Connected workspace

Use the **Workspace** selector under the main header:

- **Reading:** Books and Notes.
- **Designing:** Whiteboard and Chat.
- **Reviewing:** Artifact gallery/preview and Chat.
- **Single view:** the normal tab layout.

On wide screens, drag the divider to resize the panes (30–70%). It also supports
keyboard arrows, Home/End, and double-click to return to 50/50. At 900px and below,
Book/Notes or Whiteboard/Chat buttons switch the visible pane. Both views remain
mounted: switching panes does not discard a chat or note draft. There is one chat
instance and one existing Notes editor; no second WebSocket or task submission
pipeline is introduced. Layout choice and width are saved in browser storage.
Navigating to a tab outside the pair temporarily shows a single view; navigating
back into the pair restores it. Choose Single view to stop using the pair.
The agent sidebar is hidden inside split Chat to leave room for the work.

## Resume home

**Home** in the left navigation provides links to your saved book position,
selected/recent Whiteboard, current conversation, and selected/recent note.
Opening a book from Home preserves its stored offset rather than treating it as a
new source-location jump. The resume banner returns to the last visited tab.
Conversation remains the default startup tab to preserve existing behavior.

Results to review use the existing unread task notifications. **Review** opens the
associated conversation (or Tasks when no local conversation exists). **Mark seen**
dismisses the notification; neither action approves or applies agent changes.
Home loads metadata on entry and explicit refresh; partial failures show a retry
message and do not prevent opening other tabs.

## Referenced context

Existing `@` mentions become inspectable chips above the composer. Click a chip
to inspect it; **×** removes exactly that occurrence from the message. Books show
the requested page/chapter range and a shortened source preview. Notes show a
shortened note preview; Whiteboards show their name, revision, node/edge counts
and sample nodes. Other kinds show their source-list metadata. Bare subsystem
mentions are described as subsystem references, not as attachments of every item.

These previews do not change resolution or permissions. References are resolved
by the existing submission path when sent. Missing or ambiguous sources are
shown as errors in the preview. Session-pinned notes and conversation history
remain additional context; the tray describes mentions rather than pretending
to be a complete inventory of the model's eventual prompt.

## Conversation common room

The existing agent building now has a **Common room** below its roof. It is tied
to the current conversation, not a new Project entity. It shows agents assigned
to that conversation's active tasks (and agents those tasks explicitly wait for).
Their avatars use the existing runtime status; a room does not spawn agents.
Click a resident to open its existing agent-flow inspector.

Artifacts appear as deliveries only when their source session matches or their
source task belongs to the conversation. Clicking a delivery opens its actual
artifact preview. Results without provenance are not guessed into the room.
The room reads recent task/artifact metadata when the session changes, on task
completion or reconnection, and on explicit Refresh room. It adds no polling loop.
At most six recent deliveries are shown; task membership uses the most recent
100 queue entries. Reduced motion disables delivery animations. The room can be
collapsed. Disconnection is shown instead of claiming live status.

## Validation

`npm --prefix app/frontend run build`

`poetry run python scripts/check_workspace_features_browser.py`

The browser check uses mocked resources and prevents task submissions. It checks
context range inspection/removal, all three layouts, draft retention, divider
keyboard access, reading resume, mobile pane switching, artifact preview
uniqueness, and room membership/provenance. Backend restart is not required for
these frontend-only changes.
