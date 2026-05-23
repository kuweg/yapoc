import { useEffect, useMemo, useRef, useState } from 'react'
import { getAgentActivity } from '../agent-status/api/agentStatusClient'
import { useWsStore, type AgentEvent } from '../store/wsStore'

// Stable empty-events reference for the wsStore selector when this agent
// has no buffered activity yet — avoids a render loop.
const EMPTY_EVENTS: AgentEvent[] = []

interface Props {
  agentName: string
  state: string
  onClose: () => void
}

type Tab = 'live' | 'output'

interface OutputData {
  content: string
  total_lines?: number
}

/** Flatten the structured per-agent event stream into a text view so this
 *  drawer keeps its scrolling-text feel — but is now driven by the WS push
 *  pipeline instead of polling LIVE.MD. */
function eventsToText(events: AgentEvent[]): string {
  const out: string[] = []
  for (const ev of events) {
    const ts = (ev.timestamp || '').slice(11, 19)
    switch (ev.type) {
      case 'turn_start':
        out.push(`\n[${ts}] ── turn ${ev.turn} (${ev.model}) ──`)
        break
      case 'turn_done':
        out.push(`[${ts}] ── turn ${ev.turn} done (${ev.stop_reason}, ${ev.n_tool_calls} tools) ──\n`)
        break
      case 'thinking_delta':
        out.push(String(ev.text ?? ''))
        break
      case 'message_delta':
        out.push(String(ev.text ?? ''))
        break
      case 'tool_call': {
        const input = JSON.stringify(ev.input ?? {})
        out.push(`\n[${ts}] → ${ev.name} ${input.length > 200 ? input.slice(0, 200) + '…' : input}\n`)
        break
      }
      case 'tool_result': {
        const r = String(ev.result ?? '')
        const mark = ev.is_error ? '✗' : '✓'
        out.push(`[${ts}] ${mark} ${ev.name} ${r.length > 240 ? r.slice(0, 240) + '…' : r}\n`)
        break
      }
      default:
        // ignore unknown event types in this text view
        break
    }
  }
  return out.join('')
}

