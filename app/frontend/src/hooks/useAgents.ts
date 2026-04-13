import { useEffect, useState, useCallback } from 'react'
import { getAgents } from '../api/client'
import type { AgentStatus } from '../api/types'

export function useAgents(intervalMs = 2000) {
  const [agents, setAgents] = useState<AgentStatus[]>([])
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const data = await getAgents()
      setAgents(data)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, intervalMs)
    return () => clearInterval(id)
  }, [refresh, intervalMs])

  return { agents, error, refresh }
}
