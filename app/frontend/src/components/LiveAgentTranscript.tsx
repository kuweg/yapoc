/** Session-scoped background output rendered with the chat's normal parts. */
import { useEffect, useMemo, useState } from 'react'
import { useWsStore } from '../store/wsStore'
import type { AgentEvent } from '../store/wsStore'
import { getAgentActivity } from '../agent-status/api/agentStatusClient'
import type { TaskPart } from '../api/types'

export function eventsToChatParts(events: AgentEvent[], sinceIso: string, sessionId: string): TaskPart[] {
  const since = Date.parse(sinceIso)
  const parts: TaskPart[] = []
  const seen = new Set<string>()
  let boundary = true
  for (const event of events) {
    if (event.session_id !== sessionId || Date.parse(event.timestamp) < since) continue
    const key = JSON.stringify(event)
    if (seen.has(key)) continue
    seen.add(key)
    const text = String(event.text ?? '')
    const last = parts[parts.length - 1]
    if (event.type === 'message_delta') {
      if (!boundary && last?.kind === 'text') last.text += text
      else parts.push({ kind: 'text', text })
      boundary = false
    } else if (event.type === 'thinking_delta') {
      if (!boundary && last?.kind === 'thinking' && !last.done) last.text += text
      else parts.push({ kind: 'thinking', id: key, text, done: false })
      boundary = false
    } else if (event.type === 'tool_call') {
      parts.push({ kind: 'tool', id: key, name: String(event.name), input: (event.input ?? {}) as Record<string, unknown>, done: false })
      boundary = true
    } else if (event.type === 'tool_result') {
      for (let i = parts.length - 1; i >= 0; i--) {
        const part = parts[i]
        if (part.kind === 'tool' && !part.done && part.name === event.name) {
          const result = String(event.result ?? '')
          parts[i] = { ...part, done: true, result, isError: Boolean(event.is_error) }
          if (part.name === 'render_mermaid' && !event.is_error) {
            try {
              const payload: unknown = JSON.parse(result)
              if (
                payload &&
                typeof payload === 'object' &&
                !Array.isArray(payload) &&
                (payload as Record<string, unknown>).type === 'mermaid' &&
                typeof (payload as Record<string, unknown>).source === 'string'
              ) {
                parts[i] = { kind: 'mermaid', source: (payload as Record<string, unknown>).source as string }
              }
            } catch { /* retain the tool output */ }
          } else if (part.name === 'render_chart' && !event.is_error) {
            try {
              const option = JSON.parse(result)
              if (option && typeof option === 'object' && !Array.isArray(option)) parts[i] = { kind: 'chart', option }
            } catch { /* retain the tool output */ }
          } else if (part.name === 'render_calendar' && !event.is_error) {
            try {
              const payload: unknown = JSON.parse(result)
              if (
                payload &&
                typeof payload === 'object' &&
                !Array.isArray(payload) &&
                (payload as Record<string, unknown>).type === 'calendar' &&
                Array.isArray((payload as Record<string, unknown>).events)
              ) {
                parts[i] = {
                  kind: 'calendar',
                  events: (payload as Record<string, unknown>).events as Array<{
                    summary: string
                    start: string
                    end: string
                    location?: string
                    description?: string
                  }>,
                  weekStart:
                    typeof (payload as Record<string, unknown>).week_start === 'string'
                      ? ((payload as Record<string, unknown>).week_start as string)
                      : undefined,
                }
              }
            } catch { /* retain the tool output */ }
          }
          break
        }
      }
      boundary = true
    } else if (event.type === 'turn_done' || event.type === 'turn_start') {
      for (const part of parts) if (part.kind === 'thinking') part.done = true
      boundary = true
    }
  }
  return parts
}

export function useLiveAgentParts(agentName: string, sinceIso?: string, sessionId?: string): TaskPart[] {
  const events = useWsStore((s) => s.agentEvents[agentName])
  const connected = useWsStore((s) => s.connected)
  const subscribe = useWsStore((s) => s.subscribeAgent)
  const unsubscribe = useWsStore((s) => s.unsubscribeAgent)
  const [snapshot, setSnapshot] = useState<AgentEvent[]>([])
  useEffect(() => {
    subscribe(agentName)
    return () => unsubscribe(agentName)
  }, [agentName, subscribe, unsubscribe])
  useEffect(() => {
    let cancelled = false
    setSnapshot([])
    if (sinceIso && sessionId) getAgentActivity(agentName).then((data) => {
      if (!cancelled) setSnapshot(data)
    }).catch(() => { /* live events still work */ })
    return () => { cancelled = true }
  }, [agentName, sinceIso, sessionId, connected])
  return useMemo(() => {
    if (!sinceIso || !sessionId) return []
    const merged = [...snapshot, ...(events ?? [])].sort((a, b) => a.timestamp.localeCompare(b.timestamp))
    return eventsToChatParts(merged, sinceIso, sessionId)
  }, [snapshot, events, sinceIso, sessionId])
}
