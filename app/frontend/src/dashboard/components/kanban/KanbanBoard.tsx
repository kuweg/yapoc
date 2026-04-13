import { DragDropContext, type DropResult } from '@hello-pangea/dnd'
import type { Ticket, TicketStatus } from '../../types'
import { COLUMNS } from '../../types'
import { KanbanColumn } from './KanbanColumn'
import { updateTicket } from '../../api/ticketClient'
import { useDashboardStore } from '../../store/dashboardStore'

interface Props {
  tickets: Ticket[]
  selectedId: string | null
  onTicketClick: (ticket: Ticket) => void
}

export function KanbanBoard({ tickets, selectedId, onTicketClick }: Props) {
  const { upsertTicket, setPendingAssign } = useDashboardStore()

  async function onDragEnd(result: DropResult) {
    if (!result.destination) return
    if (result.source.droppableId === result.destination.droppableId) return

    const ticketId = result.draggableId
    const ticket = tickets.find((t) => t.id === ticketId)
    if (!ticket || ticket.type === 'agent') return  // agent tasks are read-only

    const newStatus = result.destination.droppableId as TicketStatus

    // Optimistic update
    upsertTicket({ ...ticket, status: newStatus })

    try {
      if (newStatus === 'in_progress' && !ticket.assigned_agent) {
        // Needs agent assignment — show the pending assign UI in detail panel
        setPendingAssign(ticketId)
        // Also persist status change
        const updated = await updateTicket(ticketId, { status: newStatus })
        upsertTicket(updated)
      } else {
        const updated = await updateTicket(ticketId, { status: newStatus })
        upsertTicket(updated)
      }
    } catch (err) {
      // Revert on error
      upsertTicket(ticket)
      console.error('Failed to update ticket status', err)
    }
  }

  const byColumn = (colId: TicketStatus) =>
    tickets.filter((t) => t.status === colId)

  return (
    <DragDropContext onDragEnd={onDragEnd}>
      <div className="flex gap-4 overflow-x-auto pb-4 h-full">
        {COLUMNS.map((col) => (
          <KanbanColumn
            key={col.id}
            column={col}
            tickets={byColumn(col.id)}
            selectedId={selectedId}
            onTicketClick={onTicketClick}
          />
        ))}
      </div>
    </DragDropContext>
  )
}
