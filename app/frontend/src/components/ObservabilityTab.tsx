import { useCallback, useEffect, useState } from 'react'

interface ObservabilityTotals {
  total_cost_usd: number
  total_tasks: number
  active_agents: number
  agents_with_errors: number
  recent_error_count: number
}

interface ObservabilityAgent {
  name: string
  status: string
  is_alive: boolean
  cost_usd: number
  input_tokens: number
  output_tokens: number
  task_count: number
  health_issues: number
  last_active_at: string | null
  models: string[]
}

interface ObservabilityError {
  agent: string
  timestamp: string
  level: string
  message: string
}

interface ObservabilityTask {
  agent: string
  task_id: string
  status: string
  assigned_by: string
  assigned_at: string
  completed_at: string
  duration_s: number | null
  task_summary: string
  error_summary: string
}

interface ObservabilityDashboard {
  generated_at: string
  totals: ObservabilityTotals
  agents: ObservabilityAgent[]
  recent_errors: ObservabilityError[]
  recent_tasks: ObservabilityTask[]
}

type SortKey = 'cost' | 'tokens' | 'tasks' | 'errors' | 'name'

const AGENT_COLORS: Record<string, string> = {
  master: 'text-purple-400',
  planning: 'text-blue-400',
  builder: 'text-green-400',
  keeper: 'text-yellow-400',
  cron: 'text-orange-400',
  doctor: 'text-red-400',
  model_manager: 'text-cyan-400',
  researcher: 'text-pink-400',
  librarian: 'text-emerald-400',
}

function agentColor(name: string): string {
  return AGENT_COLORS[name] ?? 'text-zinc-300'
}

