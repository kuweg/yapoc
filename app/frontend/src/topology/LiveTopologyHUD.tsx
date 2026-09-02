/**
 * Live system topology — the ambient "is anything happening right now" view.
 *
 * Collapsed it's a one-line status rail pinned to the bottom of the app: a dot
 * per agent, lit when that agent is running. Click the label and it expands
 * into a full animated graph — nodes pulse while running, recent handoffs send
 * a packet travelling along their edge, and a slow sweep ring keeps the whole
 * thing feeling live rather than static.
 *
 * All motion is suppressed under `prefers-reduced-motion`.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { agentColor, relativeTime } from '../insights/api'
import { CENTRE, RING_RADIUS, useTopologyData, type NodeState, type TopoNode } from './useTopologyData'
import { useGraphSocket } from './useGraphSocket'

const EVENT_GLYPH: Record<string, string> = {
  task_assigned: '▸',
  task_completed: '✓',
  agent_spawned: '+',
  agent_died: '×',
  notification_sent: '↩',
  health_logged: '!',
  status_changed: '~',
}

const EVENT_TONE: Record<string, string> = {
  task_assigned: 'var(--color-accent)',
  task_completed: 'var(--color-success)',
  agent_spawned: 'var(--color-accent)',
  agent_died: 'var(--color-text-muted)',
  notification_sent: 'var(--color-info)',
  health_logged: 'var(--color-error)',
  status_changed: 'var(--color-text-secondary)',
}

const STATE_COLOR: Record<NodeState, string> = {
  running: 'var(--color-accent)',
  idle: 'var(--color-text-muted)',
  error: 'var(--color-error)',
  unknown: 'var(--color-text-disabled)',
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches,
  )
  useEffect(() => {
    if (typeof matchMedia !== 'function') return
    const mq = matchMedia('(prefers-reduced-motion: reduce)')
    const on = () => setReduced(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return reduced
}

/** Quadratic curve bowing toward the centre — keeps parallel edges apart. */
function edgePath(a: TopoNode, b: TopoNode): string {
  const mx = (a.x + b.x) / 2
  const my = (a.y + b.y) / 2
  const qx = mx + (CENTRE - mx) * 0.5
  const qy = my + (CENTRE - my) * 0.5
  return `M ${a.x} ${a.y} Q ${qx} ${qy} ${b.x} ${b.y}`
}

