import { useEffect, useMemo, useState } from 'react'
import { getAgentActivity, getAgentFiles, readAgentFile, type AgentActivityEvent } from '../../api/agentStatusClient'
import { useWsStore, type AgentEvent } from '../../../store/wsStore'

// Stable empty array so a missing-agent selector doesn't return a fresh
// reference on every render (which would trigger Zustand re-renders in a
// loop).
const EMPTY_EVENTS: AgentEvent[] = []

interface Props {
  agentName: string
}

const FILE_COLORS: Record<string, string> = {
  'PROMPT.MD': 'border-blue-500/40 text-blue-400',
  'CONFIG.yaml': 'border-amber-500/40 text-amber-400',
  'MEMORY.MD': 'border-emerald-500/40 text-emerald-400',
  'NOTES.MD': 'border-purple-500/40 text-purple-400',
  'HEALTH.MD': 'border-red-500/40 text-red-400',
  'TASK.MD':   'border-cyan-500/40 text-cyan-400',
  'CRASH.MD':  'border-red-600/40 text-red-500',
}

const LIVE_TAB = 'Live'
const LIVE_TAB_COLOR = 'border-lime-500/40 text-lime-400'

// Token-level deltas accumulate too fast to render individually; group
// them into a single per-turn block keyed by turn index.
interface TurnBlock {
  kind: 'turn'
  turn: number
  model: string
  thinking: string
  text: string
  closed: boolean
}

interface MilestoneEntry {
  kind: 'milestone'
  event: AgentEvent
}

type RenderEntry = TurnBlock | MilestoneEntry

function buildRenderEntries(events: AgentEvent[]): RenderEntry[] {
  const out: RenderEntry[] = []
  // turn index → index into `out`
  const turnIdx = new Map<number, number>()

  const getOrCreateTurn = (turn: number, model: string): TurnBlock => {
    const existing = turnIdx.get(turn)
    if (existing !== undefined) {
      const block = out[existing]
      if (block.kind === 'turn') return block
    }
    const fresh: TurnBlock = {
      kind: 'turn',
      turn,
      model,
      thinking: '',
      text: '',
      closed: false,
    }
    turnIdx.set(turn, out.length)
    out.push(fresh)
    return fresh
  }

  // Track which turn deltas land under when no explicit turn_start has
  // arrived yet (snapshot may start mid-turn). Use a synthetic -1.
  let activeTurn = -1
  let activeModel = '?'

  for (const ev of events) {
    switch (ev.type) {
      case 'turn_start': {
        const turn = typeof ev.turn === 'number' ? (ev.turn as number) : activeTurn + 1
        const model = typeof ev.model === 'string' ? (ev.model as string) : activeModel
        activeTurn = turn
        activeModel = model
        getOrCreateTurn(turn, model)
        break
      }
      case 'turn_done': {
        const turn = typeof ev.turn === 'number' ? (ev.turn as number) : activeTurn
        const block = turnIdx.has(turn) ? (out[turnIdx.get(turn)!] as TurnBlock) : null
        if (block) block.closed = true
        break
      }
      case 'thinking_delta': {
        const block = getOrCreateTurn(activeTurn, activeModel)
        block.thinking += String(ev.text ?? '')
        break
      }
      case 'message_delta': {
        const block = getOrCreateTurn(activeTurn, activeModel)
        block.text += String(ev.text ?? '')
        break
      }
      case 'tool_call':
      case 'tool_result':
      default:
        out.push({ kind: 'milestone', event: ev })
        break
    }
  }
  return out
}

function MilestoneLine({ event }: { event: AgentEvent }) {
  const ts = (event.timestamp || '').slice(11, 19)
  const t = event.type
  if (t === 'tool_call') {
    const name = String(event.name ?? '?')
    const input = JSON.stringify(event.input ?? {})
    return (
      <div className="text-cyan-400">
        <span className="text-[#484F58]">{ts}</span>{' '}
        <span className="text-cyan-300">→ {name}</span>
        <span className="text-[#8B949E]"> {input.length > 200 ? input.slice(0, 200) + '…' : input}</span>
      </div>
    )
  }
  if (t === 'tool_result') {
    const name = String(event.name ?? '?')
    const isErr = Boolean(event.is_error)
    const result = String(event.result ?? '')
    return (
      <div className={isErr ? 'text-red-400' : 'text-emerald-400'}>
        <span className="text-[#484F58]">{ts}</span>{' '}
        <span>{isErr ? '✗' : '✓'} {name}</span>
        <span className="text-[#8B949E]"> {result.length > 240 ? result.slice(0, 240) + '…' : result}</span>
      </div>
    )
  }
  return (
    <div className="text-[#8B949E]">
      <span className="text-[#484F58]">{ts}</span>{' '}
      <span>{t}</span>
    </div>
  )
}

