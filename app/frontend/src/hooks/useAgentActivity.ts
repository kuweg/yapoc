import { useState, useEffect, useRef } from 'react'
import type { AgentActivityLog } from '../types/agentActivity'
import { useWsStore } from '../store/wsStore'
import { getAgentActivity } from '../agent-status/api/agentStatusClient'
import type { AgentEvent } from '../store/wsStore'

/** Convert raw AgentEvent from the WebSocket to our typed AgentActivityLog */
function eventToActivity(event: AgentEvent): AgentActivityLog | null {
  const agent = event.agent || 'unknown'
  const timestamp = event.timestamp || new Date().toISOString()
  // Raw incoming event type (e.g. 'thinking_delta', 'turn_start') — kept as a
  // plain string; the switch maps it to an AgentActivityLog['type']. (Casting
  // to AgentActivityLog['type'] here was wrong: it narrowed away the input
  // event types, so the cases below failed to type-check.)
  const type = String(event.type)

  // Map the raw event to our typed format
  switch (type) {
    case 'tool_call': {
      const name = String(event.name ?? 'tool')
      const input = event.input ?? {}
      return {
        agent_name: agent,
        timestamp,
        type: 'tool_call',
        content: `${name}(${JSON.stringify(input).slice(0, 500)})`,
        metadata: { name, input },
      }
    }
    case 'tool_result': {
      const name = String(event.name ?? 'tool')
      const result = String(event.result ?? '')
      const isError = Boolean(event.is_error)
      return {
        agent_name: agent,
        timestamp,
        type: isError ? 'error' : 'tool_result',
        content: result.length > 1000 ? result.slice(0, 1000) + '…' : result,
        metadata: { name, isError },
      }
    }
    case 'thinking_delta':
    case 'message_delta': {
      const text = String(event.text ?? '')
      if (!text.trim()) return null
      return {
        agent_name: agent,
        timestamp,
        type: 'llm_output',
        content: text.length > 500 ? text.slice(0, 500) + '…' : text,
      }
    }
    case 'turn_start': {
      const model = String(event.model ?? '')
      return {
        agent_name: agent,
        timestamp,
        type: 'system',
        content: `Turn started${model ? ` (${model})` : ''}`,
      }
    }
    case 'turn_done': {
      const reason = String(event.stop_reason ?? '')
      return {
        agent_name: agent,
        timestamp,
        type: 'system',
        content: `Turn done — ${reason}`,
      }
    }
    case 'error': {
      return {
        agent_name: agent,
        timestamp,
        type: 'error',
        content: String(event.error ?? event.text ?? 'Unknown error'),
      }
    }
    default:
      return null
  }
}

const MAX_ACTIVITY = 200

// Streaming LLM output arrives as many tiny deltas (one per word/token), each
// mapped to an `llm_output` entry. Merge consecutive llm_output entries from the
// same agent into one so the flow panel shows readable messages instead of a
// separate bubble per word. A tool_call / system / turn boundary naturally ends
// the run (different type) and starts a fresh message.
function appendCoalesced(prev: AgentActivityLog[], incoming: AgentActivityLog[]): AgentActivityLog[] {
  const out = prev.slice()
  for (const a of incoming) {
    const last = out[out.length - 1]
    if (last && a.type === 'llm_output' && last.type === 'llm_output' && last.agent_name === a.agent_name) {
      const merged = last.content + a.content
      out[out.length - 1] = {
        ...last,
        content: merged.length > 4000 ? merged.slice(merged.length - 4000) : merged,
        timestamp: a.timestamp,
      }
    } else {
      out.push(a)
    }
  }
  return out
}

/**
 * Hook that provides agent activity events as typed AgentActivityLog[].
 * Sources from both the WebSocket push events and an initial HTTP snapshot.
 * Falls back to mock data when there's no real data.
 */
export function useAgentActivity(agentName: string): AgentActivityLog[] {
  const [activities, setActivities] = useState<AgentActivityLog[]>([])
  // Tracks whether real data has arrived (drives hydratedRef); the boolean
  // value itself isn't read, only the setter is used as a render trigger.
  const [, setHasRealData] = useState(false)
  const hydratedRef = useRef(false)
  const lastLenRef = useRef(0)

  // Subscribe to real-time agent events from WebSocket
  const wsEvents = useWsStore((s) => s.agentEvents[agentName])
  const subscribeAgent = useWsStore((s) => s.subscribeAgent)
  const unsubscribeAgent = useWsStore((s) => s.unsubscribeAgent)

  // Tell the backend to stream THIS agent's events while the consumer (e.g. the
  // agent-flow panel) is mounted. Without this the panel only shows the initial
  // HTTP snapshot and never updates live — agentEvents[agentName] stays empty.
  useEffect(() => {
    if (!agentName) return
    subscribeAgent(agentName)
    return () => unsubscribeAgent(agentName)
  }, [agentName, subscribeAgent, unsubscribeAgent])

  // Hydrate from HTTP snapshot once on mount
  useEffect(() => {
    let cancelled = false
    getAgentActivity(agentName)
      .then((snapshot) => {
        if (cancelled || !snapshot || !Array.isArray(snapshot) || snapshot.length === 0) return
        const converted: AgentActivityLog[] = snapshot
          .map(eventToActivity)
          .filter((a): a is AgentActivityLog => a !== null)
        if (converted.length > 0) {
          setActivities(appendCoalesced([], converted))
          setHasRealData(true)
          hydratedRef.current = true
        }
      })
      .catch(() => { /* ignore — fall back to mock */ })
    return () => { cancelled = true }
  }, [agentName])

  // Process new WebSocket events as they arrive
  useEffect(() => {
    if (!wsEvents || wsEvents.length === 0) return
    const currentLen = wsEvents.length
    if (currentLen <= lastLenRef.current) return
    const newEvents = wsEvents.slice(lastLenRef.current)
    lastLenRef.current = currentLen

    const converted: AgentActivityLog[] = []
    for (const ev of newEvents) {
      const activity = eventToActivity(ev)
      if (activity) converted.push(activity)
    }
    if (converted.length === 0) return

    setHasRealData(true)
    hydratedRef.current = true
    setActivities((prev) => {
      const next = appendCoalesced(prev, converted)
      return next.length > MAX_ACTIVITY ? next.slice(next.length - MAX_ACTIVITY) : next
    })
  }, [wsEvents])

  // Reset when agent changes
  useEffect(() => {
    lastLenRef.current = 0
    hydratedRef.current = false
    setHasRealData(false)
  }, [agentName])

  return activities
}
