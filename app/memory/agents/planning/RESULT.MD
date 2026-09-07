I'll start by researching the existing Preview tab/component and markdown rendering flow to understand what's already there.I found the existing markdown preview work. There's a Vault markdown preview (VaultFileViewer.tsx) and a MermaidBlock. Now I need to find the "Preview tab" specifically. Let me look at the FileViewerPane and check for a "Preview" tab concept.The Vault has a full markdown preview (Edit/Split/Preview slider). But the task says "Preview tab" — this likely refers to the FileViewerPane (the file preview pane used by artifacts/workspace). Let me check the WorkspacePanel and ArtifactsPanel to understand the "Preview tab" concept, and check the fileViewerStore.Now let me look at the ArtifactsPanel to understand the "Preview tab" concept there, and check how artifacts are previewed.Now I understand the flow. The "Preview tab" is the FileViewerPane (the file preview pane). When a markdown file is selected (via artifacts or workspace), it renders as plain text (`preview.kind === 'text'` → `<pre>`). The task wants a "Preview" button that renders markdown.

Let me check the backend `/api/files/preview` endpoint to understand what data is returned (does it include ext/kind/content?).Now I have full understanding. The backend `/api/files/preview` returns `ext` (e.g. `.md`) and `content` for text files. The FileViewerPane currently renders text as plain `<pre>`. 

The task: add a "Preview" button in the FileViewerPane (the "Preview tab") that renders markdown content. When the file is a markdown file (`.md`/`.markdown`), show a "Preview" button that toggles markdown rendering vs raw text.

Let me check what markdown dependencies are available and how MessageBubble uses ReactMarkdown (to reuse conventions).`react-markdown` and `remark-gfm` are already installed. Now let me check the MessageBubble markdown components to understand the styling conventions (dark mode, code blocks) so I can reuse them.I have enough context. The cleanest, most self-contained approach: modify `FileViewerPane.tsx` to add a "Preview" toggle button that appears when the file is markdown (`.md`/`.markdown`), switching between raw text and rendered ReactMarkdown. This is the "Preview tab" (FileViewerPane is the preview pane).

Let me check the index.css for existing markdown preview styles I can reuse (vault-md-preview).There's a complete `.vault-md-preview` CSS class with dark-mode styling. I can reuse it directly. Now I have everything I need. Let me implement the change to `FileViewerPane.tsx`.

The plan:
1. Add `ReactMarkdown` + `remarkGfm` imports.
2. Add a `viewMode` state (`'raw' | 'preview'`), defaulting to `'raw'`.
3. Detect markdown via `preview.ext` (`.md`/`.markdown`).
4. Add a "Preview"/"Raw" toggle button in the header (only when markdown).
5. Render markdown via ReactMarkdown with `className="vault-md-preview"` when in preview mode.

Let me implement this directly since it's a focused, well-understood change.Now reset the markdown toggle when the file changes:Now add the markdown detection and the toggle button in the header, plus the rendering logic. Let me update the header and body:Now let me verify the full file reads correctly and then build.The change looks correct. Now let me build the frontend to verify.Build passes (exit 0, 1916 modules, no TS errors). The feature is complete and verified.

Let me log the delegation decision and report back.Task complete. I implemented the Markdown Preview button in the file preview pane (FileViewerPane, the "Preview tab" used by Artifacts and Workspace).

**What was done:**
- Researched existing markdown work first — confirmed `react-markdown` + `remark-gfm` were already installed and that the Vault's `.vault-md-preview` CSS provides complete dark-mode markdown styling.
- Modified `FileViewerPane.tsx` to add a **Preview/Raw toggle button** that appears only for `.md`/`.markdown` files, rendering content via ReactMarkdown with GFM support.
- Verified with `npm run build` — exit 0, 1916 modules, no TypeScript errors.

**Files changed:** `app/frontend/src/components/FileViewerPane.tsx` (single file, no unrelated code touched, dark mode preserved).