function TurnGroup({ block, expanded, onToggle, isLive }: { block: TurnBlock; expanded: boolean; onToggle: () => void; isLive: boolean }) {
  const hasContent = block.thinking.length > 0 || block.text.length > 0
  // Synthetic turn (-1) is what we get for deltas that arrived before any
  // turn_start was observed — i.e. the hydration snapshot caught a turn
  // mid-flight. Label it as "Earlier activity" so users don't see a weird
  // negative turn number.
  const isSynthetic = block.turn < 0
  const label = isSynthetic ? 'Earlier activity' : `Turn ${block.turn}`
  return (
    <div className="border-l-2 border-lime-500/40 pl-2 my-1">
      <button
        type="button"
        onClick={onToggle}
        className="text-[11px] text-lime-300 hover:text-lime-200 font-mono"
      >
        <span className="text-[#484F58] mr-1">{expanded ? '▾' : '▸'}</span>
        {label}
        {!isSynthetic && <span className="text-[#484F58]"> ({block.model})</span>}
        {' '}
        {block.closed
          ? <span className="text-[#484F58]">done</span>
          : isLive
            ? <span className="text-amber-400">streaming…</span>
            : <span className="text-[#484F58]">snapshot</span>}
        {!hasContent && <span className="text-[#484F58]"> (no deltas)</span>}
      </button>
      {expanded && hasContent && (
        <div className="mt-1 space-y-1">
          {block.thinking && (
            <pre className="text-[11px] text-[#6E7681] whitespace-pre-wrap break-words">[thinking] {block.thinking}</pre>
          )}
          {block.text && (
            <pre className="text-[11px] text-[#C9D1D9] whitespace-pre-wrap break-words">{block.text}</pre>
          )}
        </div>
      )}
    </div>
  )
}

function LiveFeed({ agentName }: { agentName: string }) {
  const events = useWsStore((s) => s.agentEvents[agentName] ?? EMPTY_EVENTS)
  const connected = useWsStore((s) => s.connected)
  const setAgentEvents = useWsStore((s) => s.setAgentEvents)
  const subscribeAgent = useWsStore((s) => s.subscribeAgent)
  const unsubscribeAgent = useWsStore((s) => s.unsubscribeAgent)
  const [hydrated, setHydrated] = useState(false)
  const [expandedTurns, setExpandedTurns] = useState<Set<number>>(new Set())

  useEffect(() => {
    let cancelled = false
    setHydrated(false)
    getAgentActivity(agentName)
      .then((snapshot: AgentActivityEvent[]) => {
        if (cancelled) return
        setAgentEvents(agentName, snapshot as AgentEvent[])
        setHydrated(true)
      })
      .catch(() => {
        if (cancelled) return
        // Hydration failure is non-fatal — WS push will still populate.
        setHydrated(true)
      })
    subscribeAgent(agentName)
    return () => {
      cancelled = true
      unsubscribeAgent(agentName)
    }
  }, [agentName, setAgentEvents, subscribeAgent, unsubscribeAgent])

  const entries = useMemo(() => buildRenderEntries(events), [events])

  // Auto-collapse old turns: keep only the most recent open by default.
  // Users can manually expand any turn block.
  const latestTurn = useMemo(() => {
    let max = -1
    for (const e of entries) {
      if (e.kind === 'turn' && e.turn > max) max = e.turn
    }
    return max
  }, [entries])

  const toggleTurn = (turn: number) =>
    setExpandedTurns((prev) => {
      const next = new Set(prev)
      if (next.has(turn)) next.delete(turn)
      else next.add(turn)
      return next
    })

  return (
    <div className="max-h-60 overflow-auto p-3 space-y-1">
      {!hydrated && <div className="text-[#484F58] italic text-[11px]">Hydrating…</div>}
      {hydrated && entries.length === 0 && (
        <div className="text-[#484F58] italic text-[11px]">(no activity yet)</div>
      )}
      {entries.map((entry, idx) => {
        if (entry.kind === 'milestone') {
          return (
            <div key={idx} className="text-[11px] font-mono">
              <MilestoneLine event={entry.event} />
            </div>
          )
        }
        const expanded = expandedTurns.has(entry.turn) || entry.turn === latestTurn
        return (
          <TurnGroup
            key={`turn-${entry.turn}`}
            block={entry}
            expanded={expanded}
            onToggle={() => toggleTurn(entry.turn)}
            isLive={connected}
          />
        )
      })}
    </div>
  )
}

