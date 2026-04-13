# YAPOC Agent-Status UI — Layout & Visual Hierarchy Spec

**Version:** 1.0  
**Date:** 2026-04-10  
**Target audience:** Frontend implementers  
**Design philosophy:** Information-dense, dark-first, developer-oriented dashboard

---

## 1. Overall Window Layout

The dashboard is a single-page application (SPA) divided into four structural zones:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  HEADER BAR                                                                 │
│  Logo | "YAPOC Agent Monitor" | System health badge | Settings icon         │
├──────────────────────────────────────────┬──────────────────────────────────┤
│                                          │                                  │
│  MAIN CONTENT AREA                       │  SIDEBAR                         │
│                                          │                                  │
│  [ Filter Bar: All | Running | Idle |    │  System Summary                  │
│    Error | Done ]  [ Search... ] [Sort▼] │  ─────────────                   │
│                                          │  Total agents:    7              │
│  ┌──────────────────────────────────┐    │  Running:         3              │
│  │  Agent Table / Card Grid         │    │  Idle:            2              │
│  │  (scrollable)                    │    │  Error:           1              │
│  │                                  │    │  Done:            1              │
│  │                                  │    │                                  │
│  │                                  │    │  Health Overview                 │
│  │                                  │    │  ─────────────                   │
│  │                                  │    │  ✓ OK:            5              │
│  │                                  │    │  ⚠ Warning:       1              │
│  │                                  │    │  ✗ Critical:      1              │
│  │                                  │    │                                  │
│  │                                  │    │  Active Models                   │
│  │                                  │    │  ─────────────                   │
│  │                                  │    │  claude-sonnet    4              │
│  │                                  │    │  gpt-4o           2              │
│  │                                  │    │  gemini-pro       1              │
│  │                                  │    │                                  │
│  │                                  │    │  ─────────────                   │
│  │                                  │    │  EVENT LOG                       │
│  │                                  │    │  (live scrolling feed)           │
│  │                                  │    │  13:04 builder: task done        │
│  │                                  │    │  13:03 planning: spawned         │
│  │                                  │    │  13:02 cron: health warn         │
│  └──────────────────────────────────┘    │  13:01 keeper: idle              │
│                                          │                                  │
├──────────────────────────────────────────┴──────────────────────────────────┤
│  FOOTER BAR                                                                 │
│  Last refresh: 13:04:22  |  ● Connected  |  Polling: 2s  |  v0.1.0         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.1 Header Bar
- **Height:** 56px fixed
- **Left:** YAPOC logo mark (16×16 icon) + wordmark "YAPOC" + separator + "Agent Monitor"
- **Center:** (empty on desktop; hamburger menu on mobile)
- **Right:** System-wide health badge (green/amber/red pill) + gear icon (settings)
- **Background:** `surface-elevated` color (slightly lighter than main bg)
- **Border-bottom:** 1px `border` color

### 1.2 Main Content Area
- **Width:** `calc(100% - 280px)` on desktop (sidebar is 280px fixed)
- **Padding:** 24px
- **Overflow-y:** auto (scrollable agent list)
- Contains: Filter Bar (sticky at top of scroll area) + Agent Table or Card Grid

### 1.3 Sidebar
- **Width:** 280px fixed on desktop; collapsible drawer on tablet/mobile
- **Sections:** System Summary → Health Overview → Active Models → Event Log
- **Event Log:** Takes remaining vertical space, scrolls independently
- **Border-left:** 1px `border` color

### 1.4 Footer Bar
- **Height:** 36px fixed
- **Content:** Last-refresh timestamp (auto-updates) | connection status dot + label | polling interval | app version
- **Font-size:** 12px, `text-muted` color
- **Background:** same as header

---

## 2. Visual Hierarchy

The UI prioritizes information in this order, from most to least prominent:

| Priority | Element | Rationale |
|----------|---------|-----------|
| 1 | **Status indicator** (colored badge/dot) | Operators need to spot problems instantly — color is pre-attentive |
| 2 | **Agent name** | Identity anchors all other data; must be scannable |
| 3 | **Health indicator** (OK / warning / critical icon) | Secondary signal; confirms or contradicts status |
| 4 | **Last task** (truncated) | Answers "what is this agent doing?" — most contextual value |
| 5 | **Model/Adapter** | Useful for cost/capability awareness; not urgent |
| 6 | **Last activity timestamp** | Relative time ("2m ago") gives staleness signal |

