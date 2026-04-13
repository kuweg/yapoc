import { useAgentStore } from '../../store/agentStore'
import { useFilteredAgents } from '../../store/selectors'
import { AgentRow } from './AgentRow'

const STALE_THRESHOLD_MS = 4000

export function AgentTable() {
  const { selectedAgentName, selectAgent, lastRefreshedAt } = useAgentStore()
  const agents = useFilteredAgents()
  const now = Date.now()

  return (
    <div className="overflow-x-auto">
      <table
        role="grid"
        aria-label="Agent status table"
        aria-rowcount={agents.length}
        className="w-full border-collapse text-left"
      >
        <thead>
          <tr className="border-b border-[#30363D]">
            {['Agent', 'Status', 'Health', 'Model', 'Last Task', 'Activity'].map((col, i) => (
              <th
                key={col}
                role="columnheader"
                className={`px-4 py-2 text-[10px] font-semibold uppercase tracking-widest text-[#484F58]
                  ${i === 3 ? 'hidden xl:table-cell' : ''}`}
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {agents.length === 0 && (
            <tr>
              <td colSpan={6} className="px-4 py-8 text-center text-sm text-[#484F58]">
                No agents found
              </td>
            </tr>
          )}
          {agents.map((agent) => {
            const agentUpdated = agent.updated_at ? new Date(agent.updated_at).getTime() : 0
            const isStale = lastRefreshedAt != null && agentUpdated > 0
              && (now - agentUpdated) > STALE_THRESHOLD_MS * 2
            return (
              <AgentRow
                key={agent.name}
                agent={agent}
                onClick={() => selectAgent(selectedAgentName === agent.name ? null : agent.name)}
                isSelected={selectedAgentName === agent.name}
                isStale={isStale}
              />
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
