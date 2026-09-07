# Blank chat after reconnecting a busy session

## Cause

Replaying the conversation from the reported screenshot reproduced a completely
empty React root and `Maximum update depth exceeded` in `ChatPanel`'s background
completion effect. The same failure occurred after reloading the page.

`state_sync` and `session_sync` recover completed tasks into `pendingCompletions`.
The chat effect synchronously appended or skipped the first completion, then
called `clearLastCompletedTask()`. That call exposed the next queue entry and
immediately triggered the effect again. A sufficiently large, finite backlog
exceeded React's nested-update limit. Even already-delivered or unrelated tasks
contributed to this chain. Without an error boundary, React removed the entire
application, leaving only the page's dark background.

This explains why another browser could reproduce the problem: reconnecting to
a busy conversation recreates the backlog; the problem is not browser-specific.

## Fix

The completion effect now schedules each delivery on the browser event loop,
letting React finish its current update before processing the next queue entry.
Cleanup cancels a pending delivery when the effect is replaced or unmounted,
including StrictMode replay. The completion remains queued for the next effect.
Session ownership, completion receipts, message ordering, and interactive task
group handling retain their existing behavior.

The change is frontend-only. Refresh an affected browser tab to load it; clearing
chat history or restarting the backend is unnecessary.

## Verification

- Replayed the affected conversation using the live backend in an isolated
  Playwright Chromium profile; checked initial load, offline/online reconnection,
  and reload. No agent task or provider call was initiated.
- TypeScript check and Vite production build passed.
- Isolated 400-task WebSocket replay drained successfully: 200 owned replies
  appeared once, 200 unrelated completions stayed out of chat. Duplicate replay
  and reload did not resurrect trimmed history; no browser exceptions occurred.
- All five existing Playwright restart-delivery scenarios passed against the
  updated production build (`scripts/check_restart_chat_browser.py`).
