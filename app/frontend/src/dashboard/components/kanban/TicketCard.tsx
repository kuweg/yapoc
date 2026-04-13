import { Draggable } from '@hello-pangea/dnd'
import type { Ticket } from '../../types'

interface Props {
  ticket: Ticket
  index: number
  isSelected: boolean
  onClick: (ticket: Ticket) => void
}

const STATUS_BADGE: Record<string, { label: string; color: string }> = {
  backlog:     { label: 'Backlog',     color: '#8B949E' },
  in_progress: { label: 'In Progress', color: '#D29922' },
  done:        { label: 'Done',        color: '#3FB950' },
  error:       { label: 'Error',       color: '#F85149' },
}

export function TicketCard({ ticket, index, isSelected, onClick }: Props) {
  const isAgent = ticket.type === 'agent'
  const borderColor = isAgent ? '#FFB633' : '#9E68FF'
  const badge = STATUS_BADGE[ticket.status]

  return (
    <Draggable
      draggableId={ticket.id}
      index={index}
      isDragDisabled={isAgent}
    >
      {(provided, snapshot) => (
        <div
          ref={provided.innerRef}
          {...provided.draggableProps}
          {...provided.dragHandleProps}
          onClick={() => onClick(ticket)}
          className={[
            'rounded-md border border-[#30363D] p-3 cursor-pointer select-none',
            'transition-colors duration-100',
            snapshot.isDragging ? 'opacity-80 shadow-xl' : '',
            isSelected ? 'bg-[#1C2128] border-[#484F58]' : 'bg-[#161B22] hover:bg-[#1C2128]',
          ].join(' ')}
          style={{
            borderLeft: `4px solid ${borderColor}`,
            ...provided.draggableProps.style,
          }}
        >
          {/* Header row */}
          <div className="flex items-start justify-between gap-2 mb-1.5">
            <span className="text-[#E6EDF3] text-xs font-medium leading-tight line-clamp-2 flex-1">
              {ticket.title}
            </span>
            {isAgent && (
              <span className="text-[#8B949E] text-[10px] flex-shrink-0" title="Auto-populated from agent task">
                🔒
              </span>
            )}
          </div>

          {/* Footer row */}
          <div className="flex items-center gap-2 mt-2 flex-wrap">
            {ticket.assigned_agent && (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded-full border"
                style={{ color: borderColor, borderColor: borderColor + '40', background: borderColor + '15' }}
              >
                {ticket.assigned_agent}
              </span>
            )}
            {ticket.parent_agent && ticket.parent_agent !== ticket.assigned_agent && (
              <span className="text-[10px] text-[#484F58]" title={`Spawned by ${ticket.parent_agent}`}>
                ← {ticket.parent_agent}
              </span>
            )}
            {badge && (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded-full ml-auto"
                style={{ color: badge.color, background: badge.color + '20' }}
              >
                {badge.label}
              </span>
            )}
          </div>

          {/* Type label */}
          <div className="mt-1.5 text-[#484F58] text-[10px]">
            {isAgent ? `agent task` : 'user ticket'}
          </div>
        </div>
      )}
    </Draggable>
  )
}
