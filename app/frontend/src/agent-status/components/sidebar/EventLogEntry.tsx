import type { AgentEvent } from '../../types'
import { formatRelativeTime } from '../../hooks/useRelativeTime'

interface Props {
  event: AgentEvent
  onClick?: () => void
  isNew?: boolean
}

const LEVEL_DOT: Record<string, string> = {
  info: 'bg-[#FFB633]',
  warning: 'bg-[#D29922]',
  error: 'bg-[#F85149]',
}

const EVENT_TYPE_LABEL: Record<string, string> = {
  task_assigned: '▶ assigned',
  task_completed: '✓ completed',
  task_failed: '✗ failed',
  status_changed: '↔ changed',
}

export function EventLogEntry({ event, onClick, isNew }: Props) {
  const dot = LEVEL_DOT[event.level] ?? 'bg-[#484F58]'
  const typeLabel = EVENT_TYPE_LABEL[event.event_type] ?? event.event_type

  return (
    <div
      onClick={onClick}
      className={`flex gap-2 px-2 py-1.5 rounded transition-colors text-xs
        ${onClick ? 'cursor-pointer hover:bg-[#21262D]' : ''}
        ${isNew ? 'bg-[#1F3A5F] animate-pulse' : ''}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 mt-[3px] ${dot}`} aria-hidden="true" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 mb-0.5">
          <span
            className="font-mono font-semibold text-[#E6EDF3] truncate cursor-pointer hover:underline"
            onClick={(e) => { e.stopPropagation(); onClick?.() }}
          >
            {event.agent_name}
          </span>
          <span className="text-[#484F58]">{typeLabel}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[#8B949E] truncate flex-1">{event.message}</span>
          <span className="text-[#484F58] whitespace-nowrap flex-shrink-0">
            {formatRelativeTime(event.timestamp)}
          </span>
        </div>
      </div>
    </div>
  )
}
