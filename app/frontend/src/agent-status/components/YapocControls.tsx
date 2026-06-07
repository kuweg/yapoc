import { useState } from 'react'
import { useAgents } from '../../hooks/useAgents'
import { killAgent, startBackend } from '../../api/client'

const RUNNING = new Set(['running', 'busy', 'spawning'])

/**
 * YAPOC lifecycle controls (Agents tab): Start the backend (when it's down) and
 * Stop all agents. master is excluded from Stop-all — it runs in-process, so its
 * pid is the backend's; killing it would take the whole server down.
 */
export function YapocControls() {
  const { agents, backendDown, refresh } = useAgents()
  const [busy, setBusy] = useState<'start' | 'stop' | null>(null)
  const [msg, setMsg] = useState<string | null>(null)

  const killable = agents.filter(
    (a) => a.name !== 'master' && (a.pid != null || RUNNING.has(String(a.status || a.process_state || ''))),
  )

  async function handleStart() {
    setBusy('start')
    setMsg(null)
    try {
      await startBackend()
      setMsg('starting…')
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    }
    // Backend takes a few seconds to bind; clear busy and re-poll afterwards.
    setTimeout(() => { setBusy(null); refresh() }, 3000)
  }

  async function handleStopAll() {
    if (!killable.length) return
    setBusy('stop')
    setMsg(null)
    const results = await Promise.allSettled(killable.map((a) => killAgent(a.name)))
    const failed = results.filter((r) => r.status === 'rejected').length
    setMsg(failed ? `${failed}/${killable.length} failed` : null)
    setBusy(null)
    refresh()
  }

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={handleStart}
        disabled={busy !== null || !backendDown}
        title={backendDown ? 'Start the YAPOC backend' : 'Backend is already running'}
        className="px-2.5 py-1 text-xs font-mono border border-[#2ea043] text-[#3fb950] hover:bg-[#2ea043] hover:text-[#0D1117] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        ▶ {busy === 'start' ? 'Starting…' : 'Start yapoc'}
      </button>
      <button
        onClick={handleStopAll}
        disabled={busy !== null || killable.length === 0}
        title="Stop all agents (master/backend is never killed)"
        className="px-2.5 py-1 text-xs font-mono border border-[#da3633] text-[#f85149] hover:bg-[#da3633] hover:text-[#0D1117] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        ■ {busy === 'stop' ? 'Stopping…' : 'Stop all'}{killable.length > 0 ? ` (${killable.length})` : ''}
      </button>
      {(msg || backendDown) && (
        <span className="text-[11px] font-mono text-[#8B949E] truncate max-w-[14rem]">
          {msg || (backendDown ? 'backend down' : '')}
        </span>
      )}
    </div>
  )
}
