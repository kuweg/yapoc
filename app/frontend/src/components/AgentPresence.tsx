import { useEffect, useRef } from 'react'
import { useWsStore, type AgentEvent } from '../store/wsStore'
import { startAsciiWave, ASCII_WAVE_FRAMES } from './spinner'
import { AgentAvatar, getAgentColor, getAgentDisplayName } from '../lib/agentIdentity'

export type AgentPresence = 'idle' | 'thinking' | 'calling-tool' | 'streaming' | 'waiting' | 'offline'

const RECENT_MS = 15_000
/** Freshness window for heartbeat activity events (used by the master progress pill). */
export const HEARTBEAT_FRESH_MS = 45_000

const PRESENCE_LABEL: Record<AgentPresence, string> = {
  idle: 'idle',
  thinking: 'thinking',
  'calling-tool': 'tool',
  streaming: 'streaming',
  waiting: 'waiting',
  offline: 'offline',
}

const ACTIVE_STATES: AgentPresence[] = ['thinking', 'calling-tool', 'streaming']

/**
 * Derive a presence state from the coarse status poll (useAgents, ~2s) plus the
 * real-time event buffer (wsStore.agentEvents — live for subscribed agents).
 * Fresh live events win; otherwise fall back to the polled status.
 */
export function deriveAgentPresence(status: string | undefined, events: AgentEvent[] | undefined): AgentPresence {
  const now = Date.now()
  const recent = (events || []).filter((e) => {
    const ts = e.timestamp ? new Date(e.timestamp as string).getTime() : 0
    return now - ts < RECENT_MS
  })
  const last = recent[recent.length - 1]
  if (last) {
    if (last.type === 'thinking_delta') return 'thinking'
    if (last.type === 'tool_call') return 'calling-tool'
    if (last.type === 'message_delta') return 'streaming'
    // tool_result / turn_done / turn_start / error → settled; fall through to status
  }
  const s = (status || 'idle').toLowerCase()
  if (s === 'running' || s === 'busy' || s === 'spawning') return 'waiting'
  if (s === 'terminated') return 'offline'
  return 'idle'
}

/** Inline ASCII-wave spinner (reuses spinner.ts), reduced-motion aware. */
function PresenceSpinner({ color }: { color: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      el.textContent = ASCII_WAVE_FRAMES[2]
      return
    }
    const handle = startAsciiWave(el, 120)
    return () => handle.stop()
  }, [])
  return <span ref={ref} className="font-mono text-[12px] leading-none w-5 inline-block" style={{ color }} aria-hidden />
}

/**
 * Inline live-presence indicator for an agent: optional avatar + optional name,
 * then either an animated spinner (thinking / tool / streaming) or a static
 * state dot + label. Pass `status` from the parent's single useAgents() poll so
 * this only subscribes to the cheap per-agent event selector (no extra polling).
 */
export function AgentPresenceIndicator({
  name,
  status,
  showAvatar = false,
  showName = false,
}: {
  name: string
  status?: string
  showAvatar?: boolean
  showName?: boolean
}) {
  const events = useWsStore((s) => s.agentEvents[name])
  const presence = deriveAgentPresence(status, events)
  const color = getAgentColor(name)
  const active = ACTIVE_STATES.includes(presence)
  return (
    <span
      className="inline-flex items-center gap-1.5 min-w-0"
      title={`${getAgentDisplayName(name)} — ${PRESENCE_LABEL[presence]}`}
    >
      {showAvatar && <AgentAvatar name={name} size={16} />}
      {showName && (
        <span className="text-xs font-semibold truncate" style={{ color }}>
          {getAgentDisplayName(name)}
        </span>
      )}
      {active ? (
        <PresenceSpinner color={color} />
      ) : (
        <span
          className={`inline-block w-1.5 h-1.5 rounded-full flex-shrink-0 ${presence === 'waiting' ? 'animate-pulse' : ''}`}
          style={{ backgroundColor: presence === 'offline' ? '#6b7280' : presence === 'waiting' ? color : '#34d399' }}
        />
      )}
      <span className="text-[12px] uppercase tracking-wide" style={{ color: active ? color : '#71717a' }}>
        {PRESENCE_LABEL[presence]}
      </span>
    </span>
  )
}