export function AgentFileViewer({ agentName }: Props) {
  const [files, setFiles] = useState<string[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [content, setContent] = useState<string>('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    getAgentFiles(agentName)
      .then(setFiles)
      .catch(() => setFiles([]))
    setSelected(null)
    setContent('')
  }, [agentName])

  useEffect(() => {
    if (!selected || selected === LIVE_TAB) {
      setContent('')
      return
    }
    setLoading(true)
    readAgentFile(agentName, selected)
      .then(setContent)
      .catch((e) => setContent(`Error: ${e instanceof Error ? e.message : String(e)}`))
      .finally(() => setLoading(false))
  }, [agentName, selected])

  // Live tab is always offered; static files are filtered to those that
  // exist on disk. LIVE.MD is no longer written, so drop it if present.
  const fileTabs = files.filter((f) => f !== 'LIVE.MD')

  return (
    <div>
      {/* Tabs */}
      <div className="flex flex-wrap gap-1.5 mb-2">
        <button
          key={LIVE_TAB}
          onClick={() => setSelected((s) => (s === LIVE_TAB ? null : LIVE_TAB))}
          className={`px-2 py-0.5 text-[11px] font-mono rounded border transition-colors ${
            selected === LIVE_TAB
              ? `${LIVE_TAB_COLOR} bg-[#21262D]`
              : 'border-[#30363D] text-[#484F58] hover:text-[#8B949E] hover:border-[#484F58]'
          }`}
        >
          {LIVE_TAB}
        </button>
        {fileTabs.map((f) => {
          const color = FILE_COLORS[f] || 'border-[#30363D] text-[#8B949E]'
          const isActive = selected === f
          return (
            <button
              key={f}
              onClick={() => setSelected((s) => (s === f ? null : f))}
              className={`px-2 py-0.5 text-[11px] font-mono rounded border transition-colors ${
                isActive
                  ? `${color} bg-[#21262D]`
                  : 'border-[#30363D] text-[#484F58] hover:text-[#8B949E] hover:border-[#484F58]'
              }`}
            >
              {f}
            </button>
          )
        })}
      </div>

      {/* Content */}
      {selected === LIVE_TAB && (
        <div className="bg-[#0D1117] border border-[#21262D] rounded-lg overflow-hidden">
          <div className="flex items-center justify-between px-3 py-1.5 border-b border-[#21262D]">
            <span className="text-[11px] font-mono text-lime-400">Live activity (push)</span>
          </div>
          <LiveFeed agentName={agentName} />
        </div>
      )}
      {selected && selected !== LIVE_TAB && (
        <div className="bg-[#0D1117] border border-[#21262D] rounded-lg overflow-hidden">
          <div className="flex items-center justify-between px-3 py-1.5 border-b border-[#21262D]">
            <span className="text-[11px] font-mono text-[#8B949E]">{selected}</span>
            <button
              onClick={() => {
                setLoading(true)
                readAgentFile(agentName, selected)
                  .then(setContent)
                  .catch((e) => setContent(`Error: ${e instanceof Error ? e.message : String(e)}`))
                  .finally(() => setLoading(false))
              }}
              className="text-[10px] text-[#484F58] hover:text-[#8B949E] transition-colors"
            >
              {loading ? 'Loading...' : 'Refresh'}
            </button>
          </div>
          <div className="max-h-60 overflow-auto p-3">
            <pre className="text-[11px] font-mono text-[#8B949E] whitespace-pre-wrap break-words leading-relaxed">
              {content || <span className="text-[#484F58] italic">(empty)</span>}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}
