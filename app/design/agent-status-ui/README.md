# YAPOC Agent-Status UI — Design Spec

**Version:** 1.0  
**Date:** 2026-04-10  
**Status:** Draft — ready for implementation  
**Audience:** Frontend developers implementing the YAPOC monitoring dashboard

---

## Purpose

This design spec defines a brand-new real-time monitoring dashboard for the YAPOC multi-agent orchestration system. The dashboard gives developers a single-pane view of all agent states, health, tasks, and activity — replacing the current workflow of manually reading `STATUS.json`, `HEALTH.MD`, and `TASK.MD` files from the terminal.

YAPOC runs 7 agents (`master`, `planning`, `builder`, `keeper`, `cron`, `doctor`, `model_manager`) as independent processes, each writing state to files under `app/agents/{name}/`. This UI reads those files via a backend API and presents them in a live-updating, dark-themed developer dashboard.

---

## Spec Files

| File | Description |
|------|-------------|
| [`layout-spec.md`](./layout-spec.md) | Full layout and visual hierarchy: window zones, ASCII mockups of the main table and detail panel, filter/sort navigation, and compact vs. comfortable density modes |
| [`color-spec.md`](./color-spec.md) | Complete color palette (dark + light), status color mapping with hex values, health indicator colors, WCAG AA contrast ratios, badge geometry, animation keyframes, and color usage rules |
| [`realtime-spec.md`](./realtime-spec.md) | Real-time update architecture (polling + SSE), polling intervals per data type, TypeScript data models, backend API spec (5 endpoints), stale data / connection loss handling, and live event log design |
| [`component-spec.md`](./component-spec.md) | Full React component tree with TypeScript props interfaces, responsive breakpoints (desktop/tablet/mobile), Zustand store shape, polling hook implementation, file structure, and accessibility (ARIA, keyboard nav, screen reader labels) |

---

## Quick Start for Implementers

1. **Read the specs in order:** `layout-spec.md` → `color-spec.md` → `realtime-spec.md` → `component-spec.md`. Layout gives you the mental model; color gives you the tokens; realtime gives you the data; components give you the code structure.

2. **Start with the data layer:** Implement the backend endpoints (`GET /api/agents`, `GET /api/agents/:name`, `GET /api/agents/:name/health`) using the file-reading logic in `realtime-spec.md §4`. The existing `app/backend/` FastAPI server is where these belong. Verify they return correct data before touching the frontend.

3. **Set up the Zustand store and polling hook:** Create `app/frontend/src/agent-status/store/agentStore.ts` and `hooks/useAgentPolling.ts` using the code in `component-spec.md §4`. This gives you live data flowing into the app before any UI exists.

4. **Build shared components first:** `StatusBadge`, `HealthIndicator`, `ModelTag`, and `TimestampCell` are used everywhere. Build and test these in isolation (Storybook or a simple test page) before assembling the table and cards.

5. **Wire up the route:** Add `/agents` to `App.tsx` pointing to `AgentDashboard`. The existing frontend at `app/frontend/` already has React + Tailwind + Zustand — no new framework setup needed. Install the three new dependencies: `recharts`, `framer-motion`, `@heroicons/react`.

---

## Open Design Decisions / TODOs

| # | Decision | Options | Recommendation |
|---|----------|---------|----------------|
| 1 | **SSE vs. polling for event log** | SSE (push) or polling + diff | SSE preferred; implement polling fallback if proxy strips `text/event-stream` |
| 2 | **Model/adapter source** | Read from `CONFIG.md`, `agent.py`, or a new `MANIFEST.json` | Parse `CONFIG.md` for now; consider adding a structured `MANIFEST.json` per agent |
| 3 | **Task history** | Show only current task or full task history | Current task only for v1; history requires archiving completed TASK.MD files |
| 4 | **Health sparkline data** | Parse HEALTH.MD timestamps to build hourly buckets | Implement server-side aggregation in `/api/agents/:name/health` response |
| 5 | **Mobile swipe gestures** | Swipe right to open detail, swipe left to dismiss | Implement with Framer Motion `drag` prop; deprioritize for v1 |
| 6 | **Temporary agents** | Dynamic agents created under `app/agents/` should appear automatically | Backend should scan directory dynamically — no hardcoded agent list |
| 7 | **Authentication** | Dashboard is currently open (no auth) | Add basic auth or token check if dashboard is exposed beyond localhost |
| 8 | **Spawn/Kill permissions** | Should all users be able to spawn/kill agents? | Gate behind a confirmation dialog; log all actions to HEALTH.MD |

---

## Related Files

| Path | Description |
|------|-------------|
| `app/frontend/src/api/types.ts` | Existing `AgentStatus` type (extend, don't replace) |
| `app/frontend/src/api/client.ts` | Existing API client (extend with new endpoints) |
| `app/frontend/src/components/AgentCard.tsx` | Existing agent card (different from this spec's card — review for overlap) |
| `app/agents/{name}/STATUS.json` | Primary data source for agent state |
| `app/agents/{name}/TASK.MD` | Source for current task text and frontmatter |
| `app/agents/{name}/HEALTH.MD` | Source for health log and health status derivation |
| `app/agents/{name}/MEMORY.MD` | Source for last memory entry |
