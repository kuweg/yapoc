import { useEffect, useState, useCallback } from 'react'

interface StaleTask {
  agent: string
  status: string
  assigned_at: string
  elapsed_seconds: number
  threshold_seconds: number
}

interface StaleTasksResponse {
  stale_tasks: StaleTask[]
  threshold_seconds: number
}

const POLL_INTERVAL = 30_000 // 30 seconds

export function StaleTasksPanel() {
  const [data, setData] = useState<StaleTasksResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  const fetchStaleTasks = useCallback(async () => {
    try {
      const res = await fetch('/api/stale-tasks')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json: StaleTasksResponse = await res.json()
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
    fetchStaleTasks()
    const interval = setInterval(fetchStaleTasks, POLL_INTERVAL)
    return () => clearInterval(interval)
  }, [fetchStaleTasks])

  const formatElapsed = (seconds: number): string => {
    const h = Math.floor(seconds / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    const s = Math.floor(seconds % 60)
    if (h > 0) return `${h}h ${m}m`
    if (m > 0) return `${m}m ${s}s`
    return `${s}s`
  }

  const tasks = data?.stale_tasks ?? []
  const threshold = data?.threshold_seconds ?? 600
  const hasStale = tasks.length > 0

  return (
    <div className="rounded-lg border border-[#30363D] bg-[#161B22] overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-[#30363D]">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${hasStale ? 'bg-[#F85149] animate-pulse' : 'bg-[#3FB950]'}`} />
          <span className="text-xs font-semibold text-[#E6EDF3] tracking-wide uppercase">
            Stale Tasks
          </span>
          {hasStale && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-[#F8514920] text-[#F85149]">
              {tasks.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-[#8B949E]">
            threshold: {formatElapsed(threshold)}
          </span>
          {lastUpdated && (
            <span className="text-[10px] text-[#484F58]">
              &middot; {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={fetchStaleTasks}
            disabled={loading}
            className="text-[10px] text-[#8B949E] hover:text-[#E6EDF3] transition-colors disabled:opacity-40"
            title="Refresh now"
          >
            &#8635;
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="px-4 py-3">
        {loading && !data && (
          <div className="text-xs text-[#8B949E] py-2">Scanning agents&hellip;</div>
        )}

        {error && (
          <div className="text-xs text-[#F85149] py-2">
            Error: {error}
          </div>
        )}

        {!loading && !error && tasks.length === 0 && (
          <div className="flex items-center gap-2 text-xs text-[#3FB950] py-1">
            <span>&#10003;</span>
            <span>No stale tasks detected</span>
          </div>
        )}

        {tasks.length > 0 && (
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[#21262D] text-[#8B949E]">
                <th className="text-left py-1.5 pr-3 font-medium">Agent</th>
                <th className="text-left py-1.5 pr-3 font-medium">Elapsed</th>
                <th className="text-left py-1.5 pr-3 font-medium">Assigned At</th>
                <th className="text-left py-1.5 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => (
                <tr key={t.agent} className="border-b border-[#21262D] last:border-0">
                  <td className="py-1.5 pr-3 text-[#E6EDF3] font-mono">{t.agent}</td>
                  <td className="py-1.5 pr-3">
                    <span className={`font-mono ${t.elapsed_seconds > threshold * 2 ? 'text-[#F85149]' : 'text-[#D29922]'}`}>
                      {formatElapsed(t.elapsed_seconds)}
                    </span>
                  </td>
                  <td className="py-1.5 pr-3 text-[#8B949E] font-mono text-[10px]">
                    {t.assigned_at ? new Date(t.assigned_at).toLocaleString() : '\u2014'}
                  </td>
                  <td className="py-1.5">
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[#D2992220] text-[#D29922]">
                      {t.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-1.5 border-t border-[#21262D] text-[10px] text-[#484F58]">
        Polls every 30s &middot; Threshold from agent-settings.json
      </div>
    </div>
  )
}
