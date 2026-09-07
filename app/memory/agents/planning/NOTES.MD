
## 8-Feature Hermes Gap Batch Plan
# 2026-09-01 — 8-Feature Hermes gap batch — Implementation Plan

Ordered decomposition (dependency: 3 → 1,2,4,5,6 → 7 → 8).

FEATURE 3 (LAY FIRST — foundation): Structured result contract.
- New helper app/agents/base/result.py: schema {status, summary, files[], artifacts[]} + coercion of free-text → {status, summary} when not JSON (backward compat).
- Used by delegation tools (1) and child budget (2).

FEATURE 1: delegate_task runtime tool (ANY agent can fan out mid-turn).
- Add tool in app/utils/tools/delegation.py next to SpawnAgentTool/WaitForAgentTool.
- Reuse existing peer-delegation check (_parse_delegation_targets, _UNRESTRICTED_SPAWNERS), checkpoint, concurrency cap.
- Returns structured result routed into calling agent's context (depends on F3 return shape). Enforce allowed_tools whitelist.

FEATURE 2: Child-side token budget.
- parent sets per-child token/$ cap in spawn/delegate call; enforced in app/agents/base/runner.py run loop + BaseAgent (app/agents/base/__init__.py).
- child hard-stops + returns partial results when cap exhausted. Integrates with cost_governor.is_autonomous_budget_exhausted so it cannot exceed global daily budget.

FEATURE 4: Time-based memory decay.
- settings memory_decay_days (exists: memory_max_age_days=7). Archive old MEMORY.md entries to cold store (data/memory_archive/ or librarian). Trigger: cron tick/startup/librarian sweep. Preserve embedded index or re-index lazily.

FEATURE 5: Survivable session context (CONVERSATION.md).
- Freeze per-session working context to CONVERSATION.md at session complete/restart; restore on reload. Beyond RESUME.md agent-state recovery.

FEATURE 6: Negative knowledge store.
- New section in shared KNOWLEDGE.md (or data/negative_knowledge.md), entries {approach, why_rejected, date, replaced_by}. Wire librarian to route failed/abandoned approaches. Seed with rejected approaches (lmstudio for some agents, dead claude-haiku model).

FEATURE 7: Budget-aware autonomous mode (PARTLY EXISTS).
- cost_governor.py already has is_autonomous_budget_exhausted(), get_autonomous_spend_today(). dispatcher._check_goals already gate. Extend main.py _cron_tick + goals runner + doctor to coordinate against ONE daily budget (not per-job). Add settings.daily_autonomous_budget_usd.

FEATURE 8: Escalation ladder on repeated failure.
- Track consecutive_failures per cron job in cron state (data/cron_runs.json or new data/cron_failures.json). On threshold (settings) → disable job + page user (Telegram/UI). Health-alert: 'agent fails twice in a row' (user already wants this).

KEY FILES:
- app/utils/tools/delegation.py — F1, F2 (cap in call), F3 return
- app/agents/base/result.py — F3 (NEW)
- app/agents/base/runner.py — F2
- app/agents/base/__init__.py (BaseAgent) — F2
- app/config/settings.py — F2,F4,F7,F8 config keys
- app/config/agent-settings.json — add delegate_task to agent tool lists
- app/utils/cost_governor.py — F7
- app/backend/main.py _cron_tick — F8 (track failures), F7 (budget gate)
- app/utils/goal_proposer.py — F7
- shared KNOWLEDGE.md — F6
- librarian agent — F6 wiring, F4 sweep
- data/memory_archive/ — F4 cold store
- CONVERSATION.md — F5

Backend must restart after each feature group's code mutation (server_restart via builder).


## Features B+D (UI observability)
2026-09-01 — Features B+D sequential re-delegation: Task A (backend nudge) now CONFIRMED landed. agents.py has perform_nudge helper + /{name}/nudge route; websocket.py has agent_action branch. Task B (AgentCard nudge button + nudgeAgent client fn) had been lost in parallel collision — need to confirm whether it has since been re-delegated and landed. Remaining: verify Task B frontend, then Feature A (if any) complete.

