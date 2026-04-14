/**
 * WebSocket hook — maintains a persistent connection to the backend /ws endpoint.
 *
 * Handles reconnection with exponential backoff. Dispatches parsed events
 * to the wsStore so any component can subscribe to real-time updates.
 */
import { useEffect, useRef } from 'react'
import { useWsStore } from '../store/wsStore'

const WS_URL = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`
const MAX_RETRIES = 10
const BASE_DELAY_MS = 1_000
const MAX_DELAY_MS = 30_000

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const unmountedRef = useRef(false)

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
      if (retryRef.current >= MAX_RETRIES) return

      const delay = Math.min(BASE_DELAY_MS * Math.pow(2, retryRef.current), MAX_DELAY_MS)
      retryRef.current++
      timerRef.current = setTimeout(connect, delay)
    }

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
      if (timerRef.current) clearTimeout(timerRef.current)
      wsRef.current?.close()
    }
  }, [])
}
