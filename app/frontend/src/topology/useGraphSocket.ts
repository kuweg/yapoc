/**
 * Live feed for the topology HUD — subscribes to the backend's dedicated
 * /ws/graph socket.
 *
 * The socket delivers a snapshot on connect, a batch of recent events, then
 * every topology change as it happens: a delegation lights its edge the moment
 * `spawn_agent` runs, and clears when the child reports done. Polling still
 * runs underneath as the source of truth for counts and history; this layer
 * only supplies immediacy.
 */
import { useEffect, useRef, useState } from 'react'

export interface GraphEvent {
  event_type:
    | 'agent_spawned'
    | 'agent_died'
    | 'task_assigned'
    | 'task_completed'
    | 'notification_sent'
    | 'health_logged'
    | 'status_changed'
  source: string
  target?: string
  timestamp: string
  task_id?: string
  status?: string
  level?: string
  message?: string
  old_status?: string
  new_status?: string
}

/** An edge currently carrying work, keyed `source→target`. */
export type ActiveEdges = Record<string, number>

export interface GraphSocketState {
  connected: boolean
  /** Edges with work in flight right now (value = start timestamp ms). */
  activeEdges: ActiveEdges
  /** Agents the socket believes are busy right now. */
  busyAgents: Set<string>
  /** Newest events first, capped. */
  events: GraphEvent[]
  /** Bumped on every event so consumers can trigger a one-shot flash. */
  pulse: number
}

const MAX_EVENTS = 60
/** An edge with no completion event is released after this, so a dropped
 *  completion can't leave the graph permanently lit. */
const EDGE_TTL_MS = 3 * 60_000

function wsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws/graph`
}

export function useGraphSocket(enabled = true): GraphSocketState {
  const [state, setState] = useState<GraphSocketState>({
    connected: false,
    activeEdges: {},
    busyAgents: new Set(),
    events: [],
    pulse: 0,
  })
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef<number>(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!enabled) return
    let closed = false

    const apply = (ev: GraphEvent) => {
      setState((prev) => {
        const activeEdges = { ...prev.activeEdges }
        const busy = new Set(prev.busyAgents)
        const key = ev.target ? `${ev.source}→${ev.target}` : ''

        switch (ev.event_type) {
          case 'task_assigned':
          case 'agent_spawned':
            if (key) activeEdges[key] = Date.now()
            if (ev.target) busy.add(ev.target)
            break
          case 'task_completed':
          case 'agent_died':
            if (key) delete activeEdges[key]
            if (ev.target) busy.delete(ev.target)
            break
          case 'status_changed':
            if (ev.new_status === 'running') busy.add(ev.source)
            else busy.delete(ev.source)
            break
          default:
            break
        }

        // Expire stale edges rather than trusting every completion to arrive.
        const now = Date.now()
        for (const [k, started] of Object.entries(activeEdges)) {
          if (now - started > EDGE_TTL_MS) delete activeEdges[k]
        }

        return {
          connected: prev.connected,
          activeEdges,
          busyAgents: busy,
          events: [ev, ...prev.events].slice(0, MAX_EVENTS),
          pulse: prev.pulse + 1,
        }
      })
    }

    const connect = () => {
      if (closed) return
      let ws: WebSocket
      try {
        ws = new WebSocket(wsUrl())
      } catch {
        schedule()
        return
      }
      wsRef.current = ws

      ws.onopen = () => {
        retryRef.current = 0
        setState((p) => ({ ...p, connected: true }))
      }

      ws.onmessage = (msg) => {
        let data: Record<string, unknown>
        try {
          data = JSON.parse(msg.data as string)
        } catch {
          return
        }
        const type = data.type as string
        if (type === 'graph_event') {
          apply(data as unknown as GraphEvent)
        } else if (type === 'graph_recent_events') {
          const evs = (data.events as GraphEvent[]) ?? []
          for (const e of evs) apply(e)
        }
        // graph_initial_snapshot carries agents/edges, but the polled
        // hierarchy is already authoritative for those — ignore it here
        // rather than maintaining two sources for the same shape.
      }

      ws.onclose = () => {
        setState((p) => ({ ...p, connected: false }))
        schedule()
      }
      ws.onerror = () => ws.close()
    }

    const schedule = () => {
      if (closed) return
      // Exponential backoff, capped — a downed backend shouldn't spin.
      const delay = Math.min(1000 * 2 ** retryRef.current, 15_000)
      retryRef.current += 1
      timerRef.current = setTimeout(connect, delay)
    }

    connect()

    return () => {
      closed = true
      if (timerRef.current) clearTimeout(timerRef.current)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [enabled])

  return state
}