**Design decisions:**
- Status badge uses **color + text** (not color alone) for accessibility
- Agent name is `font-weight: 600`, all other cells are `font-weight: 400`
- Timestamps use relative format ("2m ago") with absolute on hover tooltip
- Error rows get a subtle left-border accent in red to draw the eye even when not looking at the badge column

---

## 3. ASCII Mockup — Main Dashboard View

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ⬡ YAPOC  Agent Monitor                                                    ● All Systems OK   ⚙      │
├─────────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                                     │
│  [ All (7) ]  [ Running (3) ]  [ Idle (2) ]  [ Error (1) ]  [ Done (1) ]    🔍 Search agents...    │
│  Sort by: Status ▼                                                                                  │
│                                                                                                     │
│ ┌──────────────┬────────────┬────────┬──────────────────────┬──────────────────────────┬──────────┐ │
│ │ Agent Name   │ Status     │ Health │ Model / Adapter      │ Last Task                │ Activity │ │
│ ├──────────────┼────────────┼────────┼──────────────────────┼──────────────────────────┼──────────┤ │
│ │ master       │ ● RUNNING  │ ✓ OK   │ claude-sonnet / anth │ Orchestrating agent task │ just now │ │
│ │ planning     │ ● RUNNING  │ ✓ OK   │ claude-sonnet / anth │ Design agent-status UI w │ 1m ago   │ │
│ │ builder      │ ● RUNNING  │ ✓ OK   │ claude-sonnet / anth │ Create app/design/agent- │ just now │ │
│ ├──────────────┼────────────┼────────┼──────────────────────┼──────────────────────────┼──────────┤ │
│ │ keeper       │ ○ IDLE     │ ✓ OK   │ claude-sonnet / anth │ Validate .env file and A │ 34m ago  │ │
│ │ model_manager│ ○ IDLE     │ ✓ OK   │ claude-sonnet / anth │ —                        │ 2h ago   │ │
│ ├──────────────┼────────────┼────────┼──────────────────────┼──────────────────────────┼──────────┤ │
│ │ cron         │ ○ IDLE     │ ⚠ WARN │ claude-sonnet / anth │ Scheduled health check r │ 5m ago   │ │
│ ├──────────────┼────────────┼────────┼──────────────────────┼──────────────────────────┼──────────┤ │
│ │ doctor       │ ✓ DONE     │ ✓ OK   │ claude-sonnet / anth │ Full system health scan  │ 3m ago   │ │
│ └──────────────┴────────────┴────────┴──────────────────────┴──────────────────────────┴──────────┘ │
│                                                                                                     │
│  Showing 7 of 7 agents                                                                              │
│                                                                                                     │
├─────────────────────────────────────────────────────────────────────────────────────────────────────┤
│  Last refresh: 13:04:22  |  ● Connected  |  Polling every 2s  |  YAPOC v0.1.0                      │
└─────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Table column widths (desktop, 1280px):**

| Column | Width | Notes |
|--------|-------|-------|
| Agent Name | 160px | Fixed; monospace font |
| Status | 120px | Badge with icon + text |
| Health | 90px | Icon + text |
| Model / Adapter | 200px | Truncated with tooltip |
| Last Task | flex (remaining) | Truncated at ~40 chars with tooltip |
| Last Activity | 100px | Relative time |

**Row interaction:**
- Hover: row background lightens slightly (`surface-hover`)
- Click anywhere on row: opens Agent Detail Panel
- Error rows: 2px left border in `#EF4444`

---

## 4. ASCII Mockup — Agent Detail Panel

Slides in from the right as a 480px-wide panel (or modal on mobile). The main table dims behind it.

```
                                    ┌──────────────────────────────────────────────┐
                                    │  ✕  Agent: builder                           │
                                    │  ─────────────────────────────────────────── │
                                    │                                              │
                                    │  STATUS          ● RUNNING                  │
                                    │  HEALTH          ✓ OK  (0 errors)            │
                                    │  PID             53743                       │
                                    │  MODEL           claude-sonnet-4-6           │
                                    │  ADAPTER         anthropic                   │
                                    │  STARTED         2026-04-10 11:00:47 UTC     │
                                    │  UPTIME          2h 03m 35s                  │
                                    │  LAST UPDATED    2026-04-10 13:04:22 UTC     │
                                    │                                              │
                                    │  ─── CURRENT TASK ──────────────────────── │
                                    │  Assigned by: master                         │
                                    │  Assigned at: 2026-04-10 11:04:14Z           │
                                    │                                              │
                                    │  Create the directory app/design/agent-      │
                                    │  status-ui/ and write the following four     │
                                    │  design specification files to it. Each      │
                                    │  file should be thorough and production-     │
                                    │  ready...                                    │
                                    │                                              │
                                    │  [ View full TASK.MD ↗ ]                    │
                                    │                                              │
                                    │  ─── HEALTH LOG (last 5 entries) ────────── │
                                    │  13:01 AUDIT: APPROVED file_write ...        │
                                    │  13:01 AUDIT: APPROVED file_write ...        │
                                    │  13:01 AUDIT: APPROVED file_write ...        │
                                    │                                              │
                                    │  ─── HEALTH HISTORY ─────────────────────── │
                                    │  Errors over time (last 24h):               │
                                    │  ▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▃▃▁▁  (sparkline)    │
                                    │                                              │
                                    │  ─── LAST MEMORY ENTRY ──────────────────── │
                                    │  [2026-04-10 13:01] Cleaned up stale        │
                                    │  health/crash log data across all agents...  │
                                    │                                              │
                                    │  [ Spawn Agent ]  [ Kill Agent ]            │
                                    │                                              │
                                    └──────────────────────────────────────────────┘
```

