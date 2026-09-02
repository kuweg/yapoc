/**
 * Delegation Topology — who actually delegates to whom.
 *
 * The agent sidebar is a flat list; the delegation hierarchy it implies was
 * never drawn. Edges come from the notification trace (real parent→child
 * handoffs), node weight from the per-parent delegation counts, and the ring
 * layout keeps it readable without pulling in a graph library.
 */
import { useMemo, useState } from 'react'
import { agentColor, formatDuration, getHierarchy, getNotificationTrace, relativeTime } from './api'
import { Panel, Stat, ViewState, usePolled } from './shared'

interface Edge { from: string; to: string; count: number; lastTs: string }
interface Node { name: string; x: number; y: number; delegated: number; received: number; avgSeconds: number }

const R = 38 // ring radius in viewBox units
const CX = 50
const CY = 50

export function DelegationTopology() {
  const hierarchy = usePolled(getHierarchy, 20_000)
  const trace = usePolled(getNotificationTrace, 15_000)
  const [focus, setFocus] = useState<string | null>(null)

  const { nodes, edges } = useMemo(() => {
    const events = trace.data?.events ?? []
    const delegated = hierarchy.data?.delegated_by_parent ?? {}
    const avg = hierarchy.data?.average_completion_seconds_by_parent ?? {}

    const edgeMap = new Map<string, Edge>()
    const received = new Map<string, number>()
    for (const e of events) {
      if (!e.parent_agent || !e.child_agent) continue
      const key = `${e.parent_agent}→${e.child_agent}`
      const existing = edgeMap.get(key)
      if (existing) {
        existing.count += 1
        if (e.ts > existing.lastTs) existing.lastTs = e.ts
      } else {
        edgeMap.set(key, { from: e.parent_agent, to: e.child_agent, count: 1, lastTs: e.ts })
      }
      received.set(e.child_agent, (received.get(e.child_agent) ?? 0) + 1)
    }

    const names = new Set<string>([...Object.keys(delegated)])
    for (const e of edgeMap.values()) { names.add(e.from); names.add(e.to) }
    const ordered = [...names].sort((a, b) => (delegated[b] ?? 0) - (delegated[a] ?? 0))

    const built: Node[] = ordered.map((name, i) => {
      const angle = (i / Math.max(ordered.length, 1)) * Math.PI * 2 - Math.PI / 2
      return {
        name,
        x: CX + Math.cos(angle) * R,
        y: CY + Math.sin(angle) * R,
        delegated: delegated[name] ?? 0,
        received: received.get(name) ?? 0,
        avgSeconds: avg[name] ?? 0,
      }
    })
    return { nodes: built, edges: [...edgeMap.values()].sort((a, b) => b.count - a.count) }
  }, [hierarchy.data, trace.data])

  const pos = useMemo(() => new Map(nodes.map((n) => [n.name, n])), [nodes])
  const maxEdge = Math.max(1, ...edges.map((e) => e.count))
  const maxDelegated = Math.max(1, ...nodes.map((n) => n.delegated))

  const loading = (hierarchy.loading && !hierarchy.data) || (trace.loading && !trace.data)
  const error = hierarchy.error ?? trace.error

  const visibleEdges = focus ? edges.filter((e) => e.from === focus || e.to === focus) : edges

  return (
    <div className="flex flex-col gap-3 h-full min-h-0">
      <div className="flex flex-wrap gap-8 px-4 py-3 rounded border flex-shrink-0" style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-panel)' }}>
        <Stat label="Agents in graph" value={String(nodes.length)} />
        <Stat label="Delegation edges" value={String(edges.length)} />
        <Stat label="Task records" value={String(hierarchy.data?.total_task_records ?? 0)} />
        <Stat label="Busiest link" value={edges[0] ? `${edges[0].from}→${edges[0].to}` : '—'} />
      </div>

      <div className="grid gap-3 flex-1 min-h-0" style={{ gridTemplateColumns: 'minmax(0, 3fr) minmax(0, 2fr)' }}>
        <Panel title="Delegation graph" subtitle={focus ? `focused on ${focus} — click again to clear` : 'click a node to focus'}>
          <ViewState loading={loading} error={error} empty={nodes.length === 0} emptyLabel="No delegation recorded yet." onRetry={() => { hierarchy.refresh(); trace.refresh() }} />
          {nodes.length > 0 && (
            <div className="w-full h-full min-h-[280px] p-2">
              <svg viewBox="0 0 100 100" className="w-full h-full" role="img" aria-label="Agent delegation graph">
                {visibleEdges.map((e, ei) => {
                  const a = pos.get(e.from)
                  const b = pos.get(e.to)
                  if (!a || !b) return null
                  // Quadratic curve bowing toward the centre keeps parallel
                  // edges from overlapping into an unreadable mess.
                  const mx = (a.x + b.x) / 2
                  const my = (a.y + b.y) / 2
                  const qx = mx + (CX - mx) * 0.45
                  const qy = my + (CY - my) * 0.45
                  return (
                    <path
                      key={`e-${ei}-${e.from}-${e.to}`}
                      d={`M ${a.x} ${a.y} Q ${qx} ${qy} ${b.x} ${b.y}`}
                      fill="none"
                      stroke={agentColor(e.from)}
                      strokeWidth={0.25 + (e.count / maxEdge) * 1.1}
                      opacity={focus ? 0.85 : 0.45}
                    />
                  )
                })}
                {nodes.map((n, ni) => {
                  const r = 1.6 + (n.delegated / maxDelegated) * 3.2
                  const dim = focus !== null && focus !== n.name && !visibleEdges.some((e) => e.from === n.name || e.to === n.name)
                  return (
                    <g key={`n-${ni}-${n.name}`} opacity={dim ? 0.25 : 1}>
                      <circle
                        cx={n.x} cy={n.y} r={r}
                        fill={agentColor(n.name)}
                        stroke={focus === n.name ? 'var(--color-text-primary)' : 'var(--color-bg-panel)'}
                        strokeWidth={focus === n.name ? 0.7 : 0.35}
                        style={{ cursor: 'pointer' }}
                        onClick={() => setFocus(focus === n.name ? null : n.name)}
                      >
                        <title>{`${n.name} — delegated ${n.delegated}, received ${n.received}`}</title>
                      </circle>
                      <text
                        x={n.x} y={n.y + r + 2.6}
                        textAnchor="middle"
                        style={{ fontSize: '2.4px', fill: 'var(--color-text-secondary)', fontFamily: 'monospace', pointerEvents: 'none' }}
                      >
                        {n.name}
                      </text>
                    </g>
                  )
                })}
              </svg>
            </div>
          )}
        </Panel>

        <Panel title="Edges" subtitle={`${visibleEdges.length} shown`}>
          <div className="overflow-auto max-h-full">
            {visibleEdges.length === 0 ? (
              <div className="py-8 text-center text-xs font-mono" style={{ color: 'var(--color-text-muted)' }}>No edges.</div>
            ) : (
              <table className="w-full text-[13px] font-mono">
                <thead>
                  <tr style={{ color: 'var(--color-text-muted)' }}>
                    <th className="text-left font-normal px-3 py-1.5">Parent → Child</th>
                    <th className="text-right font-normal px-3 py-1.5">Handoffs</th>
                    <th className="text-right font-normal px-3 py-1.5">Last</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleEdges.slice(0, 60).map((e, ri) => (
                    <tr key={`r-${ri}-${e.from}-${e.to}`} className="border-t" style={{ borderColor: 'var(--color-border-muted)' }}>
                      <td className="px-3 py-1.5">
                        <span style={{ color: agentColor(e.from) }}>{e.from}</span>
                        <span style={{ color: 'var(--color-text-muted)' }}> → </span>
                        <span style={{ color: agentColor(e.to) }}>{e.to}</span>
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums" style={{ color: 'var(--color-text-primary)' }}>{e.count}</td>
                      <td className="px-3 py-1.5 text-right" style={{ color: 'var(--color-text-muted)' }}>{relativeTime(e.lastTs)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Panel>
      </div>

      {hierarchy.data && (
        <Panel title="Average completion by parent" className="flex-shrink-0">
          <div className="flex flex-wrap gap-4 px-4 py-3">
            {Object.entries(hierarchy.data.average_completion_seconds_by_parent)
              .filter(([, v]) => v > 0)
              .sort((a, b) => b[1] - a[1])
              .map(([name, secs]) => (
                <div key={name} className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: agentColor(name) }} />
                  <span className="text-[12px] font-mono" style={{ color: 'var(--color-text-secondary)' }}>{name}</span>
                  <span className="text-[12px] font-mono tabular-nums" style={{ color: secs > 90 ? 'var(--color-warning)' : 'var(--color-text-primary)' }}>
                    {formatDuration(secs)}
                  </span>
                </div>
              ))}
          </div>
        </Panel>
      )}
    </div>
  )
}
