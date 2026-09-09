import { useEffect, useState, useCallback, useMemo } from 'react'
import { getAgents } from '../api/client'
import { useWsStore, applyModelBinding } from '../store/wsStore'
import type { AgentStatus } from '../api/types'

export function useAgents(intervalMs = 2000) {
  const [rawAgents, setAgents] = useState<AgentStatus[]>([])
  const [error, setError] = useState<string | null>(null)
  const [backendDown, setBackendDown] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const data = await getAgents()
      setAgents(data)
      setError(null)
      setBackendDown(false)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
      // If fetch itself failed (network error, not HTTP error), backend is down
      if (msg.includes('fetch') || msg.includes('Failed') || msg.includes('NetworkError') || msg.includes('ERR_CONNECTION')) {
        setBackendDown(true)
      }
    }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, intervalMs)
    return () => clearInterval(id)
  }, [refresh, intervalMs])

  // A model hot swap is broadcast over the WebSocket; fold it in so agent
  // titles re-render on the swap rather than up to `intervalMs` later.
  const modelBindings = useWsStore((s) => s.modelBindings)
  const agents = useMemo(
    () => rawAgents.map((a) => applyModelBinding(a, modelBindings)),
    [rawAgents, modelBindings],
  )

  return { agents, error, backendDown, refresh }
}