**Panel behavior:**
- Slides in from right with 200ms ease-out transition
- Backdrop: main content dims to 40% opacity
- Close: ✕ button, Escape key, or click outside
- Sticky header with agent name + status badge
- Scrollable body for long task text / health logs
- Action buttons (Spawn / Kill) are disabled and grayed out when action is not applicable

---

## 5. Navigation Structure

### 5.1 Filter Bar (sticky, top of main content)

```
[ All (7) ]  [ ● Running (3) ]  [ ○ Idle (2) ]  [ ✗ Error (1) ]  [ ✓ Done (1) ]
```

- Tabs with count badges
- Active tab: underline + text color matches status color
- Counts update in real time as polling refreshes data

### 5.2 Sort Options

Dropdown control: `Sort by: [Status ▼]`

Options:
- **Status** (default) — groups by running → error → idle → done
- **Name** — alphabetical A→Z
- **Last Activity** — most recent first
- **Health** — critical → warning → ok

### 5.3 Search Box

- Placeholder: `🔍 Search agents...`
- Filters by agent name (substring match, case-insensitive)
- Clears with ✕ button
- Keyboard shortcut: `/` focuses the search box

---

## 6. Information Density Modes

Toggle in the settings panel (gear icon in header). Persisted to `localStorage`.

### 6.1 Compact Mode (default for developers)

```
┌──────────────┬────────────┬────────┬──────────────────────┬──────────────────────────┬──────────┐
│ master       │ ● RUNNING  │ ✓ OK   │ claude-sonnet / anth │ Orchestrating agent task │ just now │
│ planning     │ ● RUNNING  │ ✓ OK   │ claude-sonnet / anth │ Design agent-status UI w │ 1m ago   │
│ builder      │ ● RUNNING  │ ✓ OK   │ claude-sonnet / anth │ Create app/design/agent- │ just now │
└──────────────┴────────────┴────────┴──────────────────────┴──────────────────────────┴──────────┘
```

- Row height: 40px
- Font size: 13px
- Padding: 8px 12px
- No row separators (zebra striping only)
- Shows maximum agents without scrolling

### 6.2 Comfortable Mode (card-based)

```
┌─────────────────────────────────────┐  ┌─────────────────────────────────────┐
│  ● RUNNING                          │  │  ● RUNNING                          │
│  master                             │  │  planning                           │
│  ─────────────────────────────────  │  │  ─────────────────────────────────  │
│  ✓ OK  |  claude-sonnet / anthropic │  │  ✓ OK  |  claude-sonnet / anthropic │
│                                     │  │                                     │
│  Orchestrating agent task assignm…  │  │  Design agent-status UI window fo…  │
│                                     │  │                                     │
│  Last active: just now              │  │  Last active: 1m ago                │
└─────────────────────────────────────┘  └─────────────────────────────────────┘
```

- Card size: ~320px wide, auto height
- Grid: 2 columns on desktop, 1 on tablet/mobile
- Font size: 14px
- Padding: 16px
- Status badge prominent at top-left of card
- Agent name: 18px, font-weight 600
- Subtle card border + shadow

---

## 7. Responsive Behavior Summary

| Breakpoint | Layout changes |
|-----------|----------------|
| ≥1280px (Desktop) | Full table, sidebar visible, all columns shown |
| 768–1279px (Tablet) | Sidebar collapses to icon rail; Model/Adapter column hidden; Last Task → icon+tooltip |
| ≤767px (Mobile) | Card layout only; sidebar becomes bottom sheet; filter bar scrolls horizontally |

See `component-spec.md` for full responsive breakpoint details.
