/**
 * Cost Explorer — where the money actually went.
 *
 * The chat's CostBar shows a single number for the current turn; the DB has had
 * per-agent and per-model attribution all along with no view onto it. This is
 * that view: a treemap of spend by agent (drill into per-model), plus a 24h
 * cost-over-time strip.
 */
import { useMemo, useState } from 'react'
import { agentColor, formatTokens, formatUSD, getCostHistory, getUsage } from './api'
import { Panel, Stat, ViewState, usePolled } from './shared'
import type { AgentUsage, CostPoint } from './types'

// ── Squarified-ish treemap: slice-and-dice alternating axis. Good enough for
// ~15 agents and far less code than a full squarify. ─────────────────────────
interface Rect { x: number; y: number; w: number; h: number }
interface Tile<T> extends Rect { item: T }

function layout<T>(items: T[], weight: (t: T) => number, box: Rect, horizontal = true): Tile<T>[] {
  if (items.length === 0) return []
  if (items.length === 1) return [{ ...box, item: items[0] }]
  const total = items.reduce((s, i) => s + weight(i), 0)
  if (total <= 0) return []

  // Split the list at the point that best halves the total weight.
  let acc = 0
  let split = 1
  let best = Infinity
  for (let i = 1; i < items.length; i++) {
    acc += weight(items[i - 1])
    const diff = Math.abs(total / 2 - acc)
    if (diff < best) { best = diff; split = i }
  }
  const head = items.slice(0, split)
  const tail = items.slice(split)
  const headWeight = head.reduce((s, i) => s + weight(i), 0)
  const ratio = headWeight / total

  const a: Rect = horizontal
    ? { x: box.x, y: box.y, w: box.w * ratio, h: box.h }
    : { x: box.x, y: box.y, w: box.w, h: box.h * ratio }
  const b: Rect = horizontal
    ? { x: box.x + box.w * ratio, y: box.y, w: box.w * (1 - ratio), h: box.h }
    : { x: box.x, y: box.y + box.h * ratio, w: box.w, h: box.h * (1 - ratio) }

  return [...layout(head, weight, a, !horizontal), ...layout(tail, weight, b, !horizontal)]
}

