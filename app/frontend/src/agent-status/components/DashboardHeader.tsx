import { useAgentStore } from '../store/agentStore'
import { useSystemHealth } from '../store/selectors'
import { HealthIndicator } from './shared/HealthIndicator'
import { ThemeToggle } from '../../components/ThemeToggle'

export function DashboardHeader() {
  const { densityMode, setDensityMode } = useAgentStore()
  const health = useSystemHealth()
  const agents = useAgentStore((s) => s.agents)
  const runningCount = agents.filter((a) => a.state === 'running' || a.state === 'spawning').length
  const errorCount = agents.filter((a) => a.state === 'error').length

  return (
    <header className="flex-shrink-0 bg-[#1C2128] border-b border-[#30363D] px-4 py-2.5 flex items-center gap-3">
      {/* Brand — terminal prompt style */}
      <div className="flex items-center gap-2">
        <span className="font-mono font-bold text-[#FFB633] text-sm tracking-widest uppercase">
          &gt; YAPOC
        </span>
        <span className="text-[#484F58] text-xs font-mono tracking-wider uppercase">/ AGENT_MONITOR</span>
      </div>

      {/* System health badge */}
      <div className="flex items-center gap-2 px-2 py-1 bg-[#0D1117] border border-[#21262D]">
        <HealthIndicator health={health} size="sm" />
        {runningCount > 0 && (
          <span className="text-xs text-[#FFB633] font-mono">{runningCount} running</span>
        )}
        {errorCount > 0 && (
          <span className="text-xs text-[#F85149] font-mono">{errorCount} error{errorCount !== 1 ? 's' : ''}</span>
        )}
      </div>

      <div className="flex-1" />

      {/* Theme toggle */}
      <ThemeToggle />

      {/* Density toggle — retro boxy style */}
      <div className="flex items-center gap-1 bg-[#0D1117] border border-[#21262D] p-0.5">
        <button
          onClick={() => setDensityMode('compact')}
          aria-pressed={densityMode === 'compact'}
          title="Compact table view"
          className={`px-2 py-1 text-xs font-mono transition-colors ${
            densityMode === 'compact'
              ? 'bg-[#21262D] text-[#FFB633]'
              : 'text-[#484F58] hover:text-[#8B949E]'
          }`}
        >
          ≡
        </button>
        <button
          onClick={() => setDensityMode('comfortable')}
          aria-pressed={densityMode === 'comfortable'}
          title="Comfortable card view"
          className={`px-2 py-1 text-xs font-mono transition-colors ${
            densityMode === 'comfortable'
              ? 'bg-[#21262D] text-[#FFB633]'
              : 'text-[#484F58] hover:text-[#8B949E]'
          }`}
        >
          ⊞
        </button>
      </div>
    </header>
  )
}
