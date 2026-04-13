import { useState } from 'react'
import { useAgentStore } from '../store/agentStore'
import { FilterBar } from './filter/FilterBar'
import { AgentTable } from './table/AgentTable'
import { AgentCardGrid } from './cards/AgentCardGrid'
import { Sidebar } from './sidebar/Sidebar'
import { AgentDetailPanel } from './detail/AgentDetailPanel'
import { CpuUsageChart } from './metrics/CpuUsageChart'

export function DashboardLayout() {
  const { densityMode, selectedAgentName } = useAgentStore()
  const [showCpuChart, setShowCpuChart] = useState(false)

  return (
    <div className="flex flex-1 overflow-hidden relative">
      {/* Main content */}
      <div
        className={`flex flex-col flex-1 overflow-hidden transition-all duration-300 ${
          selectedAgentName ? 'mr-0 md:mr-[480px]' : ''
        }`}
      >
        <FilterBar />
        <div className="flex-1 overflow-y-auto bg-[#0D1117]">
          {densityMode === 'compact' ? <AgentTable /> : <AgentCardGrid />}
        </div>

        {/* CPU Usage Chart — collapsible footer panel */}
        <div className="flex-shrink-0 border-t border-[#21262D] bg-[#0D1117]">
          <button
            onClick={() => setShowCpuChart((v) => !v)}
            aria-expanded={showCpuChart}
            className="w-full flex items-center gap-2 px-4 py-2 text-[10px] uppercase tracking-widest
              text-[#484F58] hover:text-[#8B949E] hover:bg-[#161B22] transition-colors text-left"
          >
            <span
              className="inline-block transition-transform duration-200"
              style={{ transform: showCpuChart ? 'rotate(90deg)' : 'rotate(0deg)' }}
            >
              ▶
            </span>
            CPU &amp; Memory Usage
          </button>
          {showCpuChart && (
            <div className="px-4 pb-4">
              <CpuUsageChart />
            </div>
          )}
        </div>
      </div>

      {/* Sidebar */}
      <Sidebar />

      {/* Detail panel (slides in over content) */}
      <AgentDetailPanel />
    </div>
  )
}
