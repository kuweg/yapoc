/**
 * Shared live-topology data: who exists, who is running right now, and who has
 * handed work to whom. Feeds both the analytical Insights view and the ambient
 * HUD panel, so the two can never disagree about the shape of the system.
 */
import { useMemo } from 'react'
import { useAgents } from '../hooks/useAgents'
import { getHierarchy, getNotificationTrace } from '../insights/api'
import { usePolled } from '../insights/shared'

export type NodeState = 'running' | 'idle' | 'error' | 'unknown'

export interface TopoNode {
  name: string
  state: NodeState
  /** Times this agent delegated work — drives node size. */
  delegated: number
  received: number
  model?: string
  pid?: number | null
  /** Angle on the ring, radians. */
  angle: number
  x: number
  y: number
}

export interface TopoEdge {
  from: string
  to: string
  count: number
  lastTs: string
  /** True when the handoff happened recently enough to animate. */
  hot: boolean
}

export const RING_RADIUS = 26
export const CENTRE = 50
/** A handoff younger than this animates as an active flow. */
const HOT_WINDOW_MS = 5 * 60_000

function stateOf(status: string | undefined, health: string | undefined): NodeState {
  const s = (status ?? '').toLowerCase()
  if (health === 'critical') return 'error'
  if (s === 'running' || s === 'busy') return 'running'
  if (s === 'error' || s === 'failed') return 'error'
  if (s === 'idle' || s === 'done' || s === 'terminated') return 'idle'
  return 'unknown'
}

export function useTopologyData(enabled = true) {
  const { agents } = useAgents(enabled ? 3000 : 600_000)
  const hierarchy = usePolled(getHierarchy, 30_000, enabled)
  const trace = usePolled(getNotificationTrace, 10_000, enabled)

  return useMemo(() => {
    const delegated = hierarchy.data?.delegated_by_parent ?? {}
    const events = trace.data?.events ?? []
    const now = Date.now()

    const edgeMap = new Map<string, TopoEdge>()
    const received = new Map<string, number>()
    for (const e of events) {
      if (!e.parent_agent || !e.child_agent) continue
      const key = `${e.parent_agent}→${e.child_agent}`
      const hit = edgeMap.get(key)
      if (hit) {
        hit.count += 1
        if (e.ts > hit.lastTs) hit.lastTs = e.ts
      } else {
        edgeMap.set(key, { from: e.parent_agent, to: e.child_agent, count: 1, lastTs: e.ts, hot: false })
      }
      received.set(e.child_agent, (received.get(e.child_agent) ?? 0) + 1)
    }
    for (const e of edgeMap.values()) {
      const t = Date.parse(e.lastTs)
      e.hot = !Number.isNaN(t) && now - t < HOT_WINDOW_MS
    }

    const statusByName = new Map(agents.map((a) => [a.name, a]))
    const names = new Set<string>([...Object.keys(delegated), ...agents.map((a) => a.name)])
    for (const e of edgeMap.values()) { names.add(e.from); names.add(e.to) }

    // Busiest delegators first so the biggest hub lands at the top of the ring.
    const ordered = [...names].sort((a, b) => (delegated[b] ?? 0) - (delegated[a] ?? 0) || a.localeCompare(b))

    const nodes: TopoNode[] = ordered.map((name, i) => {
      const angle = (i / Math.max(ordered.length, 1)) * Math.PI * 2 - Math.PI / 2
      const st = statusByName.get(name)
      return {
        name,
        state: stateOf(st?.status ?? st?.state, st?.health),
        delegated: delegated[name] ?? 0,
        received: received.get(name) ?? 0,
        model: st?.model,
        pid: st?.pid ?? null,
        angle,
        x: CENTRE + Math.cos(angle) * RING_RADIUS,
        y: CENTRE + Math.sin(angle) * RING_RADIUS,
      }
    })

    const edges = [...edgeMap.values()].sort((a, b) => b.count - a.count)
    return {
      nodes,
      edges,
      byName: new Map(nodes.map((n) => [n.name, n])),
      runningCount: nodes.filter((n) => n.state === 'running').length,
      errorCount: nodes.filter((n) => n.state === 'error').length,
      hotCount: edges.filter((e) => e.hot).length,
      loading: (hierarchy.loading && !hierarchy.data) || (trace.loading && !trace.data),
      error: hierarchy.error ?? trace.error,
      refresh: () => { hierarchy.refresh(); trace.refresh() },
    }
  }, [agents, hierarchy, trace])
}
