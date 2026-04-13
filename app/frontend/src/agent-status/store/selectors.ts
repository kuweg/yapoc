import { useAgentStore } from './agentStore'
import type { AgentStatus, StatusFilterType, SortBy } from '../types'

function sortAgents(agents: AgentStatus[], sortBy: SortBy): AgentStatus[] {
  const order: Record<string, number> = { running: 0, error: 1, idle: 2, done: 3, '': 4 }
  return [...agents].sort((a, b) => {
    switch (sortBy) {
      case 'status':
        return (order[a.state] ?? 2) - (order[b.state] ?? 2)
      case 'name':
        return a.name.localeCompare(b.name)
      case 'activity': {
        const ta = a.updated_at ?? a.idle_since ?? ''
        const tb = b.updated_at ?? b.idle_since ?? ''
        return tb.localeCompare(ta)
      }
      case 'health': {
        const hord: Record<string, number> = { critical: 0, warning: 1, ok: 2 }
        return (hord[a.health] ?? 2) - (hord[b.health] ?? 2)
      }
      default:
        return 0
    }
  })
}

function matchesFilter(agent: AgentStatus, filter: StatusFilterType): boolean {
  if (filter === 'all') return true
  if (filter === 'running') return agent.state === 'running'
  if (filter === 'idle') return agent.state === 'idle' || agent.state === 'terminated' || agent.state === ''
  if (filter === 'error') return agent.health === 'critical' || agent.health === 'warning'
  return true
}

export function useFilteredAgents() {
  const { agents, activeFilter, searchQuery, sortBy } = useAgentStore()
  let result = agents.filter((a) => matchesFilter(a, activeFilter))
  if (searchQuery.trim()) {
    const q = searchQuery.toLowerCase()
    result = result.filter((a) => a.name.toLowerCase().includes(q))
  }
  return sortAgents(result, sortBy)
}

export function useStatusCounts() {
  const agents = useAgentStore((s) => s.agents)
  return {
    all: agents.length,
    running: agents.filter((a) => a.state === 'running').length,
    idle: agents.filter((a) => a.state === 'idle' || a.state === 'terminated' || a.state === '').length,
    error: agents.filter((a) => a.health !== 'ok').length,
  }
}

export function useSystemHealth() {
  const agents = useAgentStore((s) => s.agents)
  if (agents.some((a) => a.health === 'critical')) return 'critical'
  if (agents.some((a) => a.health === 'warning')) return 'warning'
  return 'ok'
}