function CostSparkline({ points }: { points: CostPoint[] }) {
  // Bucket by hour, summing every agent/model that reported in that hour.
  const buckets = useMemo(() => {
    const m = new Map<string, number>()
    for (const p of points) m.set(p.timestamp, (m.get(p.timestamp) ?? 0) + p.cost_usd)
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [points])

  if (buckets.length === 0) {
    return (
      <div className="px-4 py-6 text-center text-xs font-mono" style={{ color: 'var(--color-text-muted)' }}>
        No spend recorded in this window.
      </div>
    )
  }

  const max = Math.max(...buckets.map((b) => b[1]))
  const W = 100
  const H = 28
  const step = buckets.length > 1 ? W / (buckets.length - 1) : 0
  const pts = buckets.map(([, v], i) => `${(i * step).toFixed(2)},${(H - (v / max) * H).toFixed(2)}`)
  const line = pts.join(' ')
  const area = `0,${H} ${line} ${((buckets.length - 1) * step).toFixed(2)},${H}`

  return (
    <div className="px-4 py-3">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="w-full h-16" role="img" aria-label="Cost over the selected window">
        <polygon points={area} fill="var(--color-accent)" opacity="0.14" />
        <polyline points={line} fill="none" stroke="var(--color-accent)" strokeWidth="0.8" vectorEffect="non-scaling-stroke" />
        {buckets.length > 0 && (
          <circle
            cx={((buckets.length - 1) * step).toFixed(2)}
            cy={(H - (buckets[buckets.length - 1][1] / max) * H).toFixed(2)}
            r="1.4"
            fill="var(--color-accent)"
          />
        )}
      </svg>
      <div className="flex justify-between text-[12px] font-mono mt-1" style={{ color: 'var(--color-text-muted)' }}>
        <span>{new Date(buckets[0][0]).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit' })}</span>
        <span>peak {formatUSD(max)}/h</span>
        <span>now</span>
      </div>
    </div>
  )
}

export function CostExplorer() {
  const usage = usePolled(getUsage, 20_000)
  const [hours, setHours] = useState(24)
  const history = usePolled(useMemo(() => () => getCostHistory(hours), [hours]), 30_000)
  const [selected, setSelected] = useState<string | null>(null)

  const agents = useMemo(
    () => (usage.data?.agent_usage ?? []).filter((a) => a.total_cost_usd > 0).sort((a, b) => b.total_cost_usd - a.total_cost_usd),
    [usage.data],
  )

  const tiles = useMemo(
    () => layout<AgentUsage>(agents, (a) => a.total_cost_usd, { x: 0, y: 0, w: 100, h: 100 }),
    [agents],
  )

  const active = agents.find((a) => a.name === selected) ?? null
  const modelRows = useMemo(() => {
    if (!active) return []
    return Object.entries(active.by_model)
      .map(([model, u]) => ({ model, ...u }))
      .sort((a, b) => b.cost_usd - a.cost_usd)
  }, [active])

  const total = usage.data?.total_cost_usd ?? 0

  return (
    <div className="flex flex-col gap-3 h-full min-h-0">
      <div className="flex flex-wrap gap-8 px-4 py-3 rounded border flex-shrink-0" style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-panel)' }}>
        <Stat label="Total spend" value={formatUSD(total)} tone="var(--color-accent)" />
        <Stat label="Agents billing" value={String(agents.length)} />
        <Stat label="Turns" value={formatTokens(agents.reduce((s, a) => s + a.total_turns, 0))} />
        <Stat label="Tool calls" value={formatTokens(agents.reduce((s, a) => s + a.total_tool_calls, 0))} />
      </div>

      <div className="grid gap-3 flex-1 min-h-0" style={{ gridTemplateColumns: 'minmax(0, 3fr) minmax(0, 2fr)' }}>
        <Panel title="Spend by agent" subtitle="area ∝ cost — click to drill in">
          <ViewState
            loading={usage.loading && !usage.data}
            error={usage.error}
            empty={agents.length === 0}
            emptyLabel="No cost recorded yet."
            onRetry={usage.refresh}
          />
          {agents.length > 0 && (
            <div className="relative w-full h-full min-h-[240px]">
              {tiles.map(({ item, x, y, w, h }) => {
                const isSel = selected === item.name
                const showLabel = w > 11 && h > 9
                return (
                  <button
                    key={item.name}
                    onClick={() => setSelected(isSel ? null : item.name)}
                    title={`${item.name} — ${formatUSD(item.total_cost_usd)} (${((item.total_cost_usd / total) * 100).toFixed(1)}%)`}
                    aria-pressed={isSel}
                    className="absolute overflow-hidden text-left transition-opacity focus:outline-none focus:ring-1"
                    style={{
                      left: `${x}%`, top: `${y}%`, width: `${w}%`, height: `${h}%`,
                      background: agentColor(item.name),
                      opacity: selected && !isSel ? 0.35 : 0.85,
                      border: '1px solid var(--color-bg-panel)',
                    }}
                  >
                    {showLabel && (
                      <span className="block p-1.5 leading-tight">
                        <span className="block text-[12px] font-mono font-semibold text-black/85 truncate">{item.name}</span>
                        <span className="block text-[12px] font-mono tabular-nums text-black/65">{formatUSD(item.total_cost_usd)}</span>
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          )}
        </Panel>

        <div className="flex flex-col gap-3 min-h-0">
          <Panel
            title={active ? `${active.name} · by model` : 'By model'}
            subtitle={active ? undefined : 'select an agent'}
          >
            {!active && (
              <div className="py-8 text-center text-xs font-mono" style={{ color: 'var(--color-text-muted)' }}>
                Pick an agent from the treemap.
              </div>
            )}
            {active && (
              <div className="overflow-auto max-h-[220px]">
                <table className="w-full text-[13px] font-mono">
                  <thead>
                    <tr style={{ color: 'var(--color-text-muted)' }}>
                      <th className="text-left font-normal px-3 py-1.5">Model</th>
                      <th className="text-right font-normal px-3 py-1.5">Cost</th>
                      <th className="text-right font-normal px-3 py-1.5">Turns</th>
                      <th className="text-right font-normal px-3 py-1.5">In/Out</th>
                    </tr>
                  </thead>
                  <tbody>
                    {modelRows.map((r) => (
                      <tr key={r.model} className="border-t" style={{ borderColor: 'var(--color-border-muted)' }}>
                        <td className="px-3 py-1.5 truncate max-w-[150px]" style={{ color: 'var(--color-text-primary)' }}>{r.model}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums" style={{ color: 'var(--color-accent)' }}>{formatUSD(r.cost_usd)}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums" style={{ color: 'var(--color-text-secondary)' }}>{r.turns}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums" style={{ color: 'var(--color-text-muted)' }}>
                          {formatTokens(r.input_tokens)}/{formatTokens(r.output_tokens)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Panel
            title="Cost over time"
            right={
              <div className="flex gap-1">
                {[6, 24, 168].map((h) => (
                  <button
                    key={h}
                    onClick={() => setHours(h)}
                    className="text-[12px] font-mono px-1.5 py-0.5 rounded border"
                    style={{
                      borderColor: hours === h ? 'var(--color-accent)' : 'var(--color-border)',
                      color: hours === h ? 'var(--color-accent)' : 'var(--color-text-muted)',
                    }}
                  >
                    {h === 168 ? '7d' : `${h}h`}
                  </button>
                ))}
              </div>
            }
          >
            <ViewState
              loading={history.loading && !history.data}
              error={history.error}
              empty={false}
              emptyLabel=""
              onRetry={history.refresh}
            />
            {history.data && <CostSparkline points={history.data.points} />}
          </Panel>
        </div>
      </div>
    </div>
  )
}
