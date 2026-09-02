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
/** "Today" / "Yesterday" / "Mon 25 Aug" — a day header the eye can scan. */
function dayLabel(iso?: string): string {
  if (!iso) return 'Unknown date'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'Unknown date'
  const today = new Date()
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const diffDays = Math.round((startOf(today) - startOf(d)) / 86_400_000)
  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  return d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })
}

function fmtCost(n?: number): string | null {
  if (typeof n !== 'number' || n <= 0) return null
  return n >= 0.01 ? `$${n.toFixed(2)}` : '<$0.01'
}

/** Wall-clock duration of a task, when both ends are known. */
function fmtElapsed(t: QueuedTask): string | null {
  const a = t.started_at ? Date.parse(t.started_at) : NaN
  const b = t.completed_at ? Date.parse(t.completed_at) : NaN
  if (Number.isNaN(a) || Number.isNaN(b) || b < a) return null
  const s = (b - a) / 1000
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  return `${m}m${Math.round(s - m * 60)}s`
}

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
  const [filter, setFilter] = useState<string>('all')
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)

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

  const counts = tasks.reduce<Record<string, number>>((m, t) => {
    const k = styleFor(t.status).label
    m[k] = (m[k] || 0) + 1
    return m
  }, {})

  const visible = tasks.filter((t) => {
    if (filter !== 'all' && styleFor(t.status).label !== filter) return false
    if (!query.trim()) return true
    const q = query.toLowerCase()
    return (t.prompt || '').toLowerCase().includes(q)
      || (t.assigned_agent || '').toLowerCase().includes(q)
      || (t.source || '').toLowerCase().includes(q)
  })

  const sorted = [...visible].sort((a, b) => {
    const r = rank(a.status) - rank(b.status)
    if (r !== 0) return r
    return (b.created_at || '').localeCompare(a.created_at || '')
  })

  // The list spans days but only ever showed clock times, so "1:20 PM" could be
  // today or last week. Group under day headers instead.
  const groups: Array<{ day: string; items: QueuedTask[] }> = []
  for (const t of sorted) {
    const day = dayLabel(t.created_at)
    const last = groups[groups.length - 1]
    if (last && last.day === day) last.items.push(t)
    else groups.push({ day, items: [t] })
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="px-4 py-3 border-b border-zinc-800 flex items-center gap-3 flex-wrap">
        <h2 className="text-sm font-semibold text-zinc-200">Tasks</h2>
        <span className="text-xs text-zinc-500">{tasks.length} total</span>
        <div className="flex items-center gap-1 flex-wrap">
          {(['all', ...Object.keys(counts)] as string[]).map((k) => (
            <button
              key={k}
              onClick={() => setFilter(k)}
              aria-pressed={filter === k}
              className={`px-2 py-1 text-[13px] font-mono rounded border transition-colors ${
                filter === k
                  ? 'text-[#FFB633] border-[#FFB633] bg-zinc-800'
                  : 'text-zinc-400 border-zinc-700 hover:text-zinc-200'
              }`}
            >
              {k}{k !== 'all' ? ` ${counts[k]}` : ` ${tasks.length}`}
            </button>
          ))}
        </div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter tasks…"
          aria-label="Filter tasks"
          className="px-2 py-1 text-[13px] font-mono bg-zinc-900 border border-zinc-700 rounded text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-[#FFB633] min-w-[160px]"
        />
        {error && <span className="text-xs text-red-400 ml-auto truncate">{error}</span>}
      </div>

      <div className="flex-1 overflow-y-auto divide-y divide-zinc-800/60">
        {sorted.length === 0 && (
          <p className="px-4 py-6 text-sm text-zinc-500 italic">No tasks yet — send a message or delegate work.</p>
        )}
        {groups.map((g) => (
          <div key={g.day}>
            <div className="sticky top-0 z-10 px-4 py-1.5 bg-zinc-900/95 backdrop-blur border-b border-zinc-800 text-[13px] font-mono uppercase tracking-wider text-zinc-500">
              {g.day} <span className="text-zinc-600">· {g.items.length}</span>
            </div>
            {g.items.map((t) => {
          const st = styleFor(t.status)
          const agent = t.assigned_agent || undefined
          const active = st.label === 'running' || st.label === 'blocked'
          const isOpen = expanded === t.id
          const outcome = (t.error || t.result || '').trim()
          const cost = fmtCost(t.cost_usd)
          const elapsed = fmtElapsed(t)
          return (
            <div
              key={t.id}
              onClick={() => setExpanded(isOpen ? null : t.id)}
              className="px-4 py-2.5 flex items-start gap-3 hover:bg-zinc-800/40 transition-colors cursor-pointer">
              <span
                className="mt-0.5 px-2 py-0.5 rounded text-[12px] font-mono uppercase tracking-wide flex-shrink-0 inline-flex items-center"
                style={{ color: st.color, backgroundColor: st.bg }}
              >
                {active && <span className="inline-block w-1.5 h-1.5 rounded-full mr-1 animate-pulse" style={{ backgroundColor: st.color }} />}
                {st.label}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm text-zinc-200 truncate">{t.prompt || '(no prompt)'}</p>
                <div className="flex items-center gap-2 mt-0.5 text-[13px] text-zinc-500">
                  {agent && (
                    <span className="inline-flex items-center gap-1" style={{ color: getAgentColor(agent) }}>
                      <AgentAvatar name={agent} size={12} /> {agent}
                    </span>
                  )}
                  {t.source && <span>· {t.source}</span>}
                  {cost && <span>· {cost}</span>}
                  {elapsed && <span>· {elapsed}</span>}
                  {t.created_at && (
                    <span className="ml-auto whitespace-nowrap">
                      {new Date(t.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  )}
                </div>
                {/* What actually happened — the list used to show only what was
                    asked, so every row looked identical. */}
                {outcome && (
                  <p
                    className={`text-[13px] mt-1 ${t.error ? 'text-red-400/80' : 'text-zinc-400'} ${
                      isOpen ? 'whitespace-pre-wrap break-words' : 'truncate'
                    }`}
                  >
                    {isOpen ? outcome : outcome.replace(/\s+/g, ' ').slice(0, 200)}
                  </p>
                )}
                {!outcome && !active && (
                  <p className="text-[13px] mt-1 text-zinc-600 italic">No output recorded</p>
                )}
              </div>
            </div>
          )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}
