import { useEffect, useRef, useState } from 'react'
import { getAgents } from '../api/client'
import { getAgentActivity } from '../agent-status/api/agentStatusClient'
import { createLiveUsage, type LiveUsage } from '../components/liveUsage'
import { useWsStore, type AgentEvent } from '../store/wsStore'

const empty: LiveUsage = { type: 'usage_stats', input_tokens: 0, output_tokens: 0,
  tokens_per_second: 0, context_window: 0, inputKnown: false, estimated: true }

/** Consumes the flow panel's existing agent subscription, including reasoning. */
export function useAgentUsage(agentName: string) {
  const [usage, setUsage] = useState<LiveUsage>(empty)
  const [model, setModel] = useState('')
  const [adapter, setAdapter] = useState('')
  const events = useWsStore(s => s.agentEvents[agentName])
  const binding = useWsStore(s => s.modelBindings[agentName])
  const update = useRef(createLiveUsage())
  const last = useRef<AgentEvent | null>(null)

  const consume = (event: AgentEvent) => {
    if (typeof event.model === 'string') setModel(event.model)
    if (typeof event.adapter === 'string') setAdapter(event.adapter)
    const at = Date.parse(event.timestamp)
    const now = Number.isFinite(at) ? at : Date.now()
    let next: LiveUsage | null = null
    if (event.type === 'turn_start') {
      next = update.current({ type: 'turn_start' }, now)
    } else if (event.type === 'message_delta' || event.type === 'thinking_delta') {
      next = update.current({ type: event.type === 'message_delta' ? 'text' : 'thinking', text: String(event.text ?? '') }, now)
    } else if (event.type === 'usage_stats') {
      const fields = ['input_tokens', 'output_tokens', 'tokens_per_second', 'context_window'] as const
      if (fields.every(key => typeof event[key] === 'number' && Number.isFinite(event[key]) && Number(event[key]) >= 0)) {
        next = update.current({ type: 'usage_stats', input_tokens: Number(event.input_tokens),
          output_tokens: Number(event.output_tokens), tokens_per_second: Number(event.tokens_per_second),
          context_window: Number(event.context_window) }, now)
      }
    } else if (event.type === 'tool_call') {
      next = update.current({ type: 'tool_start', name: String(event.name ?? ''), input: {} }, now)
    }
    if (next) setUsage(next)
  }

  useEffect(() => {
    let cancelled = false
    update.current = createLiveUsage()
    last.current = null
    setUsage(empty)
    setModel('')
    setAdapter('')
    getAgents().then(agents => {
      if (cancelled || last.current) return
      const agent = agents.find(a => a.name === agentName)
      if (agent) { setModel(agent.model); setAdapter(agent.adapter ?? '') }
    }).catch(() => {})
    getAgentActivity(agentName).then(snapshot => {
      // A late snapshot must not overwrite newer WebSocket metrics.
      if (cancelled || last.current) return
      for (const event of snapshot) consume(event)
    }).catch(() => {})
    return () => { cancelled = true }
  }, [agentName])

  useEffect(() => {
    if (!events?.length) return
    const index = last.current ? events.indexOf(last.current) : -1
    for (const event of events.slice(index + 1)) consume(event)
    last.current = events[events.length - 1]
  }, [events])

  useEffect(() => {
    if (binding) { setModel(binding.model); setAdapter(binding.adapter) }
  }, [binding])

  return { usage, model, adapter }
}
