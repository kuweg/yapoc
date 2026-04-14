import { Droppable } from '@hello-pangea/dnd'
import type { Ticket, ColumnDef } from '../../types'
import { TicketCard } from './TicketCard'

interface Props {
  column: ColumnDef
  tickets: Ticket[]
  selectedId: string | null
  onTicketClick: (ticket: Ticket) => void
  isMultiSelect?: boolean
  selectedIds?: Set<string>
  onToggleSelect?: (id: string) => void
}

export function KanbanColumn({ column, tickets, selectedId, onTicketClick, isMultiSelect, selectedIds, onToggleSelect }: Props) {
  return (
    <div className="flex flex-col min-w-[240px] w-[240px] flex-shrink-0">
      {/* Column header */}
      <div
        className="flex items-center gap-2 px-3 py-2 rounded-t-md border-t-2 border-x border-[#30363D] bg-[#161B22]"
        style={{ borderTopColor: column.accent }}
      >
        <span className="text-[#E6EDF3] text-xs font-semibold flex-1">{column.label}</span>
        <span
          className="text-[10px] px-1.5 py-0.5 rounded-full font-medium"
          style={{ color: column.accent, background: column.accent + '20' }}
        >
          {tickets.length}
        </span>
      </div>

      {/* Droppable area */}
      <Droppable droppableId={column.id}>
        {(provided, snapshot) => (
          <div
            ref={provided.innerRef}
            {...provided.droppableProps}
            className={[
              'flex-1 flex flex-col gap-2 p-2 rounded-b-md border-x border-b border-[#30363D] min-h-[120px] transition-colors duration-150',
              snapshot.isDraggingOver ? 'bg-[#1C2128]' : 'bg-[#0D1117]',
            ].join(' ')}
          >
            {tickets.map((ticket, index) => (
              <TicketCard
                key={ticket.id}
                ticket={ticket}
                index={index}
                isSelected={ticket.id === selectedId}
                onClick={onTicketClick}
                isMultiSelect={isMultiSelect}
                isChecked={selectedIds?.has(ticket.id)}
                onToggleSelect={onToggleSelect}
              />
            ))}
            {provided.placeholder}
          </div>
        )}
      </Droppable>
    </div>
  )
}
