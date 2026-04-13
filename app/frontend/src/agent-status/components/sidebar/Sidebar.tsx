import { useAgentStore } from '../../store/agentStore'
import { useStatusCounts, useSystemHealth } from '../../store/selectors'
import { HealthIndicator } from '../shared/HealthIndicator'
import { EventLogFeed } from './EventLogFeed'

export function Sidebar() {
  const agents = useAgentStore((s) => s.agents)
  const counts = useStatusCounts()
  const doneCount = agents.filter((a) => a.state === 'done').length
  const systemHealth = useSystemHealth()

  const criticalCount = agents.filter((a) => a.health === 'critical').length
  const warningCount = agents.filter((a) => a.health === 'warning').length

  // Group adapter usage
  const adapterCounts = agents.reduce<Record<string, number>>((acc, a) => {
    const key = a.adapter || 'unknown'
    acc[key] = (acc[key] ?? 0) + 1
    return acc
  }, {})

  const ADAPTER_COLORS: Record<string, string> = {
    anthropic: 'text-[#FFB633]',
    openai: 'text-[#3FB950]',
    ollama: 'text-[#D29922]',
    openrouter: 'text-[#a78bfa]',
  }

  return (
    <aside
      aria-label="System overview sidebar"
      className="w-[280px] flex-shrink-0 hidden md:flex flex-col bg-[#1C2128] border-l border-[#30363D]
        overflow-hidden"
    >
      {/* System Summary */}
      <div className="px-3 py-3 border-b border-[#30363D]">
        <p className="text-[10px] uppercase tracking-widest text-[#484F58] mb-2">System</p>
        <div className="flex items-center gap-2 mb-2">
          <HealthIndicator health={systemHealth} size="sm" />
          <span className="text-xs text-[#8B949E]">{agents.length} agent{agents.length !== 1 ? 's' : ''}</span>
        </div>
        <div className="grid grid-cols-4 gap-1">
          {([
            { key: 'running', count: counts.running, color: 'text-[#FFB633]' },
            { key: 'idle', count: counts.idle, color: 'text-[#8B949E]' },
            { key: 'error', count: counts.error, color: 'text-[#F85149]' },
            { key: 'done', count: doneCount, color: 'text-[#3FB950]' },
          ] as const).map(({ key, count, color }) => (
            <div key={key} className="text-center">
              <div className={`text-sm font-semibold tabular-nums ${color}`}>{count}</div>
              <div className="text-[9px] text-[#484F58] capitalize">{key}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Health Overview */}
      {(criticalCount > 0 || warningCount > 0) && (
        <div className="px-3 py-2 border-b border-[#30363D]">
          <p className="text-[10px] uppercase tracking-widest text-[#484F58] mb-1.5">Health</p>
          <div className="space-y-1">
            {criticalCount > 0 && (
              <div className="flex items-center justify-between text-xs">
                <span className="text-[#F85149]">✗ Critical</span>
                <span className="text-[#F85149] font-semibold tabular-nums">{criticalCount}</span>
              </div>
            )}
            {warningCount > 0 && (
              <div className="flex items-center justify-between text-xs">
                <span className="text-[#D29922]">⚠ Warning</span>
                <span className="text-[#D29922] font-semibold tabular-nums">{warningCount}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Active Models */}
      {Object.keys(adapterCounts).length > 0 && (
        <div className="px-3 py-2 border-b border-[#30363D]">
          <p className="text-[10px] uppercase tracking-widest text-[#484F58] mb-1.5">Adapters</p>
          <div className="space-y-1">
            {Object.entries(adapterCounts).map(([adapter, count]) => (
              <div key={adapter} className="flex items-center justify-between text-xs">
                <span className={`font-mono font-semibold ${ADAPTER_COLORS[adapter] ?? 'text-[#8B949E]'}`}>
                  {adapter}
                </span>
                <span className="text-[#484F58] tabular-nums">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Event Log — takes remaining space */}
      <div className="flex-1 overflow-hidden">
        <EventLogFeed />
      </div>
    </aside>
  )
}