function fmtCost(n: number): string {
  if (n >= 1) return `$${n.toFixed(2)}`
  if (n >= 0.01) return `$${n.toFixed(4)}`
  return `$${n.toFixed(6)}`
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

function fmtDuration(s: number | null): string {
  if (s == null) return '—'
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const r = Math.round(s - m * 60)
  return `${m}m${r}s`
}

function fmtTimestamp(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString()
}

function statusBadge(status: string, isAlive: boolean): { label: string; cls: string } {
  if (isAlive && status === 'running') return { label: 'running', cls: 'bg-green-900/40 text-green-400 border-green-700/40' }
  if (isAlive) return { label: 'alive', cls: 'bg-zinc-800 text-zinc-300 border-zinc-700' }
  if (status === 'error') return { label: 'error', cls: 'bg-red-900/40 text-red-400 border-red-700/40' }
  if (status === 'done') return { label: 'done', cls: 'bg-zinc-800 text-zinc-400 border-zinc-700' }
  return { label: status || 'idle', cls: 'bg-zinc-800 text-zinc-500 border-zinc-700' }
}

export function ObservabilityTab() {
  const [data, setData] = useState<ObservabilityDashboard | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('cost')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/metrics/observability')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const body = (await res.json()) as ObservabilityDashboard
      setData(body)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const agents = data?.agents ?? []
  const sorted = [...agents].sort((a, b) => {
    switch (sortKey) {
      case 'name':
        return a.name.localeCompare(b.name)
      case 'tokens':
        return b.input_tokens + b.output_tokens - (a.input_tokens + a.output_tokens)
      case 'tasks':
        return b.task_count - a.task_count
      case 'errors':
        return b.health_issues - a.health_issues
      case 'cost':
      default:
        return b.cost_usd - a.cost_usd
    }
  })

  function SortButton({ k, label }: { k: SortKey; label: string }) {
    const active = sortKey === k
    return (
      <button
        onClick={() => setSortKey(k)}
        className={[
          'px-1 py-0.5 text-[10px] font-mono uppercase tracking-wider',
          active ? 'text-[#FFB633]' : 'text-zinc-500 hover:text-zinc-300',
        ].join(' ')}
      >
        {label}
        {active && ' ▼'}
      </button>
    )
  }

  return (
    <div className="flex flex-col h-full bg-zinc-950 text-zinc-100 overflow-hidden">
      <div className="flex items-center gap-3 px-4 py-2 border-b border-zinc-800 flex-shrink-0">
        <h2 className="text-[10px] uppercase tracking-widest text-zinc-500">Observability</h2>
        <button
          onClick={load}
          disabled={loading}
          className="px-2 py-1 text-[11px] font-mono uppercase tracking-wider border border-zinc-700 text-zinc-300 hover:text-[#FFB633] hover:border-[#FFB633] disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
        {data && (
          <span className="text-[11px] text-zinc-500 font-mono ml-auto">
            generated {fmtTimestamp(data.generated_at)}
          </span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {error && (
          <div className="px-3 py-2 border border-red-700 bg-red-950/50 text-red-300 text-xs font-mono">
            {error}{' '}
            <button onClick={load} className="underline ml-2">retry</button>
          </div>
        )}

        {loading && !data && (
          <div className="text-zinc-500 text-xs font-mono animate-pulse">Loading…</div>
        )}

        {data && (
          <>
            {/* Totals strip */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
              <Stat label="Total spend" value={fmtCost(data.totals.total_cost_usd)} accent="text-[#FFB633]" />
              <Stat label="Tasks (lifetime)" value={String(data.totals.total_tasks)} />
              <Stat label="Active agents" value={String(data.totals.active_agents)} />
              <Stat
                label="Agents with errors"
                value={String(data.totals.agents_with_errors)}
                accent={data.totals.agents_with_errors > 0 ? 'text-red-400' : undefined}
              />
              <Stat label="Recent errors" value={String(data.totals.recent_error_count)} />
            </div>

            {/* Agent leaderboard */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <h3 className="text-[10px] uppercase tracking-widest text-zinc-500">
                  Agent leaderboard ({agents.length})
                </h3>
                <span className="text-zinc-700">·</span>
                <span className="text-[10px] text-zinc-500 font-mono">sort:</span>
                <SortButton k="cost" label="cost" />
                <SortButton k="tokens" label="tokens" />
                <SortButton k="tasks" label="tasks" />
                <SortButton k="errors" label="errors" />
                <SortButton k="name" label="name" />
              </div>

              <div className="border border-zinc-800 overflow-hidden">
                <table className="w-full text-xs font-mono">
                  <thead className="bg-zinc-900 text-zinc-500">
                    <tr className="text-left">
                      <th className="px-3 py-2 font-normal">Agent</th>
                      <th className="px-3 py-2 font-normal">Status</th>
                      <th className="px-3 py-2 font-normal text-right">Cost</th>
                      <th className="px-3 py-2 font-normal text-right">In</th>
                      <th className="px-3 py-2 font-normal text-right">Out</th>
                      <th className="px-3 py-2 font-normal text-right">Tasks</th>
                      <th className="px-3 py-2 font-normal text-right">Errors</th>
                      <th className="px-3 py-2 font-normal">Models</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map((a) => {
                      const badge = statusBadge(a.status, a.is_alive)
                      return (
                        <tr key={a.name} className="border-t border-zinc-800 hover:bg-zinc-900/60">
                          <td className={`px-3 py-2 ${agentColor(a.name)}`}>{a.name}</td>
                          <td className="px-3 py-2">
                            <span className={`inline-block px-1.5 py-0.5 text-[10px] border ${badge.cls}`}>
                              {badge.label}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-right text-zinc-200">{fmtCost(a.cost_usd)}</td>
                          <td className="px-3 py-2 text-right text-zinc-400">{fmtTokens(a.input_tokens)}</td>
                          <td className="px-3 py-2 text-right text-zinc-400">{fmtTokens(a.output_tokens)}</td>
                          <td className="px-3 py-2 text-right text-zinc-400">{a.task_count}</td>
                          <td className={`px-3 py-2 text-right ${a.health_issues > 0 ? 'text-red-400' : 'text-zinc-500'}`}>
                            {a.health_issues}
                          </td>
                          <td className="px-3 py-2 text-zinc-500 truncate max-w-[200px]" title={a.models.join(', ')}>
                            {a.models.length === 0 ? '—' : a.models.length === 1 ? a.models[0] : `${a.models[0]} +${a.models.length - 1}`}
                          </td>
                        </tr>
                      )
                    })}
                    {sorted.length === 0 && (
                      <tr>
                        <td colSpan={8} className="px-3 py-6 text-center text-zinc-500">
                          No agents found.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Recent errors + recent tasks side-by-side on wide screens */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div>
                <h3 className="text-[10px] uppercase tracking-widest text-zinc-500 mb-2">
                  Recent errors ({data.recent_errors.length})
                </h3>
                <div className="border border-zinc-800 bg-zinc-900/40 max-h-96 overflow-y-auto">
                  {data.recent_errors.length === 0 ? (
                    <div className="px-3 py-4 text-xs text-zinc-500 font-mono">No recent errors.</div>
                  ) : (
                    <ul className="divide-y divide-zinc-800">
                      {data.recent_errors.map((e, i) => (
                        <li key={`${e.agent}-${e.timestamp}-${i}`} className="px-3 py-2 text-xs font-mono">
                          <div className="flex items-center gap-2 mb-1 text-[10px]">
                            <span className={agentColor(e.agent)}>{e.agent}</span>
                            <span className={
                              e.level === 'ERROR' ? 'text-red-400' :
                              e.level === 'WARNING' ? 'text-yellow-400' :
                              'text-zinc-500'
                            }>{e.level}</span>
                            <span className="text-zinc-600 ml-auto">{e.timestamp}</span>
                          </div>
                          <div className="text-zinc-300 break-words">{e.message}</div>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>

              <div>
                <h3 className="text-[10px] uppercase tracking-widest text-zinc-500 mb-2">
                  Recent tasks ({data.recent_tasks.length})
                </h3>
                <div className="border border-zinc-800 bg-zinc-900/40 max-h-96 overflow-y-auto">
                  {data.recent_tasks.length === 0 ? (
                    <div className="px-3 py-4 text-xs text-zinc-500 font-mono">No tasks recorded yet.</div>
                  ) : (
                    <ul className="divide-y divide-zinc-800">
                      {data.recent_tasks.map((t, i) => (
                        <li key={`${t.task_id}-${i}`} className="px-3 py-2 text-xs font-mono">
                          <div className="flex items-center gap-2 mb-1 text-[10px]">
                            <span className={agentColor(t.agent)}>{t.agent}</span>
                            <span className="text-zinc-500">←</span>
                            <span className="text-zinc-400">{t.assigned_by || '—'}</span>
                            <span className={
                              t.status === 'done' ? 'text-green-400' :
                              t.status === 'error' ? 'text-red-400' :
                              t.status === 'timeout' ? 'text-yellow-400' :
                              'text-zinc-400'
                            }>{t.status}</span>
                            <span className="text-zinc-600 ml-auto">{fmtDuration(t.duration_s)}</span>
                          </div>
                          <div className="text-zinc-300 break-words line-clamp-2" title={t.task_summary}>
                            {t.task_summary || '(no summary)'}
                          </div>
                          {t.error_summary && (
                            <div className="text-red-400 mt-1 break-words line-clamp-2" title={t.error_summary}>
                              {t.error_summary}
                            </div>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="px-3 py-2 border border-zinc-800 bg-zinc-900/40">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-mono">{label}</div>
      <div className={`mt-1 text-lg font-mono ${accent ?? 'text-zinc-100'}`}>{value}</div>
    </div>
  )
}
