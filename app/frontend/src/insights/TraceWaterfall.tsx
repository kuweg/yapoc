/**
 * Trace Waterfall — where the time went.
 *
 * The Observability tab shows aggregate counters; nothing ever showed the shape
 * of a run. This lays task records on a time axis: one bar per task, positioned
 * by assignment time, width by duration. Records are split into runs on idle
 * gaps — the log is sparse, and a single global axis squashes a busy minute
 * into one pixel when the window spans months. Errors carry a red cap so a
 * failed branch is visible without reading a single row.
 */
import { useMemo, useState } from 'react'
import { agentColor, formatDuration, getObservability, relativeTime } from './api'
import { Panel, Stat, ViewState, usePolled } from './shared'
import type { ObsTask } from './types'

interface Bar {
  task: ObsTask
  startMs: number
  durMs: number
}

/** Tasks separated by more than this are treated as separate runs. */
const RUN_GAP_MS = 30 * 60_000

interface Run {
  startMs: number
  spanMs: number
  bars: Bar[]
}

function makeRun(bars: Bar[]): Run {
  const start = Math.min(...bars.map((b) => b.startMs))
  const end = Math.max(...bars.map((b) => b.startMs + b.durMs))
  return { startMs: start, spanMs: Math.max(end - start, 1), bars }
}

function statusTone(status: string): string {
  const s = status.toLowerCase()
  if (s === 'error' || s === 'failed') return 'var(--color-error)'
  if (s === 'done' || s === 'completed') return 'var(--color-success)'
  if (s === 'running') return 'var(--color-accent)'
  return 'var(--color-text-muted)'
}