## Mermaid rendering fix (2026-09-07)
Root cause of "Mermaid markdown injections unsupported": MessageBubble.tsx MARKDOWN_COMPONENTS.pre/code rendered fenced ```mermaid blocks as plain <pre><code> — no language-mermaid detection, so diagrams appeared as raw source. The tool-rendered path (render_mermaid tool_done → {kind:'mermaid'} part → MermaidBlock) was ALREADY fully wired across ChatPanel.applyPendingEvents, LiveAgentTranscript.eventsToChatParts, PartsChain, MessageBubble.renderPart, and TaskGroupBubble. So the gap was ONLY the markdown path.

Fix: overrode MARKDOWN_COMPONENTS.pre in MessageBubble.tsx to detect a code child with className matching \blanguage-mermaid\b, extract its text via new codeChildrenToText helper, and mount <MermaidBlock source=.../> instead of <pre>. Both ReactMarkdown usages in MessageBubble (structured-parts path line ~355 and plain-content path line ~377) share MARKDOWN_COMPONENTS, so both covered. VaultFileViewer.tsx also uses ReactMarkdown but is for viewing .md files, not chat — out of scope.

Build: pnpm unavailable in builder shell allowlist; `npm run build` (tsc -b && vite build) from app/frontend succeeded exit 0, regenerated dist/assets/index-FY_e_8Qe.js + index-CqqKYbxU.css. Frontend-only → no backend restart (per task).

## Textual-ingestion feature batch (2026-09-07) — architecture research
Existing patterns to reuse:
- Attachment pipeline: uploads.py store_upload → _extract_text (text/docx/PDF) → build_attachment_injection (suffix text appended to prompt + meta list for SSE 'attachments' event). Called in routers/tasks.py /task/stream when request.attachments present.
- Frontend: ChatInput stages files → ChatPanel.sendMessage uploads via /api/upload (uploadFiles) → gets ids → streamTask(task, history, sessionId, attachmentIds) → SSE. MessageBubble.AttachCards renders image thumbs, PDF card w/ modal, else generic 📄 download chip. Attachment type in api/types.ts.
- Agent tools: app/utils/tools/*.py, registered in TOOL_REGISTRY (__init__.py). Master tools granted in BOTH app/agents/master/CONFIG.yaml AND app/config/agent-settings.json (authoritative). New tools must be added to both + TOOL_REGISTRY.
- Artifacts: render_chart → {kind:'chart'} part → ChartBlock; render_mermaid → {kind:'mermaid'} → MermaidBlock. A new document-analysis tool could return {kind:'chart'} JSON for rendering.
- Vault (routers/vault.py) already renders PDF/images/text from app/projects with sandbox path check.
- Env libs present: docx, pypdf, mailbox, email, zipfile, tarfile, lxml. MISSING: openpyxl, python-pptx, icalendar, py7zr.
- Tests: app/backend/tests/*.py (pytest, asyncio_mode=auto). pyproject dev deps include pytest.
- Backend restart required after Python/config changes; frontend-only needs npm run build only.
- Learned rule: NEVER parallel spawns to singleton builder — run builder tasks SEQUENTIALLY.


2026-09-07 — Textual-ingestion deps LANDED (keeper): pyproject.toml lines 38-41 now have openpyxl 3.1.5, python-pptx 1.0.2, icalendar 5.0.14, py7zr 0.22.0 (poetry add, installed, imports verified). Env now has all needed libs: docx, pypdf, openpyxl, python-pptx, icalendar, py7zr, mailbox, email, zipfile, tarfile, lxml. Next builder phases: backend _extract_text branches for xlsx/pptx/ics/7z + frontend rendering.

## In-chat file/artifact viewer sidebar feature (2026-09-07)
Root cause of /api/files/download 404: NO /files/download endpoint existed in app/backend/routers/files.py (only /tree,/read,/image,/upload).
BACKEND PHASE DONE: files.py now has _classify/_media_type helpers + GET /files/download (inline=1 for iframe) + GET /files/preview (text content). Tests in app/backend/tests/test_files_viewer.py (8 passed). Sandbox via existing _sandbox() (traversal + .env/.pem/.key rejection). Backend NOT restarted (builder lacks server_restart — master must restart + HTTP-verify).
REMAINING: frontend FileViewerPane right-side sidebar + store + MessageBubble file-link detection; then restart+verify (needs master server_restart).

## Artifact system
## Artifact system implementation (2026-09-07)
Researched existing architecture before decomposing:
- Uploads (data/uploads + uploads.json): chat attachments, owner-scoped, dedup, thumbnails. Served /api/upload/{id}. NOT the target — generated files are the gap.
- Generated files (data/generated/): produced by generate_image tool (image_gen.py) and document_processor agent. NO metadata registry, NO provenance, NO versioning. Served by path via /api/files/download|preview|image (files.py router, sandboxed to project_root).
- File viewer: FileViewerPane + fileViewerStore (selectFile by path) + MessageBubble link detection (isProjectFilePath). Mounted in App.tsx line 187 when selectedFile set.
- files.py has module-level helpers _classify/_media_type/_sandbox (importable, no circular dep).
- data/ fully gitignored (except .gitkeep) → artifacts registry in data/ won't pollute git.
- Backend tests: app/backend/tests/test_files_viewer.py pattern (FastAPI TestClient include_router). Frontend build: npm run build (tsc -b && vite build) from app/frontend.
- data/generated currently has: document_processor_test.md, why_yapoc_is_great.pptx, yapoc_message_bus_queue.pdf, create_yapoc_presentation.py.

DESIGN (minimal, non-duplicative):
1. app/backend/services/artifacts.py — durable registry data/artifacts/artifacts.json (atomic). Record: {id,name,path,kind,mime,size,sha256,created_at,updated_at,source_agent,source_task,source_session,version,parent_id,versions[],metadata}. Version lineage keyed on filename stem. backfill_scan() auto-indexes data/generated files not yet registered (source_agent="backfill") → backward compat for existing generated files. register_artifact() for explicit provenance.
2. app/backend/routers/artifacts.py — GET /artifacts (list+filter), GET /artifacts/{id} (detail), GET /artifacts/{id}/versions, POST /artifacts/register. Content serving REUSES /api/files/* (no duplication). Path sandboxed to data/generated.
3. Register in routers/__init__.py + main.py include_router.
4. Tests: app/backend/tests/test_artifacts.py.
5. Frontend: artifacts browser panel (list/detail/versions) + open in existing FileViewerPane via selectFile. Reuse vault list-panel patterns.
6. Backend restart + frontend build + HTTP verify (needs master server_restart — builder lacks it).


## Artifact system
Artifact system — phases 1+2 DONE, phase 3 (restart+verify) needs master.
- Backend: services/artifacts.py + routers/artifacts.py + tests (5 passed) + files_viewer regression (8 passed). Real backfill indexed 4 data/generated files into data/artifacts/artifacts.json. main.py imports cleanly.
- Frontend: artifacts/{types,api,ArtifactsPanel}.tsx + store/artifactsStore.ts + App.tsx ARTIFACTS button + panel mount. npm run build exit 0.
- Remaining: backend restart (master server_restart) + live HTTP check of GET /api/artifacts, /{id}, /{id}/versions, POST /register, and frontend panel load. Builder/planning lack server_restart — relay to master.


## Control-Room Human Interface (2026-09-07)
Research findings for the 8-requirement "control-room human interface" task.

ALREADY IMPLEMENTED (reuse, do NOT duplicate):
- Req 1 (drag-drop multi-file): ChatInput.tsx full drag-drop/paste/picker, MAX_FILES=10, two-phase /api/upload.
- Req 7 (voice): voice.py + voice_service.py (OpenAI Whisper whisper-1 STT + tts-1/onyx TTS), useBackendSTT.ts (MediaRecorder→/api/stt), ChatPanel mic 🎤 + 🔊 read-aloud + VoiceSettings. Fully wired, NOT browser speechSynthesis.
- Req 8 (charts/Mermaid/HTML/PDF/images): ChartBlock, MermaidBlock, MessageBubble MARKDOWN_COMPONENTS (mermaid fenced-block detection, pptx/pdf/file-path buttons), FileViewerPane, InlineViewerModal.
- Req 3 partial (live graph): LiveTopologyHUD + /ws/graph WS + graph_event_bus (nodes/edges/running states). MISSING: tool calls, queue state, costs, elapsed per node.
- Req 6 partial (mobile-first tasks/artifacts): TasksPanel + ArtifactsPanel exist.
- Artifacts: artifacts.py router + ArtifactsPanel + artifactsStore.
- Agent streaming: SSE /api/task/stream + WS agent activity + PartsChain execution trace.
- Costs/elapsed: metrics.py (/usage, /cost-history, /active-time, /observability), CostBar, CostExplorer, TraceWaterfall.

GENUINE GAPS (what to build):
- Req 2: @file.pdf / @repo / @artifact chat references — NO @-mention parsing/autocomplete anywhere.
- Req 4: "Explain this run" timeline (request→plan→tools→files→verification) — no per-run explain view.
- Req 5: one-click rerun/resume/rollback/export — /export listed in help but NOT implemented; no rerun/resume/rollback buttons.
- Req 3: enrich live graph with tool calls + queue state + costs + elapsed.

Key files: ChatInput.tsx, ChatPanel.tsx, MessageBubble.tsx, LiveTopologyHUD.tsx, TasksPanel.tsx, commands.py, tasks.py, metrics.py, artifacts.py, useStream.ts, api/client.ts.
Backend restart required after Python changes (builder lacks server_restart — master must restart).


## Control-Room Final Plan
FINAL DECOMPOSITION (4 phases, sequential builder delegation):

Phase A (Req 2 @-references): Backend resolve @file.pdf/@repo/@artifact → attachments/context; frontend @-mention autocomplete in ChatInput.tsx (alongside existing /-command autocomplete). NEW backend endpoint or extend uploads resolution. Frontend: parse @file/@repo/@artifact tokens, fetch suggestions, render chips.

Phase B (Req 4 explain-run timeline): New RunTimeline component rendering request→plan→tools→files→verification from existing Message.parts (TaskPart[]: thinking/tool/chart/mermaid) + taskCompletion meta. Mount in MessageBubble or a modal.

Phase C (Req 5 rerun/resume/rollback/export): Add /export command to commands.py (web UI) returning conversation as downloadable text; add rerun/resume/rollback buttons on task cards/messages (rerun = resend prompt; resume = /resume session; rollback = git revert via existing keeper flow; export = download conversation).

Phase D (Req 3 enrich graph): Extend LiveTopologyHUD to show tool calls, queue state, costs, elapsed per node from graph_event_bus + metrics.

Order: A → B → C → D. Each phase: spawn builder, wait_for_agent, verify, then next. Backend restart needed after A & C (Python changes) — master must restart (builder lacks server_restart).


## Workspace task-input surface (2026-09-07)
## Workspace → task-input surface feature

### Existing infra (reuse, don't duplicate)
- `@file <name>` mention → `resolveMentions` (lib/mentions.ts) → attachmentIds → ChatInput onSubmit → ChatPanel.sendMessage → streamTask → POST /api/task/stream `attachments` → backend `build_attachment_injection` (services/uploads.py) → master → routes to document_processor (master PROMPT.MD already says "any user-file interaction → document_processor").
- "Open in viewer" already exists: fileViewerStore.selectFile({path,name}) → FileViewerPane.
- Artifacts registry (services/artifacts.py) supports metadata + source_task/source_session linking; register via POST /api/artifacts/register.
- WorkspacePanel.tsx currently: list/upload/filter/select/preview/Download/Copy ID only.

### Gaps to fill
1. `resolveMentions` matches @file by NAME only — need `@file:<id>` (and id-based) resolution so "Use in chat" can insert a stable id reference.
2. No bridge WorkspacePanel → ChatInput to insert text. ChatInput ref handle has setText but no global access. Need a shared store bridge (extend workspaceStore or new store) with a "pending insertion" that ChatPanel/ChatInput consumes.
3. No action buttons (Extract/Summarize/Analyze/Convert/Generate from) + processing state + artifact linking.

### Plan (delegate to builder SEQUENTIALLY — singleton collision rule)
- A: backend — extend uploads router/service to support id-based resolution + a "process" endpoint that enqueues a document_processor task with source-file linkage (or reuse /api/task/stream with attachments + a source_file metadata). Add tests.
- B: frontend — extend mentions.ts for @file:<id>; add workspaceStore bridge (pendingInsertion); WorkspacePanel action buttons + processing state + artifact link display.
- C: frontend build + verify.

