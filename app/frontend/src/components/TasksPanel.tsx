import { useEffect, useState, useRef } from 'react'
import { getTasks, type QueuedTask } from '../api/client'
import { AgentAvatar, getAgentColor } from '../lib/agentIdentity'

const STATUS_STYLE: Record<string, { label: string; color: string; bg: string }> = {
  pending: { label: 'queued', color: '#a1a1aa', bg: 'rgba(161,161,170,0.12)' },
  queued: { label: 'queued', color: '#a1a1aa', bg: 'rgba(161,161,170,0.12)' },
  running: { label: 'running', color: '#fbbf24', bg: 'rgba(251,191,36,0.14)' },
  in_progress: { label: 'running', color: '#fbbf24', bg: 'rgba(251,191,36,0.14)' },
  blocked: { label: 'blocked', color: '#f97316', bg: 'rgba(249,115,22,0.14)' },
  done: { label: 'done', color: '#34d399', bg: 'rgba(52,211,153,0.12)' },
  completed: { label: 'done', color: '#34d399', bg: 'rgba(52,211,153,0.12)' },
  error: { label: 'error', color: '#f87171', bg: 'rgba(248,113,113,0.14)' },
  failed: { label: 'error', color: '#f87171', bg: 'rgba(248,113,113,0.14)' },
  cancelled: { label: 'cancelled', color: '#71717a', bg: 'rgba(113,113,122,0.10)' },
}

function styleFor(status: string) {
  return STATUS_STYLE[(status || '').toLowerCase()] ?? { label: status || '—', color: '#a1a1aa', bg: 'rgba(161,161,170,0.12)' }
}

// Active work first, then the rest by recency.
const ORDER = ['running', 'in_progress', 'blocked', 'pending', 'queued', 'error', 'failed', 'done', 'completed', 'cancelled']
function rank(status: string) {
  const i = ORDER.indexOf((status || '').toLowerCase())
  return i < 0 ? ORDER.length : i
}

/**
 * Live shared task list — the swarm's source of truth for what's done /
 * in-progress / blocked. Polls the backend task_queue (~2.5s) and renders each
 * task with its assigned agent's identity (avatar + color from agentIdentity).
 */
export function TasksPanel() {
  const [tasks, setTasks] = useState<QueuedTask[]>([])
  const [error, setError] = useState<string | null>(null)
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const t = await getTasks(60)
        if (alive) { setTasks(t); setError(null) }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e))
      }
    }
    tick()
    timerRef.current = window.setInterval(tick, 2500)
    return () => { alive = false; if (timerRef.current) window.clearInterval(timerRef.current) }
  }, [])

  const sorted = [...tasks].sort((a, b) => {
    const r = rank(a.status) - rank(b.status)
    if (r !== 0) return r
    return (b.created_at || '').localeCompare(a.created_at || '')
  })
  const counts = tasks.reduce<Record<string, number>>((m, t) => {
    const k = styleFor(t.status).label
    m[k] = (m[k] || 0) + 1
    return m
  }, {})

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="px-4 py-3 border-b border-zinc-800 flex items-center gap-3 flex-wrap">
        <h2 className="text-sm font-semibold text-zinc-200">Tasks</h2>
        <span className="text-xs text-zinc-500">{tasks.length} total</span>
        {Object.entries(counts).map(([k, n]) => (
          <span key={k} className="text-[11px] text-zinc-400">{k}: {n}</span>
        ))}
        {error && <span className="text-xs text-red-400 ml-auto truncate">{error}</span>}
      </div>

      <div className="flex-1 overflow-y-auto divide-y divide-zinc-800/60">
        {sorted.length === 0 && (
          <p className="px-4 py-6 text-sm text-zinc-500 italic">No tasks yet — send a message or delegate work.</p>
        )}
        {sorted.map((t) => {
          const st = styleFor(t.status)
          const agent = t.assigned_agent || undefined
          const active = st.label === 'running' || st.label === 'blocked'
          return (
            <div key={t.id} className="px-4 py-2.5 flex items-start gap-3 hover:bg-zinc-800/40 transition-colors">
              <span
                className="mt-0.5 px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wide flex-shrink-0 inline-flex items-center"
                style={{ color: st.color, backgroundColor: st.bg }}
              >
                {active && <span className="inline-block w-1.5 h-1.5 rounded-full mr-1 animate-pulse" style={{ backgroundColor: st.color }} />}
                {st.label}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm text-zinc-200 truncate">{t.prompt || '(no prompt)'}</p>
                <div className="flex items-center gap-2 mt-0.5 text-[11px] text-zinc-500">
                  {agent && (
                    <span className="inline-flex items-center gap-1" style={{ color: getAgentColor(agent) }}>
                      <AgentAvatar name={agent} size={12} /> {agent}
                    </span>
                  )}
                  {t.source && <span>· {t.source}</span>}
                  {typeof t.cost_usd === 'number' && t.cost_usd > 0 && <span>· ${t.cost_usd.toFixed(4)}</span>}
                  {t.created_at && <span className="ml-auto whitespace-nowrap">{new Date(t.created_at).toLocaleTimeString()}</span>}
                </div>
                {t.error && <p className="text-[11px] text-red-400/80 mt-0.5 truncate">{t.error}</p>}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
