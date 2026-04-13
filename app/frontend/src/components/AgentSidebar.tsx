import { useState } from 'react'
import { AgentCard } from './AgentCard'
import { useAgents } from '../hooks/useAgents'
import { spawnAgent, killAgent } from '../api/client'

export function AgentSidebar() {
  const { agents, error, refresh } = useAgents()
  const [selected, setSelected] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  async function handleSpawn() {
    if (!selected) return
    try {
      await spawnAgent(selected)
      setActionError(null)
      refresh()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    }
  }

  async function handleKill() {
    if (!selected) return
    try {
      await killAgent(selected)
      setActionError(null)
      refresh()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <aside className="flex flex-col bg-zinc-900 border-r border-zinc-700 w-60 min-w-[15rem] flex-shrink-0">
      <div className="px-4 py-3 border-b border-zinc-700">
        <h2 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Agents</h2>
        {(error ?? actionError) && (
          <p className="text-xs text-red-400 mt-1 truncate">{actionError ?? error}</p>
        )}
      </div>

      <div className="flex-1 overflow-y-auto divide-y divide-zinc-800">
        {agents.map((agent) => (
          <AgentCard
            key={agent.name}
            agent={agent}
            selected={selected === agent.name}
            onClick={() => setSelected((s) => (s === agent.name ? null : agent.name))}
          />
        ))}
        {agents.length === 0 && (
          <p className="px-4 py-3 text-xs text-zinc-500 italic">No agents found</p>
        )}
      </div>

      <div className="px-4 py-3 border-t border-zinc-700 flex gap-2">
        <button
          onClick={handleSpawn}
          disabled={!selected}
          className="flex-1 rounded bg-zinc-700 px-2 py-1 text-xs text-zinc-200 hover:bg-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Spawn
        </button>
        <button
          onClick={handleKill}
          disabled={!selected}
          className="flex-1 rounded bg-zinc-700 px-2 py-1 text-xs text-zinc-200 hover:bg-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Kill
        </button>
      </div>
    </aside>
  )
}
