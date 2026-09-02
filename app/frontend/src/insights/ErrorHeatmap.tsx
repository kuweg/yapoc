/**
 * Cross-Agent Error Heatmap.
 *
 * Doctor already computes cross-agent failure patterns — it reports things like
 * `CROSS_AGENT_PATTERN: 3 agents share error "Task timed out after 300s"` — but
 * that only ever surfaced as a sentence in a sidebar card. This makes it a
 * picture: agents down the side, hourly buckets across, intensity by error
 * count, plus the shared signatures called out underneath.
 */
import { useMemo, useState } from 'react'
import { getObservability, relativeTime } from './api'
import { Panel, Stat, ViewState, usePolled } from './shared'
import type { ObsError } from './types'

const HOURS = 24

// Collapse an error message to a signature so the same failure reported by
// different agents (with different ids, paths and timings) groups together.
function signature(message: string): string {
  return message
    .replace(/\d+/g, 'N')
    .replace(/['"`][^'"`]{0,80}['"`]/g, 'X')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 90)
}

function cellColor(count: number, max: number): string {
  if (count === 0) return 'var(--color-bg-tertiary)'
  const t = max <= 1 ? 1 : count / max
  // Warm ramp from the theme's warning amber to its error red.
  const alpha = 0.22 + t * 0.78
  return `color-mix(in srgb, var(--color-error) ${Math.round(alpha * 100)}%, var(--color-warning))`
}

export function ErrorHeatmap() {
  const obs = usePolled(getObservability, 15_000)
  const [selected, setSelected] = useState<{ agent: string; hour: number } | null>(null)

  const { agents, grid, max, buckets, signatures, errors } = useMemo(() => {
    const errs: ObsError[] = obs.data?.recent_errors ?? []
    const now = Date.now()
    const hourMs = 3_600_000
    // Bucket 0 is the oldest hour in the window, HOURS-1 is the current hour.
    const bucketStart = (i: number) => now - (HOURS - 1 - i) * hourMs

    const byAgent = new Map<string, number[]>()
    for (const e of errs) {
      const t = Date.parse(e.timestamp)
      if (Number.isNaN(t)) continue
      const idx = HOURS - 1 - Math.floor((now - t) / hourMs)
      if (idx < 0 || idx >= HOURS) continue
      let row = byAgent.get(e.agent)
      if (!row) { row = new Array(HOURS).fill(0); byAgent.set(e.agent, row) }
      row[idx] += 1
    }

    // Agents that reported health issues but no timestamped error still deserve a row.
    for (const a of obs.data?.agents ?? []) {
      if (a.health_issues > 0 && !byAgent.has(a.name)) byAgent.set(a.name, new Array(HOURS).fill(0))
    }

    const names = [...byAgent.keys()].sort((a, b) => {
      const sum = (n: string) => (byAgent.get(n) ?? []).reduce((s, v) => s + v, 0)
      return sum(b) - sum(a) || a.localeCompare(b)
    })

    let m = 0
    for (const row of byAgent.values()) for (const v of row) if (v > m) m = v

    // Shared signatures — the same failure seen by more than one agent.
    const sigMap = new Map<string, { sig: string; agents: Set<string>; count: number; sample: string; last: string }>()
    for (const e of errs) {
      const sig = signature(e.message)
      const hit = sigMap.get(sig)
      if (hit) {
        hit.agents.add(e.agent)
        hit.count += 1
        if (e.timestamp > hit.last) hit.last = e.timestamp
      } else {
        sigMap.set(sig, { sig, agents: new Set([e.agent]), count: 1, sample: e.message, last: e.timestamp })
      }
    }
    const shared = [...sigMap.values()]
      .filter((s) => s.agents.size > 1)
      .sort((a, b) => b.agents.size - a.agents.size || b.count - a.count)

    return {
      agents: names,
      grid: byAgent,
      max: m,
      buckets: Array.from({ length: HOURS }, (_, i) => bucketStart(i)),
      signatures: shared,
      errors: errs,
    }
  }, [obs.data])

  const cellErrors = useMemo(() => {
    if (!selected) return []
    const hourMs = 3_600_000
    const start = buckets[selected.hour]
    return errors.filter((e) => {
      if (e.agent !== selected.agent) return false
      const t = Date.parse(e.timestamp)
      return t >= start && t < start + hourMs
    })
  }, [selected, buckets, errors])

  const totalErrors = errors.length

  return (
    <div className="flex flex-col gap-3 h-full min-h-0 overflow-auto">
      <div className="flex flex-wrap gap-8 px-4 py-3 rounded border flex-shrink-0" style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-panel)' }}>
        <Stat label="Errors (24h)" value={String(totalErrors)} tone={totalErrors > 0 ? 'var(--color-error)' : 'var(--color-success)'} />
        <Stat label="Agents affected" value={String(agents.length)} />
        <Stat label="Shared patterns" value={String(signatures.length)} tone={signatures.length > 0 ? 'var(--color-warning)' : undefined} />
        <Stat label="Peak hour" value={max > 0 ? `${max} err` : '—'} />
      </div>

      <Panel title="Error heatmap" subtitle="last 24 hours · click a cell for detail" className="flex-shrink-0">
        <ViewState
          loading={obs.loading && !obs.data}
          error={obs.error}
          empty={agents.length === 0}
          emptyLabel="No errors recorded in the last 24 hours."
          onRetry={obs.refresh}
        />
        {agents.length > 0 && (
          <div className="overflow-x-auto px-3 py-3">
            <div className="inline-block min-w-full">
              {agents.map((name) => {
                const row = grid.get(name) ?? []
                const rowTotal = row.reduce((s, v) => s + v, 0)
                return (
                  <div key={name} className="flex items-center gap-2 mb-1">
                    <span className="w-24 flex-shrink-0 text-[12px] font-mono truncate text-right" style={{ color: 'var(--color-text-secondary)' }} title={name}>
                      {name}
                    </span>
                    <div className="flex gap-[2px]">
                      {row.map((count, h) => {
                        const isSel = selected?.agent === name && selected?.hour === h
                        return (
                          <button
                            key={h}
                            onClick={() => setSelected(count > 0 ? (isSel ? null : { agent: name, hour: h }) : null)}
                            disabled={count === 0}
                            aria-label={`${name}, ${new Date(buckets[h]).toLocaleString([], { hour: '2-digit' })}: ${count} errors`}
                            title={`${name} · ${new Date(buckets[h]).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit' })} · ${count} error${count === 1 ? '' : 's'}`}
                            className="w-3 h-3 rounded-[2px] transition-transform focus:outline-none"
                            style={{
                              background: cellColor(count, max),
                              cursor: count > 0 ? 'pointer' : 'default',
                              outline: isSel ? '1px solid var(--color-text-primary)' : undefined,
                              outlineOffset: '1px',
                            }}
                          />
                        )
                      })}
                    </div>
                    <span className="text-[12px] font-mono tabular-nums w-8" style={{ color: rowTotal > 0 ? 'var(--color-error)' : 'var(--color-text-muted)' }}>
                      {rowTotal || ''}
                    </span>
                  </div>
                )
              })}
              <div className="flex items-center gap-2 mt-2">
                <span className="w-24 flex-shrink-0" />
                <div className="flex gap-[2px] text-[12px] font-mono" style={{ color: 'var(--color-text-muted)' }}>
                  {buckets.map((b, i) => (
                    <span key={i} className="w-3 text-center">
                      {i % 6 === 0 ? new Date(b).getHours() : ''}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </Panel>

      {selected && cellErrors.length > 0 && (
        <Panel title={`${selected.agent} · ${new Date(buckets[selected.hour]).toLocaleString([], { hour: '2-digit' })}:00`} className="flex-shrink-0">
          <div className="px-4 py-3 flex flex-col gap-2 max-h-56 overflow-auto">
            {cellErrors.map((e, i) => (
              <div key={i} className="text-[13px] font-mono leading-relaxed">
                <span style={{ color: 'var(--color-text-muted)' }}>{new Date(e.timestamp).toLocaleTimeString()} </span>
                <span style={{ color: 'var(--color-error)' }}>{e.level} </span>
                <span style={{ color: 'var(--color-text-secondary)' }}>{e.message}</span>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {signatures.length > 0 && (
        <Panel title="Shared failure signatures" subtitle="same error, more than one agent" className="flex-shrink-0">
          <div className="flex flex-col">
            {signatures.slice(0, 8).map((s) => (
              <div key={s.sig} className="px-4 py-2.5 border-t first:border-t-0" style={{ borderColor: 'var(--color-border-muted)' }}>
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <span className="text-[12px] font-mono px-1.5 py-0.5 rounded" style={{ color: 'var(--color-warning)', border: '1px solid var(--color-warning)' }}>
                    {s.agents.size} agents
                  </span>
                  <span className="text-[12px] font-mono" style={{ color: 'var(--color-text-muted)' }}>
                    {[...s.agents].join(', ')} · {s.count} occurrences · {relativeTime(s.last)}
                  </span>
                </div>
                <p className="text-[13px] font-mono leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>{s.sample}</p>
              </div>
            ))}
          </div>
        </Panel>
      )}
    </div>
  )
}