export function AgentLogDrawer({ agentName, state, onClose }: Props) {
  const [tab, setTab] = useState<Tab>('live')
  const [outputData, setOutputData] = useState<OutputData | null>(null)
  const [loading, setLoading] = useState(false)
  const liveRef = useRef<HTMLPreElement>(null)
  const outputRef = useRef<HTMLPreElement>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  // Keep a ref so the interval callback always reads the current tab
  const tabRef = useRef(tab)
  useEffect(() => { tabRef.current = tab }, [tab])

  const isRunning = state === 'running' || state === 'spawning'

  const events = useWsStore((s) => s.agentEvents[agentName] ?? EMPTY_EVENTS)
  const setAgentEvents = useWsStore((s) => s.setAgentEvents)
  const subscribeAgent = useWsStore((s) => s.subscribeAgent)
  const unsubscribeAgent = useWsStore((s) => s.unsubscribeAgent)
  const liveContent = useMemo(() => eventsToText(events), [events])

  async function fetchOutput() {
    setLoading(true)
    try {
      const res = await fetch(`/api/agents/${agentName}/output?lines=300`)
      if (!res.ok) return
      const data = await res.json()
      setOutputData(data)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  // Hydrate the live activity buffer and subscribe via WS.
  useEffect(() => {
    let cancelled = false
    getAgentActivity(agentName)
      .then((snapshot) => {
        if (cancelled) return
        setAgentEvents(agentName, snapshot as AgentEvent[])
      })
      .catch(() => { /* WS push will still populate */ })
    subscribeAgent(agentName)
    return () => {
      cancelled = true
      unsubscribeAgent(agentName)
    }
  }, [agentName, setAgentEvents, subscribeAgent, unsubscribeAgent])

  // Logs (subprocess stdout/stderr) still polls — separate stream from
  // the per-agent activity feed.
  useEffect(() => {
    fetchOutput()
    const ms = isRunning ? 1000 : 3000
    intervalRef.current = setInterval(() => {
      if (tabRef.current === 'output') fetchOutput()
    }, ms)

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentName, isRunning])

  // Auto-scroll live view
  useEffect(() => {
    if (tab === 'live' && liveRef.current) {
      liveRef.current.scrollTop = liveRef.current.scrollHeight
    }
  }, [liveContent, tab])

  // Auto-scroll output view
  useEffect(() => {
    if (tab === 'output' && outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight
    }
  }, [outputData, tab])

  // Refetch on tab switch
  useEffect(() => {
    if (tab === 'output') fetchOutput()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center"
      onClick={onClose}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60" />

      {/* Panel */}
      <div
        className="relative w-full max-w-3xl h-[70vh] bg-zinc-900 border border-zinc-700 rounded-t-xl sm:rounded-xl
          flex flex-col overflow-hidden shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center gap-3 px-4 py-2.5 border-b border-zinc-700 flex-shrink-0">
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <span className={`h-2 w-2 rounded-full flex-shrink-0 ${
              isRunning ? 'bg-amber-400 animate-pulse' : 'bg-emerald-400'
            }`} />
            <span className="font-mono text-sm text-zinc-100 font-semibold">{agentName}</span>
            <span className="text-xs text-zinc-500">{state}</span>
          </div>

          {/* Tabs */}
          <div className="flex gap-1 bg-zinc-800 rounded-md p-0.5">
            <button
              onClick={() => setTab('live')}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                tab === 'live' ? 'bg-zinc-700 text-zinc-100' : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              {isRunning ? '● Live' : 'Last Output'}
            </button>
            <button
              onClick={() => setTab('output')}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                tab === 'output' ? 'bg-zinc-700 text-zinc-100' : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              Logs
              {outputData?.total_lines != null && (
                <span className="ml-1 text-zinc-600">{outputData.total_lines}</span>
              )}
            </button>
          </div>

          <button
            onClick={onClose}
            className="ml-2 text-zinc-500 hover:text-zinc-200 text-lg leading-none transition-colors"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden">
          {tab === 'live' && (
            <div className="h-full flex flex-col">
              {!liveContent && !isRunning && (
                <div className="flex-1 flex items-center justify-center text-sm text-zinc-600">
                  Agent is idle — no current output
                </div>
              )}
              {!liveContent && isRunning && (
                <div className="flex-1 flex items-center justify-center text-sm text-zinc-600">
                  <span className="animate-pulse">Waiting for model output…</span>
                </div>
              )}
              {liveContent && (
                <pre
                  ref={liveRef}
                  className="flex-1 overflow-y-auto px-4 py-3 text-xs font-mono text-zinc-200
                    whitespace-pre-wrap break-words leading-relaxed"
                >
                  {liveContent}
                  {isRunning && <span className="inline-block w-1.5 h-3.5 bg-amber-400 animate-pulse ml-0.5 align-middle" />}
                </pre>
              )}
            </div>
          )}

          {tab === 'output' && (
            <div className="h-full flex flex-col">
              {loading && !outputData && (
                <div className="flex-1 flex items-center justify-center text-sm text-zinc-600">
                  Loading…
                </div>
              )}
              {outputData && !outputData.content && (
                <div className="flex-1 flex items-center justify-center text-sm text-zinc-600">
                  No log output yet
                </div>
              )}
              {outputData?.content && (
                <pre
                  ref={outputRef}
                  className="flex-1 overflow-y-auto px-4 py-3 text-xs font-mono text-zinc-400
                    whitespace-pre-wrap break-words leading-relaxed"
                >
                  {outputData.content}
                </pre>
              )}
            </div>
          )}
        </div>

        {/* Footer status bar */}
        <div className="flex items-center gap-3 px-4 py-1.5 border-t border-zinc-800 text-[10px] text-zinc-600 flex-shrink-0">
          {isRunning && (
            <span className="text-amber-400/70 animate-pulse">● generating</span>
          )}
          {outputData && (
            <span>log: {outputData.total_lines ?? 0} lines</span>
          )}
          <div className="flex-1" />
          <span>auto-refresh {isRunning ? '1s' : '3s'}</span>
        </div>
      </div>
    </div>
  )
}
