import { useEffect, useState, useCallback } from 'react'
import { getAgents } from '../api/client'
import type { AgentStatus } from '../api/types'

export function useAgents(intervalMs = 2000) {
  const [agents, setAgents] = useState<AgentStatus[]>([])
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

  return { agents, error, backendDown, refresh }
}
