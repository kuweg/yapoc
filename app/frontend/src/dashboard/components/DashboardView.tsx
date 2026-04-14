import { useEffect, useRef, useState } from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import { useWsStore } from '../../store/wsStore'
import { getTickets, deleteTicket, updateTicket } from '../api/ticketClient'
import { KanbanBoard } from './kanban/KanbanBoard'
import { TicketDetailPanel } from './detail/TicketDetailPanel'
import { CreateTicketModal } from './modals/CreateTicketModal'
import { FileTreePanel } from './files/FileTreePanel'
import type { TicketStatus } from '../types'
import { COLUMNS } from '../types'

const POLL_INTERVAL = 8_000  // ms

export function DashboardView() {
  const {
    tickets, setTickets, selectedTicket, selectTicket,
    setCreateOpen,
    pendingAssignTicketId,
    isFilePanelOpen, toggleFilePanel,
    isLoading, setLoading, error, setError,
    isMultiSelect, selectedIds, toggleMultiSelect, toggleSelectId, clearSelection, removeTickets, upsertTicket,
  } = useDashboardStore()

  const [bulkLoading, setBulkLoading] = useState(false)
  const [moveDropdownOpen, setMoveDropdownOpen] = useState(false)

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Re-fetch tickets when a task lifecycle event arrives via WebSocket
  const lastCompletedTask = useWsStore((s) => s.lastCompletedTask)
  const backgroundTasks = useWsStore((s) => s.backgroundTasks)
  const wsEventCounter = backgroundTasks.length  // changes on any task event
  useEffect(() => {
    if (wsEventCounter > 0) loadTickets()
  }, [wsEventCounter, lastCompletedTask])

  async function loadTickets() {
    try {
      const data = await getTickets()
      setTickets(data)
      setError(null)
    } catch (err: any) {
      setError(err.message ?? 'Failed to load tickets')
    }
  }

  // Self-rescheduling poll (same pattern as useAgentPolling)
  function scheduleNext() {
    timerRef.current = setTimeout(async () => {
      if (document.visibilityState !== 'hidden') {
        await loadTickets()
      }
      scheduleNext()
    }, POLL_INTERVAL)
  }

  useEffect(() => {
    setLoading(true)
    loadTickets().finally(() => setLoading(false))
    scheduleNext()

    const onVisible = () => { if (document.visibilityState === 'visible') loadTickets() }
    document.addEventListener('visibilitychange', onVisible)

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [])

  async function handleBulkDelete() {
    if (selectedIds.size === 0) return
    setBulkLoading(true)
    const ids = Array.from(selectedIds)
    try {
      await Promise.all(ids.map((id) => deleteTicket(id)))
      removeTickets(ids)
    } catch (err: any) {
      setError(err.message ?? 'Failed to delete tickets')
    } finally {
      setBulkLoading(false)
      setMoveDropdownOpen(false)
    }
  }

  async function handleBulkMove(status: TicketStatus) {
    if (selectedIds.size === 0) return
    setBulkLoading(true)
    setMoveDropdownOpen(false)
    const ids = Array.from(selectedIds)
    try {
      const results = await Promise.all(
        ids.map((id) => updateTicket(id, { status }))
      )
      results.forEach((t) => upsertTicket(t))
      clearSelection()
    } catch (err: any) {
      setError(err.message ?? 'Failed to move tickets')
    } finally {
      setBulkLoading(false)
    }
  }

  const udtsTotal = tickets.filter((t) => t.type === 'user').length
  const agentTotal = tickets.filter((t) => t.type === 'agent').length

  return (
    <div className="flex flex-col h-full bg-[#0D1117] text-[#E6EDF3] overflow-hidden">
      {/* Top bar */}
      <div className="flex items-center gap-3 px-4 py-2 bg-[#161B22] border-b border-[#30363D] flex-shrink-0">
        <span className="text-[#E6EDF3] text-sm font-semibold">Dashboard</span>

        {/* Counts */}
        <div className="flex items-center gap-2 text-[11px] text-[#8B949E]">
          <span>
            <span className="text-[#9E68FF] font-medium">{udtsTotal}</span> user tickets
          </span>
          <span>·</span>
          <span>
            <span className="text-[#FFB633] font-medium">{agentTotal}</span> agent tasks
          </span>
        </div>

        <div className="flex items-center gap-2 ml-auto">
          {/* Files toggle */}
          <button
            onClick={toggleFilePanel}
            className={[
              'px-3 py-1 rounded text-xs font-medium border transition-colors',
              isFilePanelOpen
                ? 'bg-[#21262D] text-[#FFB633] border-[#FFB63340]'
                : 'bg-[#21262D] text-[#8B949E] border-[#30363D] hover:text-[#E6EDF3]',
            ].join(' ')}
          >
            Files {isFilePanelOpen ? '▲' : '▼'}
          </button>

          {/* Refresh */}
          <button
            onClick={loadTickets}
            disabled={isLoading}
            className="px-2 py-1 rounded text-xs text-[#8B949E] hover:text-[#E6EDF3] border border-[#30363D] bg-[#21262D] transition-colors disabled:opacity-40"
            title="Refresh"
          >
            ↻
          </button>

          {/* Multi-select toggle */}
          <button
            onClick={toggleMultiSelect}
            className={[
              'px-3 py-1 rounded text-xs font-medium border transition-colors',
              isMultiSelect
                ? 'bg-[#388BFD20] text-[#388BFD] border-[#388BFD40]'
                : 'bg-[#21262D] text-[#8B949E] border-[#30363D] hover:text-[#E6EDF3]',
            ].join(' ')}
          >
            {isMultiSelect ? '✕ Cancel' : 'Select'}
          </button>

          {/* New ticket */}
          <button
            onClick={() => setCreateOpen(true)}
            className="px-3 py-1 rounded bg-[#238636] text-white text-xs font-medium hover:bg-[#2EA043] transition-colors"
          >
            + New Ticket
          </button>
        </div>
      </div>

      {/* Bulk action bar */}
      {isMultiSelect && (
        <div className="flex items-center gap-3 px-4 py-2 bg-[#161B22] border-b border-[#388BFD30] flex-shrink-0">
          <span className="text-xs text-[#8B949E]">
            <span className="text-[#388BFD] font-semibold">{selectedIds.size}</span> selected
          </span>

          {selectedIds.size > 0 && (
            <>
              {/* Move dropdown */}
              <div className="relative">
                <button
                  onClick={() => setMoveDropdownOpen((o) => !o)}
                  disabled={bulkLoading}
                  className="px-3 py-1 rounded text-xs font-medium border border-[#30363D] bg-[#21262D] text-[#E6EDF3] hover:bg-[#30363D] transition-colors disabled:opacity-40"
                >
                  Move to ▾
                </button>
                {moveDropdownOpen && (
                  <div className="absolute top-full mt-1 left-0 z-50 rounded-md border border-[#30363D] bg-[#161B22] shadow-xl overflow-hidden min-w-[140px]">
                    {COLUMNS.map((col) => (
                      <button
                        key={col.id}
                        onClick={() => handleBulkMove(col.id)}
                        className="w-full text-left px-3 py-2 text-xs text-[#E6EDF3] hover:bg-[#21262D] transition-colors flex items-center gap-2"
                      >
                        <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: col.accent }} />
                        {col.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Delete */}
              <button
                onClick={handleBulkDelete}
                disabled={bulkLoading}
                className="px-3 py-1 rounded text-xs font-medium border border-[#F8514940] bg-[#F8514915] text-[#F85149] hover:bg-[#F8514930] transition-colors disabled:opacity-40"
              >
                {bulkLoading ? 'Working…' : 'Delete'}
              </button>
            </>
          )}
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div className="px-4 py-1.5 bg-[#F8514920] border-b border-[#F8514940] text-[#F85149] text-xs flex-shrink-0">
          {error}
        </div>
      )}

      {/* Legend */}
      <div className="flex items-center gap-4 px-4 py-1.5 bg-[#0D1117] border-b border-[#21262D] flex-shrink-0">
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-0.5 rounded" style={{ background: '#9E68FF' }} />
          <span className="text-[10px] text-[#8B949E]">User ticket (draggable)</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-0.5 rounded" style={{ background: '#FFB633' }} />
          <span className="text-[10px] text-[#8B949E]">Agent task (read-only 🔒)</span>
        </div>
      </div>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* File tree panel */}
        {isFilePanelOpen && <FileTreePanel />}

        {/* Board + detail panel wrapper */}
        <div className="relative flex-1 overflow-hidden">
          {/* Kanban */}
          <div className="h-full overflow-auto p-4">
            {isLoading && tickets.length === 0 ? (
              <div className="flex items-center justify-center h-full text-[#8B949E] text-sm">
                Loading tickets…
              </div>
            ) : (
              <KanbanBoard
                tickets={tickets}
                selectedId={selectedTicket?.id ?? null}
                onTicketClick={selectTicket}
                isMultiSelect={isMultiSelect}
                selectedIds={selectedIds}
                onToggleSelect={toggleSelectId}
              />
            )}
          </div>

          {/* Detail panel */}
          <TicketDetailPanel
            ticket={selectedTicket}
            pendingAssignId={pendingAssignTicketId}
          />
        </div>
      </div>

      {/* Create modal */}
      <CreateTicketModal />
    </div>
  )
}
