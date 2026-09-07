I'll verify the build completed cleanly before reporting.Done. The agents list now lives on the **right side** of the Chat tab.

**What changed:**
- `App.tsx` — moved `<AgentSidebar />` from before the chat `main` to after it, so it renders as a right-hand panel.
- `AgentSidebar.tsx` — flipped its border from `border-r` to `border-l` so the divider sits on the correct (left) edge.

**Result:** The Chat tab now has a single left rail (nav) + chat in the middle + agents list on the right — no more double-left-column clump.

Build passed clean (`tsc -b && vite build`, exit 0). Frontend-only — **refresh the page** to see it.