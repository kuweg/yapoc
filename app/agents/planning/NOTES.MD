# Planning Agent Notes

## Ping Button Feature — COMPLETE ✓
### Files modified:
- `app/backend/routers/agents.py` — Added POST /{name}/ping endpoint with full diagnostic info
- `app/frontend/src/agent-status/api/agentStatusClient.ts` — Added PingResult interface + pingAgent()
- `app/frontend/src/agent-status/components/detail/AgentActions.tsx` — Added 🏓 Ping button with state management

### Key implementation details:
- Backend reuses _pid_alive + _is_stale_status from services
- Returns 404 if agent dir not found
- Human-readable diagnostic messages for all states
- Frontend shows green (alive) / yellow (not alive) / red (error) results
- Button disabled during in-flight request, shows "Pinging…"
- Calls onRefresh? prop after successful ping

## Temp Agent Lifecycle — IN PROGRESS (Round 3)
- Created: app/agents/temp1–temp5 ✓
- Spawning: Master to spawn each with "What is your name?" ← WAITING FOR MASTER
- Responses: pending
- Deletion: pending

## PROMPT.MD Update Task — COMPLETE ✓
### Files updated:
- app/agents/master/PROMPT.MD
- app/agents/planning/PROMPT.MD
- app/agents/builder/PROMPT.MD

## CPU Usage Feature

## CPU Usage Feature — COMPLETE ✓
### Backend files modified:
- `app/backend/routers/metrics.py` — Added `AgentCpuMetrics` model, `_get_process_cpu_memory()` helper (psutil, 0.1s interval), `_build_agent_cpu_metrics()`, and `GET /agents/cpu` endpoint
- `app/backend/tests/test_metrics.py` — Added `TestListAgentCpu` class with 6 tests (200 status, list schema, both agents present, required fields, zero CPU for no-status agent, zero CPU for dead PID)

### Frontend files created/modified:
- `app/frontend/src/agent-status/components/metrics/CpuUsageChart.tsx` — SVG bar chart (no external lib), polls /api/metrics/agents/cpu every 5s, loading/error states
- `app/frontend/src/agent-status/api/agentStatusClient.ts` — Added `AgentCpuMetrics` interface + `getAgentCpuMetrics()` function

### Key implementation details:
- Uses psutil with 0.1s interval (non-blocking)
- Reads PID from STATUS.json per agent
- Dead/missing PID → cpu_percent: 0, memory_mb: 0
- SVG chart pattern (same as HealthSparkline — no charting lib installed)
- Note: test runner has pre-existing `aiofiles` import issue (unrelated to this feature)


## Light/Dark Theme Feature — COMPLETE ✓
### Files created:
- `app/frontend/src/store/themeStore.ts` — Zustand store, `yapoc-theme` localStorage key, default 'dark', `applyTheme()` sets `data-theme` on `<html>`
- `app/frontend/src/components/ThemeToggle.tsx` — ☀️/🌙 SVG icon button, light/dark styles

### Files modified:
- `app/frontend/src/index.css` — Added `[data-theme="dark"]` (line 11) and `[data-theme="light"]` (line 73) CSS variable blocks
- `app/frontend/src/App.tsx` — ThemeToggle imported and placed in 3 header locations
- `app/frontend/src/agent-status/components/DashboardHeader.tsx` — ThemeToggle added
- `app/frontend/src/agent-status/components/metrics/CpuUsageChart.tsx` — Uses `useThemeStore` directly for SVG colors

### Architecture:
- Zustand store (no React context/provider needed)
- `applyTheme()` called at module load time for instant theme on page load
- CSS variables cover both GitHub-style dark palette AND Tailwind zinc scale
- ThemeToggle placed in 4 locations total (App.tsx ×3, DashboardHeader ×1)

## Ticket Manipulation Tool

## Ticket Manipulation Tool — COMPLETE ✓ (Master PROMPT.MD needs self-update)
### Backend endpoints added to `app/backend/routers/tickets.py`:
- `PATCH /api/tickets/{id}/status` — StatusUpdate model (status: done/in_progress/pending/blocked)
- `POST /api/tickets/{id}/notes` — NoteAdd model (note: str, author: str)
- `PATCH /api/tickets/{id}/priority` — PriorityUpdate model (priority: low/medium/high/critical)
- `PATCH /api/tickets/{id}/assignee` — AssigneeUpdate model (assignee: str)

### New files created:
- `app/utils/tools/ticket_tool.py` — TicketTool class with mark_done/mark_in_progress/add_note/update_priority/update_assignee/get_ticket methods
- `app/utils/tools/README.md` — Tools directory documentation
- `app/tickets/.gitkeep` — Tickets storage directory
- `app/backend/tests/test_tickets.py` — 43 tests, all passing

### Sandbox constraint:
- Builder CANNOT write to `app/agents/master/` — sandbox policy blocks it
- Master must update its own PROMPT.MD with the Ticket Manipulation Tool section


## Retro Terminal UI Redesign — COMPLETE ✓
### Files modified:
- `app/frontend/src/index.css` — Full retro terminal theme (Share Tech Mono font, CSS variables, scanlines, blink cursor, retro buttons/cards/badges/nav/tables/scrollbars)
- `app/frontend/src/App.tsx` — Removed rounded corners, monospace nav
- `app/frontend/src/components/ThemeToggle.tsx` — Retro [DARK]/[LITE] text button
- `app/frontend/src/agent-status/components/AgentCard.tsx` — No rounded corners, terminal borders
- `app/frontend/src/agent-status/components/DashboardHeader.tsx` — Terminal prompt prefix
- `app/frontend/src/agent-status/components/StatusBadge.tsx` — Uppercase, monospace, no radius
- 27 additional component files — rounded corners removed, monospace applied

### Key design tokens:
- `--color-accent: #FFB633` (amber phosphor)
- `--color-bg-primary: #0a0a0a`
- `--font-mono: 'Share Tech Mono', 'Courier New', monospace`
- Scanline effect via repeating-linear-gradient on body
- Blinking block cursor via @keyframes blink
- Amber glow on running/active states via text-shadow
