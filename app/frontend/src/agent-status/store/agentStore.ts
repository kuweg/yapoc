import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { AgentStatus, AgentDetail, AgentEvent, StatusFilterType, SortBy, DensityMode } from '../types'

interface AgentStore {
  // Data
  agents: AgentStatus[]
  selectedAgentName: string | null
  selectedAgentDetail: AgentDetail | null
  events: AgentEvent[]
  // UI state
  activeFilter: StatusFilterType
  searchQuery: string
  sortBy: SortBy
  densityMode: DensityMode
  // Connection
  connectionStatus: 'connected' | 'reconnecting' | 'disconnected'
  lastRefreshedAt: number | null
  isDetailLoading: boolean
  // Actions
  setAgents: (agents: AgentStatus[]) => void
  selectAgent: (name: string | null) => void
  setAgentDetail: (detail: AgentDetail | null) => void
  setDetailLoading: (v: boolean) => void
  pushEvent: (event: AgentEvent) => void
  setActiveFilter: (f: StatusFilterType) => void
  setSearchQuery: (q: string) => void
  setSortBy: (s: SortBy) => void
  setDensityMode: (m: DensityMode) => void
  setConnectionStatus: (s: 'connected' | 'reconnecting' | 'disconnected') => void
  setLastRefreshed: () => void
}

export const useAgentStore = create<AgentStore>()(
  persist(
    (set) => ({
      agents: [],
      selectedAgentName: null,
      selectedAgentDetail: null,
      events: [],
      activeFilter: 'all',
      searchQuery: '',
      sortBy: 'status',
      densityMode: 'compact',
      connectionStatus: 'connected',
      lastRefreshedAt: null,
      isDetailLoading: false,

      setAgents: (agents) => set({ agents }),
      selectAgent: (name) => set({ selectedAgentName: name, selectedAgentDetail: null }),
      setAgentDetail: (detail) => set({ selectedAgentDetail: detail }),
      setDetailLoading: (v) => set({ isDetailLoading: v }),
      pushEvent: (event) =>
        set((s) => ({ events: [event, ...s.events].slice(0, 50) })),
      setActiveFilter: (f) => set({ activeFilter: f }),
      setSearchQuery: (q) => set({ searchQuery: q }),
      setSortBy: (s) => set({ sortBy: s }),
      setDensityMode: (m) => set({ densityMode: m }),
      setConnectionStatus: (s) => set({ connectionStatus: s }),
      setLastRefreshed: () => set({ lastRefreshedAt: Date.now() }),
    }),
    {
      name: 'yapoc-agent-dashboard',
      partialize: (s) => ({ densityMode: s.densityMode }),
    },
  ),
)
