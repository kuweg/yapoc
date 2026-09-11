import { X as XMarkIcon } from 'lucide-react'
import { useState } from 'react'
import { AgentOffice, officeState } from './AgentOffice'
import { useAgentChatStore } from '../store/agentChatStore'
import { AgentCard } from './AgentCard'
import { useAgents } from '../hooks/useAgents'
import { spawnAgent, killAgent } from '../api/client'
import { useWindowsStore } from '../store/windowsStore'

export function AgentSidebar({ onClose }: { onClose?: () => void }) {
  const { agents, error, backendDown, refresh } = useAgents()
  const [view, setView] = useState<'office' | 'list'>(() => { try { return localStorage.getItem('yapoc-team-view') === 'list' ? 'list' : 'office' } catch { return 'office' } })
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

  const working = agents.filter(a => officeState(a, Boolean(error)) === 'working').length
  const ordered = [...agents].sort((a, b) => {
    if (a.name === 'master') return -1
    if (b.name === 'master') return 1
    return Number(['running', 'busy', 'spawning'].includes(b.status || b.process_state || '')) - Number(['running', 'busy', 'spawning'].includes(a.status || a.process_state || ''))
  })

  return (
    <aside className="studio-team" aria-label="Agent team">
      <div className="studio-team-header">
        <div><p className="studio-eyebrow">THE COLLECTIVE</p><h2>Your agent team <span>{agents.length}</span></h2></div>
        {onClose && <button className="studio-icon-button" onClick={onClose} aria-label="Hide agent team"><XMarkIcon /></button>}
        {(error ?? actionError) && !backendDown && (
          <p className="text-xs text-red-400 mt-1 truncate">{actionError ?? error}</p>
        )}
      </div>

      {backendDown && (
        <div className="px-4 py-2 bg-red-950/60 border-b border-red-800/40 flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-red-500 animate-pulse flex-shrink-0" />
          <span className="text-[13px] text-red-400 font-medium">Backend unavailable</span>
        </div>
      )}

      <div className="studio-team-summary"><span className={error ? 'is-offline' : ''} />{error ? 'Waiting for connection' : working ? `${working} agent${working === 1 ? '' : 's'} working` : 'No agents working right now'}</div>
      <div className="office-view-switch" aria-label="Team view">
        {(['office', 'list'] as const).map(mode => <button key={mode} aria-pressed={view === mode} onClick={() => { setView(mode); try { localStorage.setItem('yapoc-team-view', mode) } catch { /* private browsing */ } }}>{mode === 'office' ? 'Building' : 'List'}</button>)}
      </div>
      <div className="studio-team-list">
        {view === 'office' ? <AgentOffice agents={ordered} disconnected={Boolean(error)} onOpen={agent => { setSelected(agent.name); useAgentChatStore.getState().setSelectedLogAgent(agent.name); if (window.matchMedia('(max-width: 1000px)').matches) onClose?.() }} /> : <>

        {ordered.map((agent) => (
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
        </>}
      </div>

      <div className="studio-team-footer flex flex-col gap-2">
        <button
          onClick={handleOpenLogs}
          disabled={!selected}
          className="w-full rounded border border-zinc-600 bg-transparent px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-700 hover:text-zinc-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          View agent logs
        </button>
        <div className="flex gap-2">
          <button
            onClick={handleSpawn}
            disabled={!selected}
            className="flex-1 rounded border border-[#FFB633] bg-transparent px-2 py-1 text-xs text-[#FFB633] hover:bg-[#FFB633] hover:text-[#0a0a0a] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Start agent
          </button>
          <button
            onClick={handleKill}
            disabled={!selected || selected === 'master'}
            title={selected === 'master' ? 'master runs the backend — cannot be killed' : undefined}
            className="flex-1 rounded border border-[#FFB633] bg-transparent px-2 py-1 text-xs text-[#FFB633] hover:bg-[#FFB633] hover:text-[#0a0a0a] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Stop agent
          </button>
        </div>
      </div>
    </aside>
  )
}
