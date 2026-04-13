import { useAgentStore } from '../../store/agentStore'
import { useFilteredAgents } from '../../store/selectors'
import { AgentCard } from './AgentCard'

const STALE_THRESHOLD_MS = 4000

export function AgentCardGrid() {
  const { selectedAgentName, selectAgent, lastRefreshedAt } = useAgentStore()
  const agents = useFilteredAgents()
  const now = Date.now()

  if (agents.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-sm text-[#484F58]">
        No agents found
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 p-4">
      {agents.map((agent) => {
        const agentUpdated = agent.updated_at ? new Date(agent.updated_at).getTime() : 0
        const isStale = lastRefreshedAt != null && agentUpdated > 0
          && (now - agentUpdated) > STALE_THRESHOLD_MS * 2
        return (
          <AgentCard
            key={agent.name}
            agent={agent}
            onClick={() => selectAgent(selectedAgentName === agent.name ? null : agent.name)}
            isSelected={selectedAgentName === agent.name}
            isStale={isStale}
          />
        )
      })}
    </div>
  )
}
