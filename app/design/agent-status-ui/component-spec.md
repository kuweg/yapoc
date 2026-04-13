# YAPOC Agent-Status UI — Component Structure, Responsive Design & Implementation Spec

**Version:** 1.0  
**Date:** 2026-04-10  
**Stack:** React 19 + TypeScript + Tailwind CSS v4 + Zustand v5  
**Note:** The existing YAPOC frontend already uses React 19, TypeScript, Tailwind CSS v4, and Zustand v5. This spec extends that stack.

---

## 1. Component Tree

```
AgentDashboard                          # Root page component
├── DashboardHeader                     # Fixed top bar
│   ├── BrandMark                       # Logo + "YAPOC Agent Monitor"
│   ├── SystemHealthBadge               # Global health pill (ok/warning/critical)
│   └── SettingsButton                  # Opens settings panel
│
├── DashboardLayout                     # Flex container: main + sidebar
│   ├── MainContent                     # Left/center scrollable area
│   │   ├── FilterBar                   # Sticky filter/search/sort controls
│   │   │   ├── StatusFilter            # Tab group: All | Running | Idle | Error | Done
│   │   │   ├── SearchInput             # Text search box
│   │   │   └── SortControl             # Dropdown: sort by status/name/activity/health
│   │   │
│   │   ├── AgentTable                  # Table layout (Compact mode)
│   │   │   ├── AgentTableHeader        # Column headers with sort indicators
│   │   │   └── AgentRow[]              # One per agent
│   │   │       ├── StatusBadge         # Colored pill: ● RUNNING / ○ IDLE / etc.
│   │   │       ├── HealthIndicator     # Icon + text: ✓ OK / ⚠ WARN / ✗ CRIT
│   │   │       ├── ModelTag            # Model name + adapter chip
│   │   │       ├── TaskSummaryCell     # Truncated task text with tooltip
│   │   │       └── TimestampCell       # Relative time with absolute tooltip
│   │   │
│   │   └── AgentCardGrid               # Card layout (Comfortable mode)
│   │       └── AgentCard[]             # One per agent
│   │           ├── StatusBadge         # (shared component)
│   │           ├── HealthIndicator     # (shared component)
│   │           ├── ModelTag            # (shared component)
│   │           └── TimestampCell       # (shared component)
│   │
│   └── Sidebar                         # Right panel (280px fixed)
│       ├── SystemSummary               # Agent count by status
│       ├── HealthOverview              # Health count by level
│       ├── ActiveModels                # Model usage breakdown
│       └── EventLogFeed                # Live scrolling event stream
│           └── EventLogEntry[]         # One per event
│
├── AgentDetailPanel                    # Slide-in right panel (480px)
│   ├── AgentDetailHeader               # Agent name + status + close button
│   ├── AgentMetaGrid                   # Key-value grid: PID, model, uptime, etc.
│   ├── TaskDetail                      # Full task text + frontmatter
│   │   └── TaskHistory                 # Previous tasks (if available)
│   ├── HealthLogList                   # Last 20 HEALTH.MD entries
│   ├── HealthSparkline                 # Error count over time (Recharts)
│   ├── MemoryPreview                   # Last 5 MEMORY.MD entries
│   └── AgentActions                    # Spawn / Kill buttons
│
├── DashboardFooter                     # Fixed bottom bar
│   ├── LastRefreshTimestamp            # "Last refresh: 13:04:22"
│   ├── ConnectionStatus                # ● Connected / ● Reconnecting / ● Disconnected
│   └── AppVersion                      # "YAPOC v0.1.0"
│
└── SettingsPanel                       # Slide-in settings (density mode, theme toggle)
```

---

## 2. Props Interfaces (TypeScript)

### 2.1 AgentDashboard

```typescript
// No props — root component, owns all state via Zustand store
export function AgentDashboard(): JSX.Element
```

### 2.2 FilterBar

```typescript
interface FilterBarProps {
  activeFilter: StatusFilter;
  onFilterChange: (filter: StatusFilter) => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
  sortBy: SortOption;
  onSortChange: (sort: SortOption) => void;
  counts: Record<StatusFilter, number>;
}

type StatusFilter = 'all' | 'running' | 'idle' | 'error' | 'done';
type SortOption = 'status' | 'name' | 'last_activity' | 'health';
```

### 2.3 StatusFilter (tab group)

