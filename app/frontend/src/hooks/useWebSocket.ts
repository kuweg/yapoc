/**
 * WebSocket hook — maintains a persistent connection to the backend /ws endpoint.
 *
 * Handles reconnection with exponential backoff. Dispatches parsed events
 * to the wsStore so any component can subscribe to real-time updates.
 */
import { useEffect, useRef } from 'react'
import { useWsStore } from '../store/wsStore'
import { useSessionStore } from '../store/session'

const WS_URL = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`
// The backend is local and restarts often (server_restart, deploys). The old
// 1s→30s backoff burned its early retries while the port was still down, then
// waited ~11s — long enough for a whole post-restart resume task to run and
// finish unseen, which is why the chat looked idle while the agent panel filled
// up. Localhost reconnects are cheap: retry quickly, cap low, and never stop.
const BASE_DELAY_MS = 400
const MAX_DELAY_MS = 3_000

export function useWebSocket() {
  const activeSessionId = useSessionStore((s) => s.activeId)
  const subscribedAgents = useWsStore((s) => s.subscribedAgents)
  const wsRef = useRef<WebSocket | null>(null)
  const activeSessionRef = useRef<string | null>(activeSessionId)
  const subscribedSessionRef = useRef<string | null>(null)
  const subscribedAgentsRef = useRef<Set<string>>(new Set())
  const retryRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const unmountedRef = useRef(false)

  useEffect(() => {
    activeSessionRef.current = activeSessionId
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return

    const prev = subscribedSessionRef.current
    const next = activeSessionId

    if (prev && prev !== next) {
      ws.send(JSON.stringify({ type: 'unsubscribe', session_id: prev }))
      subscribedSessionRef.current = null
    }
    if (next && next !== prev) {
      ws.send(JSON.stringify({ type: 'subscribe', session_id: next }))
      subscribedSessionRef.current = next
    }
  }, [activeSessionId])

  // Reconcile per-agent subscriptions against the open WS.
  useEffect(() => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    const desired = new Set(subscribedAgents)
    for (const agent of subscribedAgentsRef.current) {
      if (!desired.has(agent)) {
        ws.send(JSON.stringify({ type: 'unsubscribe_agent', agent }))
      }
    }
    for (const agent of desired) {
      if (!subscribedAgentsRef.current.has(agent)) {
        ws.send(JSON.stringify({ type: 'subscribe_agent', agent }))
      }
    }
    subscribedAgentsRef.current = desired
  }, [subscribedAgents])

  useEffect(() => {
    unmountedRef.current = false

    function connect() {
      if (unmountedRef.current) return

      try {
        const ws = new WebSocket(WS_URL)
        wsRef.current = ws

        ws.onopen = () => {
          retryRef.current = 0
          useWsStore.getState().setConnected(true)
          const sid = activeSessionRef.current
          if (sid) {
            ws.send(JSON.stringify({ type: 'subscribe', session_id: sid }))
            subscribedSessionRef.current = sid
          }
          // Re-arm any per-agent subscriptions after reconnect. The server-
          // side subscriber set is wiped when the previous WS closed.
          const desired = new Set(useWsStore.getState().subscribedAgents)
          subscribedAgentsRef.current = new Set()
          for (const agent of desired) {
            ws.send(JSON.stringify({ type: 'subscribe_agent', agent }))
            subscribedAgentsRef.current.add(agent)
          }
        }

        ws.onmessage = (ev) => {
          try {
            const data = JSON.parse(ev.data)
            useWsStore.getState().handleEvent(data)
          } catch {
            // skip malformed frames
          }
        }

        ws.onclose = () => {
          useWsStore.getState().setConnected(false)
          wsRef.current = null
          subscribedSessionRef.current = null
          subscribedAgentsRef.current = new Set()
          scheduleReconnect()
        }

        ws.onerror = () => {
          // onclose will fire after onerror — reconnect handled there
        }
      } catch {
        scheduleReconnect()
      }
    }

    function scheduleReconnect() {
      if (unmountedRef.current) return
      // No retry ceiling: giving up leaves the chat permanently deaf to task
      // and session events until a manual page reload, with no visible cause.
      const delay = Math.min(BASE_DELAY_MS * Math.pow(2, retryRef.current), MAX_DELAY_MS)
      retryRef.current++
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(connect, delay)
    }

    // Coming back to the tab (or back online) is a strong hint the backend may
    // be reachable again — retry now instead of waiting out the backoff.
    function retryNow() {
      if (unmountedRef.current) return
      if (wsRef.current?.readyState === WebSocket.OPEN) return
      retryRef.current = 0
      if (timerRef.current) clearTimeout(timerRef.current)
      connect()
    }
    const onVisible = () => {
      if (document.visibilityState === 'visible') retryNow()
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('online', retryNow)

    connect()

    // Ping keepalive every 30s
    const pingInterval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }))
      }
    }, 30_000)

    return () => {
      unmountedRef.current = true
      clearInterval(pingInterval)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('online', retryNow)
      if (timerRef.current) clearTimeout(timerRef.current)
      wsRef.current?.close()
    }
  }, [])
}
