import { useEffect } from 'react'
import { useAgentStore } from '../store/agentStore'
import type { AgentEvent } from '../types'

export function useEventStream() {
  const pushEvent = useAgentStore((s) => s.pushEvent)

  useEffect(() => {
    let es: EventSource | null = null
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let active = true

    function connect() {
      if (!active) return
      es = new EventSource('/api/agents/events/stream')
      es.onmessage = (e) => {
        try {
          const event: AgentEvent = JSON.parse(e.data)
          pushEvent(event)
        } catch { /* skip malformed */ }
      }
      es.onerror = () => {
        es?.close()
        if (active) retryTimer = setTimeout(connect, 10000)
      }
    }

    connect()
    return () => {
      active = false
      es?.close()
      if (retryTimer) clearTimeout(retryTimer)
    }
  }, [pushEvent])
}