```typescript
interface StatusFilterProps {
  active: StatusFilter;
  onChange: (filter: StatusFilter) => void;
  counts: Record<StatusFilter, number>;
}
```

### 2.4 SearchInput

```typescript
interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;  // default: "Search agents..."
}
```

### 2.5 SortControl

```typescript
interface SortControlProps {
  value: SortOption;
  onChange: (sort: SortOption) => void;
}
```

### 2.6 AgentTable

```typescript
interface AgentTableProps {
  agents: AgentStatus[];
  onRowClick: (agentName: string) => void;
  selectedAgent: string | null;
}
```

### 2.7 AgentRow

```typescript
interface AgentRowProps {
  agent: AgentStatus;
  onClick: () => void;
  isSelected: boolean;
  isStale: boolean;  // true if data is older than 2× polling interval
}
```

### 2.8 StatusBadge

```typescript
interface StatusBadgeProps {
  status: 'running' | 'idle' | 'done' | 'error';
  size?: 'sm' | 'md';  // default: 'md'
  showLabel?: boolean;  // default: true; false = dot only
}
```

### 2.9 HealthIndicator

```typescript
interface HealthIndicatorProps {
  health: 'ok' | 'warning' | 'critical';
  errorCount?: number;  // shown in tooltip: "3 errors"
  size?: 'sm' | 'md';  // default: 'md'
}
```

### 2.10 ModelTag

```typescript
interface ModelTagProps {
  model: string;    // e.g. "claude-sonnet-4-6"
  adapter: string;  // e.g. "anthropic"
  truncate?: boolean;  // default: true (truncates model name)
}
```

### 2.11 TimestampCell

```typescript
interface TimestampCellProps {
  timestamp: string | null;  // ISO 8601 UTC
  fallback?: string;         // default: "—"
  isStale?: boolean;         // shows ⚠ indicator
}
```

### 2.12 AgentDetailPanel

```typescript
interface AgentDetailPanelProps {
  agentName: string | null;  // null = panel closed
  onClose: () => void;
}
```

### 2.13 HealthSparkline

```typescript
interface HealthSparklineProps {
  // Array of {hour, errorCount} for last 24 hours
  data: Array<{ hour: string; errorCount: number }>;
  height?: number;  // default: 40
}
```

### 2.14 EventLogFeed

```typescript
interface EventLogFeedProps {
  events: AgentEvent[];
  onAgentClick?: (agentName: string) => void;
  maxEntries?: number;  // default: 50
}
```

### 2.15 EventLogEntry

```typescript
interface EventLogEntryProps {
  event: AgentEvent;
  onClick?: () => void;
  isNew?: boolean;  // triggers highlight animation
}
```

### 2.16 SystemHealthBadge

```typescript
interface SystemHealthBadgeProps {
  // Derived from all agents
  overallHealth: 'ok' | 'warning' | 'critical';
  runningCount: number;
  errorCount: number;
}
```

### 2.17 AgentCard (Comfortable mode)

```typescript
interface AgentCardProps {
  agent: AgentStatus;
  onClick: () => void;
  isSelected: boolean;
  isStale: boolean;
}
```

---

## 3. Responsive Breakpoints

### 3.1 Desktop (≥1280px) — Full Table

- **Layout:** Sidebar (280px fixed right) + Main content (remaining width)
- **Agent display:** Full table with all 6 columns
- **Columns shown:** Agent Name | Status | Health | Model/Adapter | Last Task | Last Activity
- **Sidebar:** Always visible
- **Detail panel:** Slides in from right (480px), main content shrinks

```css
/* Tailwind v4 */
@media (min-width: 1280px) {
  .sidebar { display: flex; width: 280px; }
  .col-model { display: table-cell; }
  .col-task { display: table-cell; }
  .detail-panel { width: 480px; }
}
```

### 3.2 Tablet (768px–1279px) — Condensed Table

- **Layout:** Sidebar collapses to icon rail (48px) with hover-expand
- **Agent display:** Table with 4 columns (Model/Adapter column hidden)
- **Columns shown:** Agent Name | Status | Health | Last Task (icon+tooltip) | Last Activity
- **Last Task:** Replaced with a `📋` icon; full text in tooltip on hover
- **Sidebar:** Icon rail with tooltips; click to expand as overlay drawer

