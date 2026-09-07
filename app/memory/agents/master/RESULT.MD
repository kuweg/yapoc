I'll proceed with Option 2 — full visual refresh with restructured navigation. Let me first map the exact files I need to touch so I can write a precise plan.Let me read the key files that define the current layout and styling.I have a thorough understanding now. This is a large redesign. Let me check the appStore to understand the tab state model, and check the remaining CSS tail to understand what other component styles exist.I now have a complete picture. This is a substantial redesign touching the app shell (App.tsx), the CSS design system (index.css), and the nav structure. Complexity ~8. I'll route through planning, which will decompose and execute via builder.

Let me write a precise, complete task spec for planning so the implementation is unambiguous.Planning is now decomposing and executing the redesign. I'll let you know when it's done.

While that runs, here's what's happening:

**The plan (Option 2 — full visual refresh + restructured nav):**

1. **Navigation un-clump** — replace the 11 flat tabs with a clean left **icon rail + collapsible sidebar** (Linear/Vercel-style), grouped into Primary / Insights / Knowledge / Comms sections.
2. **Visual refresh** — swap the retro-terminal look for a modern design system: sans-serif body text (mono kept for code/labels), softer rounded corners, more generous spacing, subtle shadows, no scanlines/pixel-art.
3. **Unify the header** — collapse the two duplicated header blocks into one clean header.
4. **Build + verify** — `npm run build`, no TypeScript errors.

I'll report back with the result and how to see it (just refresh the page — no backend restart needed).