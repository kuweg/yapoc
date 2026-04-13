import { useEffect, useRef, useCallback } from 'react'
import { useAgentStore } from '../store/agentStore'
import type { AgentStatus, AgentEvent } from '../types'

function synthesizeEvents(prev: AgentStatus[], next: AgentStatus[]): AgentEvent[] {
  const prevMap = new Map(prev.map((a) => [a.name, a.state]))
  const events: AgentEvent[] = []
  for (const agent of next) {
    const prevState = prevMap.get(agent.name)
    if (prevState === undefined || prevState === agent.state) continue
    let event_type = 'status_changed'
    let level: 'info' | 'warning' | 'error' = 'info'
    if (agent.state === 'running') event_type = 'task_assigned'
    else if (agent.state === 'idle' && prevState === 'running') event_type = 'task_completed'
    else if (agent.state === 'error') { event_type = 'task_failed'; level = 'error' }
    else if (agent.health !== 'ok') level = 'warning'
    events.push({
      id: crypto.randomUUID(),
      timestamp: new Date().toISOString(),
      agent_name: agent.name,
      event_type,
      message: `${agent.name}: ${prevState || 'unknown'} → ${agent.state}`,
      level,
    })
  }
  return events
}

export function useAgentPolling(intervalMs = 2000) {
  const { setAgents, setConnectionStatus, setLastRefreshed, pushEvent, selectedAgentName, setAgentDetail, setDetailLoading } = useAgentStore()
  const prevAgentsRef = useRef<AgentStatus[]>([])
  const failCountRef = useRef(0)
  const backoffRef = useRef(intervalMs)
  const timerId = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchAgents = useCallback(async () => {
    if (document.visibilityState === 'hidden') return
    try {
      const res = await fetch('/api/agents')
      if (!res.ok) throw new Error(`${res.status}`)
      const data: AgentStatus[] = await res.json()
      const events = synthesizeEvents(prevAgentsRef.current, data)
      prevAgentsRef.current = data
      setAgents(data)
      setLastRefreshed()
      for (const ev of events) pushEvent(ev)
      failCountRef.current = 0
      backoffRef.current = intervalMs
      setConnectionStatus('connected')
    } catch {
      failCountRef.current++
      if (failCountRef.current >= 3) setConnectionStatus('disconnected')
      else setConnectionStatus('reconnecting')
      backoffRef.current = Math.min(backoffRef.current * 2, 60000)
    }
  }, [setAgents, setConnectionStatus, setLastRefreshed, pushEvent, intervalMs])

  const fetchDetail = useCallback(async (name: string) => {
    setDetailLoading(true)
    try {
      const res = await fetch(`/api/agents/${name}`)
      if (!res.ok) throw new Error(`${res.status}`)
      const data = await res.json()
      setAgentDetail(data)
    } catch {
      setAgentDetail(null)
    } finally {
      setDetailLoading(false)
    }
  }, [setAgentDetail, setDetailLoading])

  // Poll agent list
  useEffect(() => {
    let active = true
    const jitter = () => Math.random() * 500
    async function loop() {
      if (!active) return
      await fetchAgents()
      timerId.current = setTimeout(loop, backoffRef.current + jitter())
    }
    loop()
    const onVisible = () => { if (document.visibilityState === 'visible') loop() }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      active = false
      if (timerId.current) clearTimeout(timerId.current)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [fetchAgents])

  // Poll detail when an agent is selected
  useEffect(() => {
    if (!selectedAgentName) return
    let active = true
    async function loop() {
      if (!active || !selectedAgentName) return
      await fetchDetail(selectedAgentName)
      setTimeout(loop, 5000)
    }
    loop()
    return () => { active = false }
  }, [selectedAgentName, fetchDetail])
}