```css
@media (min-width: 768px) and (max-width: 1279px) {
  .sidebar { width: 48px; }
  .sidebar:hover, .sidebar.expanded { width: 280px; }
  .col-model { display: none; }
  .col-task-text { display: none; }
  .col-task-icon { display: table-cell; }
}
```

### 3.3 Mobile (≤767px) — Card Layout

- **Layout:** Single column; sidebar becomes bottom sheet (swipe up to reveal)
- **Agent display:** Card-based, one agent per card, full width
- **Filter bar:** Scrolls horizontally (overflow-x: auto)
- **Detail panel:** Full-screen modal (100vw × 100vh)
- **Bottom sheet:** Triggered by floating action button (⊞ icon, bottom-right)

```css
@media (max-width: 767px) {
  .sidebar { 
    position: fixed; bottom: 0; left: 0; right: 0;
    height: 0; transition: height 300ms ease;
  }
  .sidebar.open { height: 60vh; }
  .agent-table { display: none; }
  .agent-card-grid { display: grid; grid-template-columns: 1fr; }
  .detail-panel { 
    position: fixed; inset: 0; 
    width: 100%; height: 100%;
  }
}
```

### 3.4 Breakpoint Summary Table

| Feature | Mobile (≤767px) | Tablet (768–1279px) | Desktop (≥1280px) |
|---------|----------------|--------------------|--------------------|
| Layout | Single column | Two column | Two column |
| Agent display | Cards | Table (4 cols) | Table (6 cols) |
| Sidebar | Bottom sheet | Icon rail | Fixed 280px |
| Model/Adapter col | Hidden | Hidden | Visible |
| Last Task col | Card body | Icon + tooltip | Truncated text |
| Detail panel | Full screen | Full screen | Slide-in 480px |
| Filter bar | Horizontal scroll | Full | Full |

---

## 4. State Management

### 4.1 Recommended: Zustand (already in project)

The project already uses Zustand v5. Use it for all UI state. Use `fetch` with `setInterval` for polling (React Query is not in the current `package.json` — avoid adding it unless needed).

### 4.2 Store Shape

```typescript
// app/ui/agent-status/store/agentStore.ts

import { create } from 'zustand';
import type { AgentStatus, AgentDetail, AgentEvent } from '../types';

interface AgentStore {
  // Data
  agents: AgentStatus[];
  selectedAgentName: string | null;
  selectedAgentDetail: AgentDetail | null;
  events: AgentEvent[];
  
  // UI state
  activeFilter: StatusFilter;
  searchQuery: string;
  sortBy: SortOption;
  densityMode: 'compact' | 'comfortable';
  theme: 'dark' | 'light';
  
  // Connection state
  connectionStatus: 'connected' | 'reconnecting' | 'disconnected';
  lastRefreshedAt: Date | null;
  isDetailLoading: boolean;
  
  // Actions
  setAgents: (agents: AgentStatus[]) => void;
  selectAgent: (name: string | null) => void;
  setAgentDetail: (detail: AgentDetail | null) => void;
  addEvent: (event: AgentEvent) => void;
  setFilter: (filter: StatusFilter) => void;
  setSearch: (query: string) => void;
  setSort: (sort: SortOption) => void;
  setDensityMode: (mode: 'compact' | 'comfortable') => void;
  setTheme: (theme: 'dark' | 'light') => void;
  setConnectionStatus: (status: 'connected' | 'reconnecting' | 'disconnected') => void;
  setLastRefreshed: (date: Date) => void;
}

export const useAgentStore = create<AgentStore>((set) => ({
  agents: [],
  selectedAgentName: null,
  selectedAgentDetail: null,
  events: [],
  activeFilter: 'all',
  searchQuery: '',
  sortBy: 'status',
  densityMode: 'compact',
  theme: 'dark',
  connectionStatus: 'connected',
  lastRefreshedAt: null,
  isDetailLoading: false,

  setAgents: (agents) => set({ agents, lastRefreshedAt: new Date() }),
  selectAgent: (name) => set({ selectedAgentName: name, selectedAgentDetail: null }),
  setAgentDetail: (detail) => set({ selectedAgentDetail: detail, isDetailLoading: false }),
  addEvent: (event) => set((state) => ({
    events: [event, ...state.events].slice(0, 50), // Keep last 50
  })),
  setFilter: (activeFilter) => set({ activeFilter }),
  setSearch: (searchQuery) => set({ searchQuery }),
  setSort: (sortBy) => set({ sortBy }),
  setDensityMode: (densityMode) => {
    localStorage.setItem('yapoc-density', densityMode);
    set({ densityMode });
  },
  setTheme: (theme) => {
    localStorage.setItem('yapoc-theme', theme);
    document.documentElement.setAttribute('data-theme', theme);
    set({ theme });
  },
  setConnectionStatus: (connectionStatus) => set({ connectionStatus }),
  setLastRefreshed: (date) => set({ lastRefreshedAt: date }),
}));
```