export function LiveTopologyHUD() {
  const [expanded, setExpanded] = useState(false)
  const [focus, setFocus] = useState<string | null>(null)
  const topo = useTopologyData(true)
  const live = useGraphSocket(true)
  const reduced = usePrefersReducedMotion()
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setExpanded(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])

  const { nodes: baseNodes, edges: baseEdges, errorCount } = topo

  // Overlay the socket's real-time view on the polled shape: an agent the
  // socket saw receive work is running *now*, whatever the 3s status poll
  // still says, and its edge is live until the completion event lands.
  const { nodes, edges, byName, runningCount, hotCount } = useMemo(() => {
    const ns = baseNodes.map((n) =>
      live.busyAgents.has(n.name) && n.state !== 'error' ? { ...n, state: 'running' as NodeState } : n,
    )
    const es = baseEdges.map((e) => ({
      ...e,
      hot: e.hot || `${e.from}→${e.to}` in live.activeEdges,
    }))
    // A socket edge with no counterpart in the polled history is a brand-new
    // delegation — show it immediately rather than waiting for the next poll.
    const known = new Set(es.map((e) => `${e.from}→${e.to}`))
    for (const key of Object.keys(live.activeEdges)) {
      if (known.has(key)) continue
      const [from, to] = key.split('→')
      if (!from || !to) continue
      es.push({ from, to, count: 1, lastTs: new Date(live.activeEdges[key]).toISOString(), hot: true })
    }
    return {
      nodes: ns,
      edges: es,
      byName: new Map(ns.map((n) => [n.name, n])),
      runningCount: ns.filter((n) => n.state === 'running').length,
      hotCount: es.filter((e) => e.hot).length,
    }
  }, [baseNodes, baseEdges, live.busyAgents, live.activeEdges])

  const maxDelegated = useMemo(() => Math.max(1, ...nodes.map((n) => n.delegated)), [nodes])
  const maxEdge = useMemo(() => Math.max(1, ...edges.map((e) => e.count)), [edges])

  const visibleEdges = focus ? edges.filter((e) => e.from === focus || e.to === focus) : edges
  const focused = focus ? byName.get(focus) : null

  return (
    <div
      ref={panelRef}
      className="flex-shrink-0 border-t"
      style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-secondary)' }}
      data-testid="topology-hud"
    >
      {/* ── Rail — always visible ─────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-4 py-1.5">
        <button
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-controls="topology-panel"
          className="flex items-center gap-2 text-[12px] font-mono uppercase tracking-[0.14em] px-2 py-0.5 rounded border transition-colors"
          style={{
            borderColor: expanded ? 'var(--color-accent)' : 'var(--color-border)',
            color: expanded ? 'var(--color-accent)' : 'var(--color-text-secondary)',
          }}
          title={expanded ? 'Collapse the system topology' : 'Expand the system topology'}
        >
          <span style={{ display: 'inline-block', transform: expanded ? 'rotate(90deg)' : 'none', transition: 'transform 160ms' }}>
            ▸
          </span>
          Topology
        </button>

        {/* Agent dots — the ambient signal when collapsed. */}
        <div className="flex items-center gap-1.5 flex-wrap min-w-0">
          {nodes.slice(0, 16).map((n, ri) => (
            <button
              key={`rail-${ri}-${n.name}`}
              onClick={() => { setFocus(n.name); setExpanded(true) }}
              title={`${n.name} — ${n.state}${n.model ? ` · ${n.model}` : ''}`}
              aria-label={`${n.name}: ${n.state}`}
              className="relative w-2 h-2 rounded-full flex-shrink-0"
              style={{
                background: n.state === 'running' ? agentColor(n.name) : STATE_COLOR[n.state],
                opacity: n.state === 'running' ? 1 : 0.5,
                boxShadow: n.state === 'running' ? `0 0 6px ${agentColor(n.name)}` : undefined,
                animation: n.state === 'running' && !reduced ? 'yapoc-topo-pulse 1.6s ease-in-out infinite' : undefined,
              }}
            />
          ))}
        </div>

        <div className="ml-auto flex items-center gap-3 text-[12px] font-mono flex-shrink-0">
          <span style={{ color: runningCount > 0 ? 'var(--color-accent)' : 'var(--color-text-muted)' }}>
            {runningCount} running
          </span>
          {hotCount > 0 && <span style={{ color: 'var(--color-success)' }}>{hotCount} active link{hotCount === 1 ? '' : 's'}</span>}
          {errorCount > 0 && <span style={{ color: 'var(--color-error)' }}>{errorCount} error</span>}
          <span
            className="flex items-center gap-1"
            title={live.connected ? 'Streaming topology events' : 'Event stream down — falling back to polling'}
            data-testid="topology-feed-state"
          >
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{
                background: live.connected ? 'var(--color-success)' : 'var(--color-text-muted)',
                animation: live.connected && !reduced ? 'yapoc-topo-pulse 2.4s ease-in-out infinite' : undefined,
              }}
            />
            <span style={{ color: live.connected ? 'var(--color-success)' : 'var(--color-text-muted)' }}>
              {live.connected ? 'LIVE' : 'POLLING'}
            </span>
          </span>
        </div>
      </div>

      {/* ── Expanded graph ────────────────────────────────────────────────── */}
      <div
        id="topology-panel"
        style={{
          height: expanded ? 400 : 0,
          overflow: 'hidden',
          transition: reduced ? undefined : 'height 260ms cubic-bezier(0.4, 0, 0.2, 1)',
        }}
      >
        {expanded && (
          <div className="grid h-full" style={{ gridTemplateColumns: 'minmax(0, 1fr) 260px' }}>
            <div className="relative flex items-center justify-center overflow-hidden">
              {/* The viewBox is square, so pin the SVG to a square box and centre
                  it — stretching it across a wide panel blows the label type up
                  to ~30px and collides every node. */}
              <svg
                viewBox="0 0 100 100"
                style={{ height: '100%', aspectRatio: '1 / 1', display: 'block' }}
                role="img"
                aria-label="Live agent topology"
              >
                <defs>
                  <radialGradient id="yapoc-topo-core">
                    <stop offset="0%" stopColor="var(--color-accent)" stopOpacity="0.30" />
                    <stop offset="100%" stopColor="var(--color-accent)" stopOpacity="0" />
                  </radialGradient>
                </defs>

                {/* Ambient rings + slow sweep — the "system is alive" cue. */}
                <circle cx={CENTRE} cy={CENTRE} r={RING_RADIUS + 8} fill="url(#yapoc-topo-core)" />
                {[RING_RADIUS, RING_RADIUS * 0.66, RING_RADIUS * 0.33].map((r) => (
                  <circle key={r} cx={CENTRE} cy={CENTRE} r={r} fill="none" stroke="var(--color-border)" strokeWidth="0.15" opacity="0.5" />
                ))}
                {!reduced && (
                  <line
                    x1={CENTRE} y1={CENTRE} x2={CENTRE} y2={CENTRE - RING_RADIUS}
                    stroke="var(--color-accent)" strokeWidth="0.25" opacity="0.35"
                  >
                    <animateTransform
                      attributeName="transform" type="rotate"
                      from={`0 ${CENTRE} ${CENTRE}`} to={`360 ${CENTRE} ${CENTRE}`}
                      dur="12s" repeatCount="indefinite"
                    />
                  </line>
                )}

                {/* Edges */}
                {visibleEdges.map((e, ei) => {
                  const a = byName.get(e.from)
                  const b = byName.get(e.to)
                  if (!a || !b) return null
                  const d = edgePath(a, b)
                  const w = 0.2 + (e.count / maxEdge) * 1.0
                  return (
                    <g key={`edge-${ei}-${e.from}-${e.to}`}>
                      <path d={d} fill="none" stroke={agentColor(e.from)} strokeWidth={w} opacity={e.hot ? 0.75 : 0.3} />
                      {/* A packet travelling the edge marks a recent handoff. */}
                      {e.hot && !reduced && (
                        <circle r="0.8" fill={agentColor(e.from)}>
                          <animateMotion dur="2.4s" repeatCount="indefinite" path={d} />
                        </circle>
                      )}
                    </g>
                  )
                })}

                {/* Nodes */}
                {nodes.map((n, ni) => {
                  const r = 1.5 + (n.delegated / maxDelegated) * 2.8
                  const dim = focus !== null && focus !== n.name && !visibleEdges.some((e) => e.from === n.name || e.to === n.name)
                  const color = n.state === 'error' ? 'var(--color-error)' : agentColor(n.name)
                  return (
                    <g key={`node-${ni}-${n.name}`} opacity={dim ? 0.2 : 1} style={{ cursor: 'pointer' }} onClick={() => setFocus(focus === n.name ? null : n.name)}>
                      {n.state === 'running' && !reduced && (
                        <circle cx={n.x} cy={n.y} r={r} fill="none" stroke={color} strokeWidth="0.3">
                          <animate attributeName="r" values={`${r};${r + 3.5}`} dur="1.8s" repeatCount="indefinite" />
                          <animate attributeName="opacity" values="0.7;0" dur="1.8s" repeatCount="indefinite" />
                        </circle>
                      )}
                      <circle
                        cx={n.x} cy={n.y} r={r}
                        fill={color}
                        opacity={n.state === 'idle' ? 0.55 : 1}
                        stroke={focus === n.name ? 'var(--color-text-primary)' : 'var(--color-bg-secondary)'}
                        strokeWidth={focus === n.name ? 0.6 : 0.3}
                      >
                        <title>{`${n.name} — ${n.state}, delegated ${n.delegated}, received ${n.received}`}</title>
                      </circle>
                      {/* Labels sit outside the ring, anchored by hemisphere —
                          stacking them under each node collides once the ring
                          carries more than a handful of agents. */}
                      <text
                        x={CENTRE + Math.cos(n.angle) * (RING_RADIUS + 5)}
                        y={CENTRE + Math.sin(n.angle) * (RING_RADIUS + 5) + 0.8}
                        textAnchor={Math.abs(Math.cos(n.angle)) < 0.25 ? 'middle' : Math.cos(n.angle) > 0 ? 'start' : 'end'}
                        style={{
                          fontSize: '2.6px',
                          fill: focus === n.name ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
                          fontFamily: 'monospace',
                          pointerEvents: 'none',
                        }}
                      >
                        {n.name.length > 13 ? `${n.name.slice(0, 12)}…` : n.name}
                      </text>
                    </g>
                  )
                })}
              </svg>
            </div>

            {/* Side rail — focus detail, or the live link list. */}
            <div className="border-l overflow-auto" style={{ borderColor: 'var(--color-border)' }}>
              {focused ? (
                <div className="p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="w-2 h-2 rounded-full" style={{ background: agentColor(focused.name) }} />
                    <span className="text-[12px] font-mono" style={{ color: 'var(--color-text-primary)' }}>{focused.name}</span>
                    <button onClick={() => setFocus(null)} className="ml-auto text-[12px] font-mono" style={{ color: 'var(--color-text-muted)' }}>
                      clear
                    </button>
                  </div>
                  <dl className="text-[12px] font-mono grid grid-cols-2 gap-y-1">
                    <dt style={{ color: 'var(--color-text-muted)' }}>state</dt>
                    <dd style={{ color: STATE_COLOR[focused.state] }}>{focused.state}</dd>
                    <dt style={{ color: 'var(--color-text-muted)' }}>delegated</dt>
                    <dd style={{ color: 'var(--color-text-primary)' }}>{focused.delegated}</dd>
                    <dt style={{ color: 'var(--color-text-muted)' }}>received</dt>
                    <dd style={{ color: 'var(--color-text-primary)' }}>{focused.received}</dd>
                    {focused.model && (<>
                      <dt style={{ color: 'var(--color-text-muted)' }}>model</dt>
                      <dd className="truncate" style={{ color: 'var(--color-text-secondary)' }}>{focused.model}</dd>
                    </>)}
                    {focused.pid != null && (<>
                      <dt style={{ color: 'var(--color-text-muted)' }}>pid</dt>
                      <dd style={{ color: 'var(--color-text-secondary)' }}>{focused.pid}</dd>
                    </>)}
                  </dl>
                </div>
              ) : (
                <div className="p-3">
                  {/* Live event ticker when the socket is delivering, falling
                      back to the polled link list when it isn't. */}
                  {live.events.length > 0 ? (
                    <>
                      <p className="text-[12px] font-mono uppercase tracking-[0.14em] mb-2" style={{ color: 'var(--color-text-muted)' }}>
                        Live feed
                      </p>
                      {live.events.slice(0, 14).map((e, i) => (
                        <div key={`${e.timestamp}-${e.source}-${e.target ?? ''}-${i}`} className="flex items-center gap-1.5 text-[12px] font-mono py-0.5">
                          <span className="flex-shrink-0" style={{ color: EVENT_TONE[e.event_type] ?? 'var(--color-text-muted)' }}>
                            {EVENT_GLYPH[e.event_type] ?? '·'}
                          </span>
                          <span className="truncate" style={{ color: agentColor(e.source) }}>{e.source}</span>
                          {e.target && (<>
                            <span style={{ color: 'var(--color-text-muted)' }}>→</span>
                            <span className="truncate" style={{ color: agentColor(e.target) }}>{e.target}</span>
                          </>)}
                          <span className="ml-auto flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>
                            {relativeTime(e.timestamp)}
                          </span>
                        </div>
                      ))}
                    </>
                  ) : (
                    <>
                      <p className="text-[12px] font-mono uppercase tracking-[0.14em] mb-2" style={{ color: 'var(--color-text-muted)' }}>
                        Recent links
                      </p>
                      {edges.slice(0, 12).map((e, li) => (
                        <div key={`link-${li}-${e.from}-${e.to}`} className="flex items-center gap-1.5 text-[12px] font-mono py-0.5">
                          {e.hot && <span className="w-1 h-1 rounded-full flex-shrink-0" style={{ background: 'var(--color-success)' }} />}
                          <span className="truncate" style={{ color: agentColor(e.from) }}>{e.from}</span>
                          <span style={{ color: 'var(--color-text-muted)' }}>→</span>
                          <span className="truncate" style={{ color: agentColor(e.to) }}>{e.to}</span>
                          <span className="ml-auto flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>{relativeTime(e.lastTs)}</span>
                        </div>
                      ))}
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
