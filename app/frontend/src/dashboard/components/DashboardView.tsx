import { useEffect, useRef } from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import { getTickets } from '../api/ticketClient'
import { KanbanBoard } from './kanban/KanbanBoard'
import { TicketDetailPanel } from './detail/TicketDetailPanel'
import { CreateTicketModal } from './modals/CreateTicketModal'
import { FileTreePanel } from './files/FileTreePanel'

const POLL_INTERVAL = 8_000  // ms

export function DashboardView() {
  const {
    tickets, setTickets, selectedTicket, selectTicket,
    setCreateOpen,
    pendingAssignTicketId,
    isFilePanelOpen, toggleFilePanel,
    isLoading, setLoading, error, setError,
  } = useDashboardStore()

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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

          {/* New ticket */}
          <button
            onClick={() => setCreateOpen(true)}
            className="px-3 py-1 rounded bg-[#238636] text-white text-xs font-medium hover:bg-[#2EA043] transition-colors"
          >
            + New Ticket
          </button>
        </div>
      </div>

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
