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

export function AgentCard({ agent, onClick, isSelected, isStale }: Props) {
  return (
    <div
      role="button"
      tabIndex={0}
      aria-pressed={isSelected}
      onClick={onClick}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onClick()}
      className={`border p-3 cursor-pointer transition-colors
        focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#FFB633]
        ${isSelected
          ? 'bg-[#1C2128] border-[#FFB633] shadow-[0_0_8px_rgba(255,182,51,0.2)]'
          : 'bg-[#161B22] border-[#30363D] hover:border-[#FFB633] hover:shadow-[0_0_6px_rgba(255,182,51,0.1)]'}
        ${agent.state === 'error' ? 'border-l-2 border-l-[#DA3633]' : ''}`}
    >
      {/* Header row */}
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="font-mono text-base text-[#E6EDF3] font-medium truncate">{agent.name}</span>
        <StatusBadge state={agent.state} size="sm" />
      </div>

      {/* Health + model */}
      <div className="flex items-center justify-between gap-2 mb-2">
        <HealthIndicator health={agent.health} errorCount={agent.health_errors || undefined} size="sm" />
        <ModelTag model={agent.model} adapter={agent.adapter} />
      </div>

      {/* Task summary */}
      {agent.task_summary && (
        <p className="text-sm text-[#8B949E] truncate mb-1.5 font-mono" title={agent.task_summary}>
          {agent.task_summary}
        </p>
      )}

      {/* Footer */}
      <div className="flex items-center gap-2 text-sm text-[#484F58] font-mono">
        {agent.pid && <span>pid:{agent.pid}</span>}
        <span className="flex-1" />
        <TimestampCell timestamp={agent.updated_at} isStale={isStale} />
      </div>
    </div>
  )
}
