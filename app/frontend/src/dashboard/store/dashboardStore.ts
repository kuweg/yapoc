import { create } from 'zustand'
import type { Ticket, FileNode } from '../types'

interface DashboardStore {
  tickets: Ticket[]
  selectedTicket: Ticket | null
  isCreateOpen: boolean
  pendingAssignTicketId: string | null  // ticket waiting for agent assignment
  fileTree: FileNode[]
  openFilePath: string | null
  openFileContent: string | null
  openFileTruncated: boolean
  isFilePanelOpen: boolean
  isLoading: boolean
  error: string | null
  activeMasterTicketId: string | null

  // Multi-select
  isMultiSelect: boolean
  selectedIds: Set<string>

  setTickets: (tickets: Ticket[]) => void
  upsertTicket: (ticket: Ticket) => void
  removeTicket: (id: string) => void
  selectTicket: (ticket: Ticket | null) => void
  setCreateOpen: (open: boolean) => void
  setPendingAssign: (id: string | null) => void
  setFileTree: (nodes: FileNode[]) => void
  openFile: (path: string, content: string, truncated: boolean) => void
  closeFile: () => void
  toggleFilePanel: () => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  setActiveMasterTicketId: (id: string | null) => void

  // Multi-select actions
  toggleMultiSelect: () => void
  toggleSelectId: (id: string) => void
  clearSelection: () => void
  removeTickets: (ids: string[]) => void
}

export const useDashboardStore = create<DashboardStore>((set, get) => ({
  tickets: [],
  selectedTicket: null,
  isCreateOpen: false,
  pendingAssignTicketId: null,
  fileTree: [],
  openFilePath: null,
  openFileContent: null,
  openFileTruncated: false,
  isFilePanelOpen: false,
  isLoading: false,
  error: null,
  activeMasterTicketId: null,
  isMultiSelect: false,
  selectedIds: new Set(),

  setTickets: (tickets) => {
    // Keep selectedTicket in sync if it exists
    const sel = get().selectedTicket
    const updated = sel ? tickets.find((t) => t.id === sel.id) ?? sel : null
    set({ tickets, selectedTicket: updated })
  },
  upsertTicket: (ticket) =>
    set((s) => {
      const exists = s.tickets.some((t) => t.id === ticket.id)
      const tickets = exists
        ? s.tickets.map((t) => (t.id === ticket.id ? ticket : t))
        : [...s.tickets, ticket]
      const selectedTicket = s.selectedTicket?.id === ticket.id ? ticket : s.selectedTicket
      return { tickets, selectedTicket }
    }),
  removeTicket: (id) =>
    set((s) => ({
      tickets: s.tickets.filter((t) => t.id !== id),
      selectedTicket: s.selectedTicket?.id === id ? null : s.selectedTicket,
    })),
  selectTicket: (ticket) => set({ selectedTicket: ticket }),
  setCreateOpen: (open) => set({ isCreateOpen: open }),
  setPendingAssign: (id) => set({ pendingAssignTicketId: id }),
  setFileTree: (nodes) => set({ fileTree: nodes }),
  openFile: (path, content, truncated) =>
    set({ openFilePath: path, openFileContent: content, openFileTruncated: truncated }),
  closeFile: () => set({ openFilePath: null, openFileContent: null, openFileTruncated: false }),
  toggleFilePanel: () => set((s) => ({ isFilePanelOpen: !s.isFilePanelOpen })),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
  setActiveMasterTicketId: (id) => set({ activeMasterTicketId: id }),

  toggleMultiSelect: () =>
    set((s) => ({ isMultiSelect: !s.isMultiSelect, selectedIds: new Set() })),
  toggleSelectId: (id) =>
    set((s) => {
      const next = new Set(s.selectedIds)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return { selectedIds: next }
    }),
  clearSelection: () => set({ selectedIds: new Set(), isMultiSelect: false }),
  removeTickets: (ids) =>
    set((s) => {
      const idSet = new Set(ids)
      return {
        tickets: s.tickets.filter((t) => !idSet.has(t.id)),
        selectedTicket: s.selectedTicket && idSet.has(s.selectedTicket.id) ? null : s.selectedTicket,
        selectedIds: new Set(),
      }
    }),
}))
