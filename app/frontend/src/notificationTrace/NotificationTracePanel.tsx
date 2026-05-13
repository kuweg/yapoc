import { useCallback, useEffect, useMemo, useState } from 'react'

type TraceEvent = {
  ts: string
  event: 'enqueued' | 'deduped' | 'drained'
  parent_agent?: string
  child_agent?: string
  status?: string
  session_id?: string
  reason?: string
  result_preview?: string
  error_preview?: string
  completed_at?: string
}

interface TraceResponse {
  events: TraceEvent[]
  count: number
}

const POLL_INTERVAL = 5_000
const LIMIT = 200

const EVENT_STYLES: Record<TraceEvent['event'], { dot: string; pill: string; label: string }> = {
  enqueued: { dot: 'bg-[#3FB950]', pill: 'bg-[#3FB95020] text-[#3FB950]', label: 'enqueued' },
  deduped: { dot: 'bg-[#D29922]', pill: 'bg-[#D2992220] text-[#D29922]', label: 'deduped' },
  drained: { dot: 'bg-[#58A6FF]', pill: 'bg-[#58A6FF20] text-[#58A6FF]', label: 'drained' },
}

type Filter = 'all' | TraceEvent['event']

export function NotificationTracePanel() {
  const [data, setData] = useState<TraceResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [filter, setFilter] = useState<Filter>('all')

  const fetchTrace = useCallback(async () => {
    try {
      const res = await fetch(`/api/notifications/trace?limit=${LIMIT}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json: TraceResponse = await res.json()
      setData(json)
      setLastUpdated(new Date())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchTrace()
    const interval = setInterval(fetchTrace, POLL_INTERVAL)
    return () => clearInterval(interval)
  }, [fetchTrace])

  const events = data?.events ?? []
  const filtered = useMemo(
    () => (filter === 'all' ? events : events.filter((e) => e.event === filter)),
    [events, filter],
  )

  const counts = useMemo(() => {
    const c = { enqueued: 0, deduped: 0, drained: 0 }
    for (const e of events) {
      if (e.event in c) c[e.event] += 1
    }
    return c
  }, [events])

  const formatTime = (iso: string): string => {
    try {
      return new Date(iso).toLocaleTimeString()
    } catch {
      return iso
    }
  }

  return (
    <div className="rounded-lg border border-[#30363D] bg-[#161B22] overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-[#30363D]">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-[#58A6FF] flex-shrink-0" />
          <span className="text-xs font-semibold text-[#E6EDF3] tracking-wide uppercase">
            Notification Trace
          </span>
          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-[#21262D] text-[#8B949E]">
            {events.length}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {lastUpdated && (
            <span className="text-[10px] text-[#484F58]">{lastUpdated.toLocaleTimeString()}</span>
          )}
          <button
            onClick={fetchTrace}
            disabled={loading}
            className="text-[10px] text-[#8B949E] hover:text-[#E6EDF3] transition-colors disabled:opacity-40"
            title="Refresh now"
          >
            &#8635;
          </button>
        </div>
      </div>

      {/* Filter chips */}
      <div className="flex items-center gap-1.5 px-4 py-2 border-b border-[#21262D]">
        {(['all', 'enqueued', 'deduped', 'drained'] as Filter[]).map((f) => {
          const active = filter === f
          const count = f === 'all' ? events.length : counts[f as keyof typeof counts]
          const styles = f === 'all' ? null : EVENT_STYLES[f as TraceEvent['event']]
          return (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                active
                  ? styles?.pill ?? 'bg-[#21262D] text-[#E6EDF3]'
                  : 'text-[#8B949E] hover:text-[#E6EDF3]'
              }`}
            >
              {f} {count > 0 && <span className="opacity-70">({count})</span>}
            </button>
          )
        })}
      </div>

      {/* Body */}
      <div className="px-4 py-3 max-h-80 overflow-y-auto">
        {loading && !data && (
          <div className="text-xs text-[#8B949E] py-2">Loading trace&hellip;</div>
        )}

        {error && <div className="text-xs text-[#F85149] py-2">Error: {error}</div>}

        {!loading && !error && filtered.length === 0 && (
          <div className="text-xs text-[#8B949E] py-2">
            {events.length === 0 ? 'No notification events yet.' : 'No events match this filter.'}
          </div>
        )}

        {filtered.length > 0 && (
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[#21262D] text-[#8B949E]">
                <th className="text-left py-1.5 pr-3 font-medium">Time</th>
                <th className="text-left py-1.5 pr-3 font-medium">Event</th>
                <th className="text-left py-1.5 pr-3 font-medium">Parent &larr; Child</th>
                <th className="text-left py-1.5 pr-3 font-medium">Status</th>
                <th className="text-left py-1.5 font-medium">Detail</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((e, idx) => {
                const styles = EVENT_STYLES[e.event]
                const detail =
                  e.event === 'deduped'
                    ? e.reason ?? ''
                    : e.event === 'enqueued'
                    ? e.result_preview || e.error_preview || ''
                    : e.completed_at ?? ''
                return (
                  <tr key={`${e.ts}-${idx}`} className="border-b border-[#21262D] last:border-0">
                    <td className="py-1.5 pr-3 font-mono text-[10px] text-[#8B949E] whitespace-nowrap">
                      {formatTime(e.ts)}
                    </td>
                    <td className="py-1.5 pr-3">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${styles.pill}`}>
                        {styles.label}
                      </span>
                    </td>
                    <td className="py-1.5 pr-3 font-mono text-[#E6EDF3] whitespace-nowrap">
                      {e.parent_agent ?? '?'} <span className="text-[#484F58]">&larr;</span>{' '}
                      {e.child_agent ?? '?'}
                    </td>
                    <td className="py-1.5 pr-3 text-[#8B949E]">{e.status ?? ''}</td>
                    <td className="py-1.5 text-[#8B949E] truncate max-w-[260px]" title={detail}>
                      {detail}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="px-4 py-1.5 border-t border-[#21262D] text-[10px] text-[#484F58]">
        Polls every 5s &middot; Newest first &middot; Source: data/notification_trace.jsonl
      </div>
    </div>
  )
}