### 4.3 Polling Hook

```typescript
// app/ui/agent-status/hooks/useAgentPolling.ts

import { useEffect, useRef } from 'react';
import { useAgentStore } from '../store/agentStore';
import { getAgents, getAgentDetail } from '../api/agentStatusClient';

const AGENT_LIST_INTERVAL = 2000;   // 2s
const AGENT_DETAIL_INTERVAL = 5000; // 5s
const MAX_FAILURES = 3;

export function useAgentPolling() {
  const { 
    setAgents, selectedAgentName, setAgentDetail,
    setConnectionStatus, addEvent, agents: prevAgents
  } = useAgentStore();
  
  const failureCount = useRef(0);
  const backoffMs = useRef(AGENT_LIST_INTERVAL);

  useEffect(() => {
    let listTimer: ReturnType<typeof setTimeout>;
    let isMounted = true;

    async function pollAgentList() {
      if (!isMounted) return;
      
      // Pause when tab is hidden
      if (document.visibilityState === 'hidden') {
        listTimer = setTimeout(pollAgentList, AGENT_LIST_INTERVAL);
        return;
      }

      try {
        const agents = await getAgents();
        if (!isMounted) return;
        
        // Synthesize events from state diff (fallback for SSE)
        const events = diffAgentStates(prevAgents, agents);
        events.forEach(addEvent);
        
        setAgents(agents);
        failureCount.current = 0;
        backoffMs.current = AGENT_LIST_INTERVAL;
        setConnectionStatus('connected');
      } catch {
        failureCount.current++;
        if (failureCount.current >= MAX_FAILURES) {
          setConnectionStatus('disconnected');
        } else {
          setConnectionStatus('reconnecting');
        }
        // Exponential backoff: 2s → 4s → 8s → 16s → max 60s
        backoffMs.current = Math.min(backoffMs.current * 2, 60000);
      }

      listTimer = setTimeout(pollAgentList, backoffMs.current);
    }

    // Add jitter to avoid thundering herd
    const jitter = Math.random() * 500;
    listTimer = setTimeout(pollAgentList, jitter);

    return () => {
      isMounted = false;
      clearTimeout(listTimer);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll detail when an agent is selected
  useEffect(() => {
    if (!selectedAgentName) return;
    let detailTimer: ReturnType<typeof setTimeout>;
    let isMounted = true;

    async function pollDetail() {
      if (!isMounted || !selectedAgentName) return;
      try {
        const detail = await getAgentDetail(selectedAgentName);
        if (isMounted) setAgentDetail(detail);
      } catch { /* silently fail — list poll handles connection status */ }
      detailTimer = setTimeout(pollDetail, AGENT_DETAIL_INTERVAL);
    }

    pollDetail();
    return () => { isMounted = false; clearTimeout(detailTimer); };
  }, [selectedAgentName]); // eslint-disable-line react-hooks/exhaustive-deps
}
```

### 4.4 Derived Selectors