export function TraceWaterfall() {
  const obs = usePolled(getObservability, 15_000)
  const [selected, setSelected] = useState<ObsTask | null>(null)

  const { bars, runs, parents } = useMemo(() => {
    const tasks = obs.data?.recent_tasks ?? []
    const parsed: Bar[] = []
    for (const t of tasks) {
      const start = Date.parse(t.assigned_at)
      if (Number.isNaN(start)) continue
      const end = Date.parse(t.completed_at)
      const durMs =
        t.duration_s != null && t.duration_s > 0
          ? t.duration_s * 1000
          : !Number.isNaN(end) && end > start
            ? end - start
            : 0
      parsed.push({ task: t, startMs: start, durMs })
    }
    if (parsed.length === 0) return { bars: [], runs: [] as Run[], parents: [] as string[] }

    parsed.sort((a, b) => a.startMs - b.startMs)

    // The task log is sparse and clustered — 20 records can span months, which
    // squashes every bar to an invisible sliver on one global axis. So split on
    // idle gaps and give each run its own local axis; a run stays legible no
    // matter how long ago it happened.
    const built: Run[] = []
    let current: Bar[] = []
    for (const b of parsed) {
      if (current.length === 0) { current = [b]; continue }
      const prevEnd = Math.max(...current.map((x) => x.startMs + x.durMs))
      if (b.startMs - prevEnd > RUN_GAP_MS) {
        built.push(makeRun(current))
        current = [b]
      } else {
        current.push(b)
      }
    }
    if (current.length > 0) built.push(makeRun(current))
    built.reverse() // newest run first

    return {
      bars: parsed,
      runs: built,
      parents: [...new Set(parsed.map((b) => b.task.assigned_by || 'unknown'))].sort(),
    }
  }, [obs.data])

  const slowest = bars.reduce<Bar | null>((acc, b) => (!acc || b.durMs > acc.durMs ? b : acc), null)
  const errored = bars.filter((b) => b.task.status?.toLowerCase() === 'error').length

  return (
    <div className="flex flex-col gap-3 h-full min-h-0">
      <div className="flex flex-wrap gap-8 px-4 py-3 rounded border flex-shrink-0" style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-panel)' }}>
        <Stat label="Tasks traced" value={String(bars.length)} />
        <Stat label="Runs" value={String(runs.length)} />
        <Stat label="Delegating agents" value={String(parents.length)} />
        <Stat label="Slowest" value={slowest ? formatDuration(slowest.durMs / 1000) : '—'} tone={slowest && slowest.durMs > 120_000 ? 'var(--color-warning)' : undefined} />
        <Stat label="Errored" value={String(errored)} tone={errored > 0 ? 'var(--color-error)' : undefined} />
      </div>

      <Panel
        title="Task waterfall"
        subtitle={runs.length > 0 ? `${runs.length} run${runs.length === 1 ? '' : 's'} · each on its own time axis` : undefined}
        className="flex-1 min-h-0"
      >
        <ViewState
          loading={obs.loading && !obs.data}
          error={obs.error}
          empty={bars.length === 0}
          emptyLabel="No task records in the recent window — run a task and it will appear here."
          onRetry={obs.refresh}
        />
        {runs.length > 0 && (
          <div className="overflow-auto h-full px-3 py-2">
            {runs.map((run, ri) => (
              <div key={`run-${ri}-${run.startMs}`} className="mb-4">
                <div className="flex items-center gap-2 mb-1.5 sticky top-0 z-10 py-1" style={{ background: 'var(--color-bg-panel)' }}>
                  <span className="text-[12px] font-mono uppercase tracking-[0.1em]" style={{ color: 'var(--color-text-secondary)' }}>
                    {relativeTime(new Date(run.startMs).toISOString())}
                  </span>
                  <span className="text-[12px] font-mono" style={{ color: 'var(--color-text-muted)' }}>
                    {new Date(run.startMs).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                    {' · '}{run.bars.length} task{run.bars.length === 1 ? '' : 's'}
                    {' · '}{formatDuration(run.spanMs / 1000)}
                  </span>
                </div>
                {run.bars.map((b, bi) => {
                  const leftPct = ((b.startMs - run.startMs) / run.spanMs) * 100
                  const widthPct = Math.max((b.durMs / run.spanMs) * 100, 1.5)
                  const isSel = selected?.task_id === b.task.task_id
                  return (
                    <button
                      key={`bar-${ri}-${bi}-${b.task.task_id}`}
                      onClick={() => setSelected(isSel ? null : b.task)}
                      aria-pressed={isSel}
                      className="w-full grid items-center gap-2 py-0.5 rounded hover:bg-white/5 focus:outline-none focus:ring-1"
                      style={{ gridTemplateColumns: '96px 1fr 58px' }}
                      title={`${b.task.agent} · ${b.task.status} · ${formatDuration(b.durMs / 1000)}\n${b.task.task_summary || ''}`}
                    >
                      <span className="text-[12px] font-mono truncate text-left" style={{ color: 'var(--color-text-secondary)' }}>
                        {b.task.agent}
                      </span>
                      <span className="relative h-3 rounded-sm" style={{ background: 'var(--color-bg-tertiary)' }}>
                        <span
                          className="absolute top-0 h-full rounded-sm"
                          style={{
                            left: `${leftPct}%`,
                            width: `${widthPct}%`,
                            background: agentColor(b.task.agent),
                            opacity: isSel ? 1 : 0.8,
                            boxShadow: isSel ? '0 0 0 1px var(--color-text-primary)' : undefined,
                          }}
                        />
                        {b.task.status?.toLowerCase() === 'error' && (
                          <span
                            className="absolute top-0 h-full w-[2px]"
                            style={{ left: `calc(${leftPct}% + ${widthPct}%)`, background: 'var(--color-error)' }}
                          />
                        )}
                      </span>
                      <span className="text-[12px] font-mono tabular-nums text-right" style={{ color: statusTone(b.task.status) }}>
                        {formatDuration(b.durMs / 1000)}
                      </span>
                    </button>
                  )
                })}
              </div>
            ))}
          </div>
        )}
      </Panel>

      {selected && (
        <div className="rounded border px-4 py-3 flex-shrink-0" style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-panel)' }}>
          <div className="flex items-center gap-3 mb-1.5">
            <span className="text-[13px] font-mono" style={{ color: 'var(--color-text-primary)' }}>{selected.agent}</span>
            <span className="text-[12px] font-mono px-1.5 py-0.5 rounded" style={{ color: statusTone(selected.status), border: `1px solid ${statusTone(selected.status)}` }}>
              {selected.status}
            </span>
            <span className="text-[12px] font-mono" style={{ color: 'var(--color-text-muted)' }}>
              assigned by {selected.assigned_by} · {relativeTime(selected.assigned_at)}
            </span>
            <button onClick={() => setSelected(null)} className="ml-auto text-[12px] font-mono" style={{ color: 'var(--color-text-muted)' }} aria-label="Close task detail">
              close
            </button>
          </div>
          {selected.task_summary && (
            <p className="text-[13px] font-mono leading-relaxed whitespace-pre-wrap" style={{ color: 'var(--color-text-secondary)' }}>
              {selected.task_summary}
            </p>
          )}
          {selected.error_summary && (
            <p className="text-[13px] font-mono leading-relaxed whitespace-pre-wrap mt-1.5" style={{ color: 'var(--color-error)' }}>
              {selected.error_summary}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
