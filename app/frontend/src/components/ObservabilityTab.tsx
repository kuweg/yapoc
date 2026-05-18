import { useCallback, useEffect, useRef, useState } from 'react'

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

interface CostDataPoint {
  timestamp: string
  cost_usd: number
  agent: string
  model: string
  tokens_in: number
  tokens_out: number
}

interface CostHistoryResponse {
  points: CostDataPoint[]
  bucket: string
}

interface TraceEvent {
  agent: string
  content: string
  timestamp: string
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

const AGENT_CHART_COLORS: Record<string, string> = {
  master: '#a78bfa',
  planning: '#60a5fa',
  builder: '#4ade80',
  keeper: '#facc15',
  cron: '#fb923c',
  doctor: '#f87171',
  model_manager: '#22d3ee',
  researcher: '#f472b6',
  librarian: '#34d399',
}

function agentColor(name: string): string {
  return AGENT_COLORS[name] ?? 'text-zinc-300'
}

function chartColor(name: string): string {
  return AGENT_CHART_COLORS[name] ?? '#a1a1aa'
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

function shortTimestamp(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function statusBadge(status: string, isAlive: boolean): { label: string; cls: string } {
  if (isAlive && status === 'running') return { label: 'running', cls: 'bg-green-900/40 text-green-400 border-green-700/40' }
  if (isAlive) return { label: 'alive', cls: 'bg-zinc-800 text-zinc-300 border-zinc-700' }
  if (status === 'error') return { label: 'error', cls: 'bg-red-900/40 text-red-400 border-red-700/40' }
  if (status === 'done') return { label: 'done', cls: 'bg-zinc-800 text-zinc-400 border-zinc-700' }
  return { label: status || 'idle', cls: 'bg-zinc-800 text-zinc-500 border-zinc-700' }
}

// ── Cost chart component (pure SVG, no deps) ────────────────────────────────

function CostChart({ points }: { points: CostDataPoint[] }) {
  if (points.length === 0) {
    return (
      <div className="px-3 py-6 text-center text-zinc-500 text-xs font-mono">
        No cost data yet.
      </div>
    )
  }

  // Aggregate by timestamp across all agents
  const byTime = new Map<string, { total: number; agents: Map<string, number> }>()
  for (const p of points) {
    if (!byTime.has(p.timestamp)) {
      byTime.set(p.timestamp, { total: 0, agents: new Map() })
    }
    const bucket = byTime.get(p.timestamp)!
    bucket.total += p.cost_usd
    bucket.agents.set(p.agent, (bucket.agents.get(p.agent) || 0) + p.cost_usd)
  }

  const sortedTs = [...byTime.keys()].sort()
  const maxCost = Math.max(...sortedTs.map((ts) => byTime.get(ts)!.total), 0.001)

  const W = 600
  const H = 180
  const PAD = { top: 10, right: 10, bottom: 20, left: 50 }
  const chartW = W - PAD.left - PAD.right
  const chartH = H - PAD.top - PAD.bottom

  const allAgents = [...new Set(points.map((p) => p.agent))].sort()

  // Y-axis ticks
  const yTicks = 4
  const yStep = maxCost / yTicks

  // X-axis: show every Nth label
  const labelEvery = Math.max(1, Math.floor(sortedTs.length / 8))

  return (
    <div className="overflow-x-auto">
      <svg width={W} height={H} className="font-mono">
        {/* Y-axis gridlines + labels */}
        {Array.from({ length: yTicks + 1 }, (_, i) => {
          const val = yStep * i
          const y = PAD.top + chartH - (val / maxCost) * chartH
          return (
            <g key={i}>
              <line x1={PAD.left} y1={y} x2={W - PAD.right} y2={y} stroke="#27272a" strokeWidth={1} />
              <text x={PAD.left - 4} y={y + 3} textAnchor="end" fill="#71717a" fontSize={9}>
                {fmtCost(val)}
              </text>
            </g>
          )
        })}

        {/* Stacked bars */}
        {sortedTs.map((ts, ti) => {
          const bucket = byTime.get(ts)!
          const barW = Math.max(4, chartW / sortedTs.length - 1)
          const x = PAD.left + (ti / sortedTs.length) * chartW

          let stackedY = 0
          const segments: { agent: string; y: number; h: number }[] = []

          for (const agent of allAgents) {
            const val = bucket.agents.get(agent) || 0
            if (val === 0) continue
            const h = (val / maxCost) * chartH
            segments.push({ agent, y: PAD.top + chartH - stackedY - h, h })
            stackedY += h
          }

          return (
            <g key={ts}>
              {segments.map((seg) => (
                <rect
                  key={seg.agent}
                  x={x}
                  y={seg.y}
                  width={barW}
                  height={Math.max(1, seg.h)}
                  fill={chartColor(seg.agent)}
                  opacity={0.85}
                >
                  <title>{`${seg.agent}: ${fmtCost(bucket.agents.get(seg.agent)!)}`}</title>
                </rect>
              ))}
              {/* X-axis label */}
              {ti % labelEvery === 0 && (
                <text
                  x={x + barW / 2}
                  y={H - 4}
                  textAnchor="end"
                  fill="#71717a"
                  fontSize={8}
                  transform={`rotate(-45, ${x + barW / 2}, ${H - 4})`}
                >
                  {shortTimestamp(ts)}
                </text>
              )}
            </g>
          )
        })}
      </svg>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 mt-2 px-1">
        {allAgents.map((agent) => (
          <div key={agent} className="flex items-center gap-1.5 text-[10px] font-mono">
            <span
              className="inline-block w-2 h-2 rounded-sm"
              style={{ backgroundColor: chartColor(agent) }}
            />
            <span className={agentColor(agent)}>{agent}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Live trace viewer ───────────────────────────────────────────────────────

function LiveTraceViewer({ agent, onClose }: { agent: string; onClose: () => void }) {
  const [events, setEvents] = useState<TraceEvent[]>([])
  const [connected, setConnected] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    const es = new EventSource(`/api/metrics/trace-stream?agent=${agent}`)
    esRef.current = es

    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as TraceEvent
        setEvents((prev) => {
          const next = [...prev, data]
          // Keep last 100 events
          return next.length > 100 ? next.slice(-100) : next
        })
      } catch {
        // ignore parse errors
      }
    }

    return () => {
      es.close()
      esRef.current = null
    }
  }, [agent])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [events])

  return (
    <div className="border border-zinc-800 bg-zinc-900/60">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-800">
        <span className={`inline-block w-2 h-2 rounded-full ${connected ? 'bg-green-500' : 'bg-red-500'}`} />
        <span className="text-[10px] uppercase tracking-widest text-zinc-500 font-mono">
          Live trace: {agent}
        </span>
        <span className="text-[10px] text-zinc-600 font-mono">
          {events.length} events
        </span>
        <button
          onClick={onClose}
          className="ml-auto px-2 py-0.5 text-[10px] font-mono border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500"
        >
          Close
        </button>
      </div>

      {/* Event feed */}
      <div ref={scrollRef} className="max-h-80 overflow-y-auto p-2 space-y-1">
        {events.length === 0 && (
          <div className="text-zinc-500 text-[10px] font-mono text-center py-4">
            {connected ? 'Waiting for activity...' : 'Connecting...'}
          </div>
        )}
        {events.map((ev, i) => (
          <div key={i} className="text-[10px] font-mono">
            <span className="text-zinc-600">{shortTimestamp(ev.timestamp)}</span>{' '}
            <span className={agentColor(ev.agent)}>[{ev.agent}]</span>{' '}
            <span className="text-zinc-300 whitespace-pre-wrap line-clamp-3">
              {ev.content || '(empty)'}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Agent detail panel ──────────────────────────────────────────────────────

function AgentDetailPanel({
  agent,
  onClose,
}: {
  agent: ObservabilityAgent
  onClose: () => void
}) {
  const [traceOpen, setTraceOpen] = useState(false)
  const badge = statusBadge(agent.status, agent.is_alive)

  return (
    <div className="border border-zinc-800 bg-zinc-900/60">
      {/* Header */}
      <div className="flex items-center gap-3 px-3 py-2 border-b border-zinc-800">
        <span className={`text-sm font-mono font-bold ${agentColor(agent.name)}`}>
          {agent.name}
        </span>
        <span className={`inline-block px-1.5 py-0.5 text-[10px] border ${badge.cls}`}>
          {badge.label}
        </span>
        <button
          onClick={onClose}
          className="ml-auto px-2 py-0.5 text-[10px] font-mono border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500"
        >
          Close
        </button>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-zinc-800">
        <DetailStat label="Cost" value={fmtCost(agent.cost_usd)} accent="text-[#FFB633]" />
        <DetailStat label="Input tokens" value={fmtTokens(agent.input_tokens)} />
        <DetailStat label="Output tokens" value={fmtTokens(agent.output_tokens)} />
        <DetailStat label="Tasks" value={String(agent.task_count)} />
        <DetailStat label="Health issues" value={String(agent.health_issues)} accent={agent.health_issues > 0 ? 'text-red-400' : undefined} />
        <DetailStat label="Last active" value={agent.last_active_at ? fmtTimestamp(agent.last_active_at) : '—'} />
        <DetailStat label="Models" value={agent.models.join(', ') || '—'} />
        <DetailStat label="Alive" value={agent.is_alive ? 'Yes' : 'No'} accent={agent.is_alive ? 'text-green-400' : 'text-red-400'} />
      </div>

      {/* Live trace toggle */}
      <div className="px-3 py-2">
        <button
          onClick={() => setTraceOpen(!traceOpen)}
          className="px-3 py-1 text-[10px] font-mono uppercase tracking-wider border border-zinc-700 text-zinc-300 hover:text-[#FFB633] hover:border-[#FFB633]"
        >
          {traceOpen ? 'Hide live trace' : 'Show live trace'}
        </button>
      </div>

      {traceOpen && (
        <div className="px-3 pb-3">
          <LiveTraceViewer agent={agent.name} onClose={() => setTraceOpen(false)} />
        </div>
      )}
    </div>
  )
}

function DetailStat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="px-3 py-2 bg-zinc-900/60">
      <div className="text-[9px] uppercase tracking-wider text-zinc-500 font-mono">{label}</div>
      <div className={`mt-0.5 text-xs font-mono truncate ${accent ?? 'text-zinc-200'}`}>{value}</div>
    </div>
  )
}

// ── Main component ──────────────────────────────────────────────────────────

export function ObservabilityTab() {
  const [data, setData] = useState<ObservabilityDashboard | null>(null)
  const [costHistory, setCostHistory] = useState<CostDataPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [costLoading, setCostLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('cost')
  const [selectedAgent, setSelectedAgent] = useState<ObservabilityAgent | null>(null)
  const [showCostChart, setShowCostChart] = useState(true)
  const [showLiveTrace, setShowLiveTrace] = useState(false)
  const [traceAgent, setTraceAgent] = useState<string>('')

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

  const loadCostHistory = useCallback(async () => {
    setCostLoading(true)
    try {
      const res = await fetch('/api/metrics/cost-history?bucket=hour&hours=72')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const body = (await res.json()) as CostHistoryResponse
      setCostHistory(body.points)
    } catch {
      // silent fail for cost chart
    } finally {
      setCostLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    loadCostHistory()
  }, [load, loadCostHistory])

  // Auto-refresh every 15 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      load()
    }, 15000)
    return () => clearInterval(interval)
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
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-zinc-800 flex-shrink-0">
        <h2 className="text-[10px] uppercase tracking-widest text-zinc-500">Observability</h2>
        <button
          onClick={() => { load(); loadCostHistory(); }}
          disabled={loading}
          className="px-2 py-1 text-[11px] font-mono uppercase tracking-wider border border-zinc-700 text-zinc-300 hover:text-[#FFB633] hover:border-[#FFB633] disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
        <button
          onClick={() => setShowCostChart(!showCostChart)}
          className={`px-2 py-1 text-[11px] font-mono uppercase tracking-wider border ${
            showCostChart ? 'border-[#FFB633] text-[#FFB633]' : 'border-zinc-700 text-zinc-400'
          } hover:border-[#FFB633] hover:text-[#FFB633]`}
        >
          {showCostChart ? 'Hide chart' : 'Cost chart'}
        </button>
        <button
          onClick={() => setShowLiveTrace(!showLiveTrace)}
          className={`px-2 py-1 text-[11px] font-mono uppercase tracking-wider border ${
            showLiveTrace ? 'border-[#FFB633] text-[#FFB633]' : 'border-zinc-700 text-zinc-400'
          } hover:border-[#FFB633] hover:text-[#FFB633]`}
        >
          {showLiveTrace ? 'Hide trace' : 'Live trace'}
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

            {/* Cost chart */}
            {showCostChart && (
              <div>
                <h3 className="text-[10px] uppercase tracking-widest text-zinc-500 mb-2">
                  Cost over time (72h)
                  {costLoading && <span className="text-zinc-600 ml-2 animate-pulse">loading…</span>}
                </h3>
                <div className="border border-zinc-800 bg-zinc-900/40 p-3">
                  <CostChart points={costHistory} />
                </div>
              </div>
            )}

            {/* Live trace */}
            {showLiveTrace && (
              <div>
                <h3 className="text-[10px] uppercase tracking-widest text-zinc-500 mb-2">
                  Live agent trace
                </h3>
                <div className="flex items-center gap-2 mb-2">
                  <select
                    value={traceAgent}
                    onChange={(e) => setTraceAgent(e.target.value)}
                    className="bg-zinc-900 border border-zinc-700 text-zinc-200 text-[11px] font-mono px-2 py-1"
                  >
                    <option value="">All agents</option>
                    {agents.map((a) => (
                      <option key={a.name} value={a.name}>{a.name}</option>
                    ))}
                  </select>
                </div>
                <LiveTraceViewer
                  agent={traceAgent}
                  onClose={() => setShowLiveTrace(false)}
                />
              </div>
            )}

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
                      const isSelected = selectedAgent?.name === a.name
                      return (
                        <tr
                          key={a.name}
                          className={`border-t border-zinc-800 cursor-pointer ${
                            isSelected ? 'bg-zinc-800/60' : 'hover:bg-zinc-900/60'
                          }`}
                          onClick={() => setSelectedAgent(isSelected ? null : a)}
                        >
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

            {/* Agent detail panel */}
            {selectedAgent && (
              <AgentDetailPanel
                agent={selectedAgent}
                onClose={() => setSelectedAgent(null)}
              />
            )}

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
