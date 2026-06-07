import { useState } from 'react'
import { AgentCard } from './AgentCard'
import { useAgents } from '../hooks/useAgents'
import { spawnAgent, killAgent } from '../api/client'
import { useWindowsStore } from '../store/windowsStore'

export function AgentSidebar() {
  const { agents, error, backendDown, refresh } = useAgents()
  const [selected, setSelected] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const openAgentLog = useWindowsStore((s) => s.openAgentLog)

  function handleOpenLogs() {
    if (!selected) return
    const a = agents.find((x) => x.name === selected)
    openAgentLog(selected, String(a?.process_state || a?.status || 'idle'))
  }

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
    if (selected === 'master') {
      // master runs in-process — its pid is the backend's. Killing it stops yapoc.
      setActionError('Cannot kill master — it runs the backend')
      return
    }
    try {
      await killAgent(selected)
      setActionError(null)
      refresh()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <aside className="flex flex-col bg-zinc-900 border-r border-zinc-700 w-48 min-w-[12rem] flex-shrink-0 max-md:w-36 max-md:min-w-[9rem] max-sm:hidden">
      <div className="px-4 py-3 border-b border-zinc-700">
        <h2 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Agents</h2>
        {(error ?? actionError) && !backendDown && (
          <p className="text-xs text-red-400 mt-1 truncate">{actionError ?? error}</p>
        )}
      </div>

      {backendDown && (
        <div className="px-4 py-2 bg-red-950/60 border-b border-red-800/40 flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-red-500 animate-pulse flex-shrink-0" />
          <span className="text-[11px] text-red-400 font-medium">Backend unavailable</span>
        </div>
      )}

      <div className="flex-1 overflow-y-auto divide-y divide-zinc-800">
        {agents.map((agent) => (
          <AgentCard
            key={agent.name}
            agent={backendDown ? { ...agent, status: 'error', process_state: 'error', state: 'error' } : agent}
            selected={selected === agent.name}
            onClick={() => setSelected((s) => (s === agent.name ? null : agent.name))}
          />
        ))}
        {agents.length === 0 && (
          <p className="px-4 py-3 text-xs text-zinc-500 italic">No agents found</p>
        )}
      </div>

      <div className="px-4 py-3 border-t border-zinc-700 flex flex-col gap-2">
        <button
          onClick={handleOpenLogs}
          disabled={!selected}
          className="w-full rounded border border-zinc-600 bg-transparent px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-700 hover:text-zinc-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          Open Logs ⊟
        </button>
        <div className="flex gap-2">
          <button
            onClick={handleSpawn}
            disabled={!selected}
            className="flex-1 rounded border border-[#FFB633] bg-transparent px-2 py-1 text-xs text-[#FFB633] hover:bg-[#FFB633] hover:text-[#0a0a0a] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Spawn
          </button>
          <button
            onClick={handleKill}
            disabled={!selected || selected === 'master'}
            title={selected === 'master' ? 'master runs the backend — cannot be killed' : undefined}
            className="flex-1 rounded border border-[#FFB633] bg-transparent px-2 py-1 text-xs text-[#FFB633] hover:bg-[#FFB633] hover:text-[#0a0a0a] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Kill
          </button>
        </div>
      </div>
    </aside>
  )
}
