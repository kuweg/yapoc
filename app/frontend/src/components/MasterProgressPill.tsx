import { useEffect, useState } from 'react'
import { useWsStore } from '../store/wsStore'
import { HEARTBEAT_FRESH_MS } from './AgentPresence'

interface HeartbeatInfo {
  waiting_on: string[]
  status: string
  since_s: number
  rawTs: number
}

/** Pull the freshest master heartbeat from the agent-event buffer. A heartbeat
 *  carries {type:'heartbeat', waiting_on:[...], since_s, timestamp}. If the most
 *  recent event is a fresh heartbeat with waiting_on entries, master is blocked
 *  waiting on sub-agents. */
function latestHeartbeat(events: Array<{ type?: unknown; waiting_on?: unknown; since_s?: unknown; status?: unknown; timestamp?: unknown }>): HeartbeatInfo | null {
  let best: HeartbeatInfo | null = null
  for (const e of events ?? []) {
    if (e.type !== 'heartbeat') continue
    const ts = e.timestamp ? new Date(String(e.timestamp)).getTime() : 0
    if (!ts || Number.isNaN(ts)) continue
    if (Date.now() - ts > HEARTBEAT_FRESH_MS) continue
    const waitingOn = Array.isArray(e.waiting_on) ? e.waiting_on.map(String) : []
    if (waitingOn.length === 0) continue
    if (!best || ts > best.rawTs) {
      best = { waiting_on: waitingOn, status: String(e.status ?? ''), since_s: Number(e.since_s ?? 0), rawTs: ts }
    }
  }
  return best
}

function fmtSince(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`
  return `${Math.floor(seconds / 60)}m${Math.floor(seconds % 60)}s`
}

/** Persistent top-bar widget showing whether master is idle or waiting on
 *  specific agents. Subscribes to master's live agent-event buffer. */
export function MasterProgressPill() {
  const events = useWsStore((s) => s.agentEvents['master'])
  const [, forceTick] = useState(0)
  const heartbeat = latestHeartbeat(events)

  // Re-render periodically while we're mid-wait so the elapsed timer ticks.
  useEffect(() => {
    const hb = heartbeat
    if (!hb) return
    const id = setInterval(() => forceTick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [!!heartbeat, heartbeat?.rawTs])

  if (!heartbeat) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-1 text-[11px] font-mono leading-none text-zinc-500 bg-zinc-800/60 border border-zinc-800 rounded-full flex-shrink-0 whitespace-nowrap" title="master is idle">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 flex-shrink-0" />
        master idle
      </span>
    )
  }

  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-1 text-[11px] font-mono leading-none text-amber-300 bg-[#2a2a1a]/70 border border-[#FFB633]/40 rounded-full flex-shrink-0 whitespace-nowrap"
      title={`master ${heartbeat.status} for ${fmtSince(heartbeat.since_s)}`}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-[#FFB633] animate-pulse flex-shrink-0" />
      master ⏳ {heartbeat.waiting_on.join(', ')} {fmtSince(heartbeat.since_s)}
    </span>
  )
}