```typescript
// app/ui/agent-status/store/selectors.ts

import { useAgentStore } from './agentStore';

export function useFilteredAgents() {
  const { agents, activeFilter, searchQuery, sortBy } = useAgentStore();
  
  return agents
    .filter(a => activeFilter === 'all' || a.state === activeFilter)
    .filter(a => a.name.toLowerCase().includes(searchQuery.toLowerCase()))
    .sort((a, b) => {
      if (sortBy === 'name') return a.name.localeCompare(b.name);
      if (sortBy === 'last_activity') {
        return (b.updated_at ?? '').localeCompare(a.updated_at ?? '');
      }
      if (sortBy === 'health') {
        const order = { critical: 0, warning: 1, ok: 2 };
        return order[a.health] - order[b.health];
      }
      // Default: status (running → error → idle → done)
      const order = { running: 0, error: 1, idle: 2, done: 3 };
      return order[a.state] - order[b.state];
    });
}

export function useStatusCounts() {
  const agents = useAgentStore(s => s.agents);
  return {
    all: agents.length,
    running: agents.filter(a => a.state === 'running').length,
    idle: agents.filter(a => a.state === 'idle').length,
    error: agents.filter(a => a.state === 'error').length,
    done: agents.filter(a => a.state === 'done').length,
  };
}

export function useSystemHealth() {
  const agents = useAgentStore(s => s.agents);
  const criticalCount = agents.filter(a => a.health === 'critical').length;
  const warningCount = agents.filter(a => a.health === 'warning').length;
  if (criticalCount > 0) return 'critical';
  if (warningCount > 0) return 'warning';
  return 'ok';
}
```

---

## 5. Implementation Stack Recommendations

### 5.1 Core Stack (already in project — use as-is)

| Technology | Version | Role |
|-----------|---------|------|
| **React** | 19.x | UI framework |
| **TypeScript** | 5.7.x | Type safety |
| **Tailwind CSS** | 4.x | Styling |
| **Zustand** | 5.x | State management |
| **Vite** | 6.x | Build tool |

### 5.2 Additions Required

| Technology | Version | Role | Install command |
|-----------|---------|------|----------------|
| **Recharts** | ^2.12 | HealthSparkline component | `npm install recharts` |
| **Framer Motion** | ^11 | Status transition animations | `npm install framer-motion` |
| **@heroicons/react** | ^2.1 | Status/health icons | `npm install @heroicons/react` |

**Why Recharts over alternatives:**
- Lightweight, React-native (no D3 dependency)
- `<LineChart>` and `<AreaChart>` work perfectly for sparklines
- Already used in many React dashboards; well-documented

**Why Framer Motion:**
- Declarative animation API fits React's component model
- `AnimatePresence` handles the detail panel slide-in/out cleanly
- `layout` prop handles table row reordering animations when filter changes
- Lighter than react-spring for this use case

**Why @heroicons/react:**
- Consistent icon set (same as Tailwind UI)
- Tree-shakeable; only imports icons used
- Solid and outline variants for health indicators

### 5.3 Do NOT Add

- ❌ **React Query / TanStack Query** — Zustand + custom polling hook is sufficient and avoids adding a large dependency
- ❌ **Redux** — Zustand is already in the project and is simpler
- ❌ **D3.js** — Recharts covers all charting needs
- ❌ **Material UI / Chakra UI** — Tailwind CSS is already the styling system

---

## 6. File Structure

Place all agent-status UI files under `app/ui/agent-status/` to keep them separate from the existing frontend components:

```
app/
└── frontend/
    └── src/
        ├── App.tsx                          # Existing — add route to AgentDashboard
        ├── api/
        │   ├── client.ts                    # Existing — extend with new endpoints
        │   └── types.ts                     # Existing — extend with new types
        │
        ├── components/                      # Existing components (unchanged)
        │   ├── AgentCard.tsx
        │   └── ...
        │
        └── agent-status/                    # NEW — all agent-status UI code
            ├── index.tsx                    # Entry point: exports AgentDashboard
            │
            ├── types.ts                     # AgentStatus, AgentDetail, AgentEvent types
            │
            ├── api/
            │   └── agentStatusClient.ts     # getAgents(), getAgentDetail(), SSE setup
            │
            ├── store/
            │   ├── agentStore.ts            # Zustand store
            │   └── selectors.ts             # Derived selectors
            │
            ├── hooks/
            │   ├── useAgentPolling.ts       # Polling logic
            │   ├── useEventStream.ts        # SSE connection
            │   └── useRelativeTime.ts       # "2m ago" formatting
            │
            └── components/
                ├── AgentDashboard.tsx       # Root component
                ├── DashboardHeader.tsx
                ├── DashboardFooter.tsx
                ├── DashboardLayout.tsx
                │
                ├── filter/
                │   ├── FilterBar.tsx
                │   ├── StatusFilter.tsx
                │   ├── SearchInput.tsx
                │   └── SortControl.tsx
                │
                ├── table/
                │   ├── AgentTable.tsx
                │   ├── AgentTableHeader.tsx
                │   └── AgentRow.tsx
                │
                ├── cards/
                │   ├── AgentCardGrid.tsx
                │   └── AgentCard.tsx
                │
                ├── shared/
                │   ├── StatusBadge.tsx      # Used in table, cards, and detail panel
                │   ├── HealthIndicator.tsx
                │   ├── ModelTag.tsx
                │   └── TimestampCell.tsx
                │
                ├── detail/
                │   ├── AgentDetailPanel.tsx
                │   ├── AgentMetaGrid.tsx
                │   ├── TaskDetail.tsx
                │   ├── HealthLogList.tsx
                │   ├── HealthSparkline.tsx
                │   ├── MemoryPreview.tsx
                │   └── AgentActions.tsx
                │
                └── sidebar/
                    ├── Sidebar.tsx
                    ├── SystemSummary.tsx
                    ├── HealthOverview.tsx
                    ├── ActiveModels.tsx
                    ├── EventLogFeed.tsx
                    └── EventLogEntry.tsx
```

