import type { AgentStatus } from '../../types'
import { StatusBadge } from '../shared/StatusBadge'
import { HealthIndicator } from '../shared/HealthIndicator'
import { ModelTag } from '../shared/ModelTag'
import { TimestampCell } from '../shared/TimestampCell'

interface Props {
  agent: AgentStatus
  onClick: () => void
  isSelected: boolean
  isStale: boolean
}

export function AgentRow({ agent, onClick, isSelected, isStale }: Props) {
  const isError = agent.state === 'error'

  return (
    <tr
      role="row"
      tabIndex={0}
      aria-selected={isSelected}
      onClick={onClick}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onClick()}
      className={`relative border-b border-[#21262D] cursor-pointer transition-colors
        ${isSelected ? 'bg-[#1C2128]' : 'hover:bg-[#21262D]'}
        ${isError ? 'border-l-2 border-l-[#DA3633]' : ''}
        focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#FFB633]`}
    >
      {/* Agent name */}
      <td className="px-4 py-2.5 font-mono text-sm text-[#E6EDF3] whitespace-nowrap">
        {agent.name}
        {agent.pid && (
          <span className="ml-2 text-[12px] text-[#484F58]">pid:{agent.pid}</span>
        )}
      </td>

      {/* Status */}
      <td className="px-4 py-2.5">
        <StatusBadge state={agent.state} size="sm" />
      </td>

      {/* Health */}
      <td className="px-4 py-2.5">
        <HealthIndicator health={agent.health} errorCount={agent.health_errors || undefined} size="sm" />
      </td>

      {/* Model — hidden on mobile/tablet */}
      <td className="px-4 py-2.5 hidden xl:table-cell">
        <ModelTag model={agent.model} adapter={agent.adapter} />
      </td>

      {/* Last task */}
      <td className="px-4 py-2.5 max-w-[200px]">
        {agent.task_summary ? (
          <span
            className="text-sm text-[#8B949E] truncate block"
            title={agent.task_summary}
          >
            {agent.task_summary}
          </span>
        ) : (
          <span className="text-sm text-[#484F58]">—</span>
        )}
      </td>

      {/* Last activity */}
      <td className="px-4 py-2.5 whitespace-nowrap">
        <TimestampCell timestamp={agent.updated_at} isStale={isStale} />
      </td>
    </tr>
  )
}