### 6.1 Routing

Add a route in `App.tsx`:

```typescript
// In App.tsx — add alongside existing routes
import { AgentDashboard } from './agent-status';

// Add to router:
{ path: '/agents', element: <AgentDashboard /> }
```

Or add a navigation link in the existing UI to `/agents`.

---

## 7. Accessibility

### 7.1 Keyboard Navigation

| Key | Action |
|-----|--------|
| `Tab` | Move focus through interactive elements |
| `Enter` / `Space` | Activate focused row/button |
| `Escape` | Close detail panel / clear search |
| `/` | Focus search input |
| `↑` / `↓` | Navigate table rows when table is focused |
| `←` / `→` | Switch between filter tabs |

**Implementation:**
- `AgentTable` uses `role="grid"` with `aria-rowcount`
- `AgentRow` uses `role="row"` with `tabIndex={0}` and `onKeyDown` handler
- Detail panel traps focus when open (use `focus-trap-react` or manual implementation)

### 7.2 ARIA Roles

```typescript
// AgentTable
<table role="grid" aria-label="Agent status table" aria-rowcount={agents.length}>
  <thead>
    <tr role="row">
      <th role="columnheader" aria-sort="ascending">Agent Name</th>
      ...
    </tr>
  </thead>
  <tbody>
    {agents.map(agent => (
      <AgentRow key={agent.name} agent={agent} role="row" />
    ))}
  </tbody>
</table>

// AgentRow
<tr
  role="row"
  tabIndex={0}
  aria-selected={isSelected}
  onClick={onClick}
  onKeyDown={(e) => e.key === 'Enter' && onClick()}
>

// StatusBadge
<span
  role="status"
  aria-label={`Status: ${status}`}
  aria-live="polite"  // announces status changes to screen readers
>
  <span aria-hidden="true">●</span>  {/* icon is decorative */}
  {statusLabel}
</span>

// HealthIndicator
<span aria-label={`Health: ${health}${errorCount ? `, ${errorCount} errors` : ''}`}>
  <span aria-hidden="true">{icon}</span>
  {healthLabel}
</span>

// AgentDetailPanel
<div
  role="dialog"
  aria-modal="true"
  aria-label={`Agent details: ${agentName}`}
  aria-describedby="agent-detail-description"
>
```

### 7.3 Screen Reader Labels for Status Badges

```typescript
const STATUS_LABELS: Record<string, string> = {
  running: 'Running — agent is actively processing a task',
  idle: 'Idle — agent is waiting for a task',
  done: 'Done — agent has completed its last task',
  error: 'Error — agent encountered a problem',
};

const HEALTH_LABELS: Record<string, string> = {
  ok: 'Health OK — no recent errors',
  warning: 'Health Warning — recent warnings detected',
  critical: 'Health Critical — recent errors detected',
};
```

### 7.4 Color Independence

- All status indicators use **color + text label** (never color alone)
- All health indicators use **color + icon + text label**
- The error row accent border is supplemented by the `✗ ERROR` badge text
- Animations respect `prefers-reduced-motion`:

```css
@media (prefers-reduced-motion: reduce) {
  .status-dot--running {
    animation: none;
  }
  .status-badge--running {
    box-shadow: none;
  }
}
```

### 7.5 Focus Indicators

```css
/* Override Tailwind's default focus ring for better visibility on dark bg */
:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
  border-radius: 4px;
}
```
