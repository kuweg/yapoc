import { useEffect, useRef, useState } from 'react'
import type { AgentStatus } from '../api/types'
import { useAgentChatStore } from '../store/agentChatStore'
import { killAgent } from '../api/client'
import { AgentAvatar, getAgentDisplayName } from '../lib/agentIdentity'
import { AgentPresenceIndicator } from './AgentPresence'
import { ContextGauge, contextWindowForModel } from './ContextGauge'

const MAX_SPARKLINE = 20

interface SparklineProps {
  values: number[]
  width?: number
  height?: number
}

function TpsSparkline({ values, width = 60, height = 18 }: SparklineProps) {
  if (values.length < 2) {
    return <div style={{ width, height }} className="flex items-end">
      {values.map((_, i) => (
        <div key={i} className="flex-1 bg-amber-400/40 rounded-sm mx-px" style={{ height: 3 }} />
      ))}
    </div>
  }
  const max = Math.max(...values, 0.1)
  const barW = Math.max(2, (width / values.length) - 1)

  return (
    <svg width={width} height={height} className="overflow-visible">
      {values.map((v, i) => {
        const h = Math.max(2, (v / max) * height)
        const x = i * (barW + 1)
        return (
          <rect
            key={i}
            x={x}
            y={height - h}
            width={barW}
            height={h}
            rx={1}
            className="fill-amber-400/70"
          />
        )
      })}
    </svg>
  )
}

interface AgentCardProps {
  agent: AgentStatus
  selected: boolean
  onClick: () => void
}

export function AgentCard({ agent, selected, onClick }: AgentCardProps) {
  const state = agent.status || agent.process_state || 'idle'
  const isRunning = state === 'running' || state === 'spawning' || state === 'busy'
  const ctxUsed = (agent.input_tokens || 0) + (agent.output_tokens || 0)
  // Killable = a live subprocess exists (busy OR idle-but-alive). EXCLUDE master:
  // it runs in-process, so its STATUS pid IS the backend (uvicorn) pid — killing
  // it would SIGTERM the whole backend. The UI must never do that.
  const killable = (agent.pid != null || isRunning) && agent.name !== 'master'

  const setSelectedLogAgent = useAgentChatStore((s) => s.setSelectedLogAgent)

  // TPS sparkline history
  const tpsHistoryRef = useRef<number[]>([])
  const [tpsHistory, setTpsHistory] = useState<number[]>([])

  useEffect(() => {
    if (!isRunning) {
      tpsHistoryRef.current = []
      setTpsHistory([])
      return
    }
    const tps = agent.tokens_per_second
    if (tps != null) {
      tpsHistoryRef.current = [...tpsHistoryRef.current, tps].slice(-MAX_SPARKLINE)
      setTpsHistory([...tpsHistoryRef.current])
    }
  }, [agent.tokens_per_second, isRunning])

  const tps = agent.tokens_per_second
  const outTokens = agent.output_tokens
  const inTokens = agent.input_tokens

  function handleClick(_e: React.MouseEvent) {
    onClick()
  }

  function openAgentFlow(e: React.MouseEvent) {
    e.stopPropagation()
    setSelectedLogAgent(agent.name)
  }

  const [killing, setKilling] = useState(false)
  async function handleStop(e: React.MouseEvent) {
    e.stopPropagation()
    setKilling(true)
    try {
      await killAgent(agent.name)
    } catch {
      /* error surfaced by the sidebar refresh / next poll */
    } finally {
      setKilling(false)
    }
  }

  return (
    <button
      onClick={handleClick}
      className={`w-full text-left px-4 py-2.5 hover:bg-zinc-800 transition-colors ${
        selected ? 'bg-zinc-800' : ''
      }`}
    >
      {/* Row 1: identity avatar + name + live presence + per-agent stop */}
      <div className="flex items-center gap-2">
        <AgentAvatar name={agent.name} size={18} />
        <span className="text-sm text-zinc-200 truncate flex-1">{getAgentDisplayName(agent.name)}</span>
        <AgentPresenceIndicator name={agent.name} status={state} />
        {killable && (
          <span
            role="button"
            tabIndex={0}
            onClick={handleStop}
            aria-disabled={killing}
            title={`Stop ${agent.name}`}
            className={`flex-shrink-0 w-5 h-5 rounded flex items-center justify-center text-red-400/70 hover:text-red-300 hover:bg-red-500/15 transition-colors ${killing ? 'opacity-40 pointer-events-none' : ''}`}
          >
            <svg width="8" height="8" viewBox="0 0 10 10"><rect width="10" height="10" rx="1.5" fill="currentColor" /></svg>
          </span>
        )}
      </div>

      {/* Row 2: pid / context gauge / task summary */}
      {(agent.pid != null || agent.task_summary || ctxUsed > 0) && (
        <div className="pl-4 mt-0.5">
          <div className="flex items-center gap-2">
            {agent.pid != null && (
              <span className="text-xs text-zinc-600 flex-shrink-0">pid {agent.pid}</span>
            )}
            <ContextGauge used={ctxUsed} window={contextWindowForModel(agent.model)} />
          </div>
          {agent.task_summary && (
            <p className="text-xs text-zinc-500 truncate">{agent.task_summary}</p>
          )}
        </div>
      )}

      {/* Row 3: model info (when selected) */}
      {selected && (
        <div className="pl-4 mt-0.5">
          <span className="text-[12px] text-zinc-500">{agent.adapter}/{agent.model}</span>
        </div>
      )}

      {/* Row 4: token stats (only when running) */}
      {isRunning && (tps != null || outTokens != null) && (
        <div className="pl-4 mt-1 flex items-center gap-3">
          {/* Counts */}
          <div className="flex flex-col gap-0.5 text-[12px] text-zinc-500 tabular-nums">
            {inTokens != null && (
              <span>in&nbsp;<span className="text-zinc-400">{inTokens.toLocaleString()}</span></span>
            )}
            {outTokens != null && (
              <span>out&nbsp;<span className="text-zinc-400">{outTokens.toLocaleString()}</span></span>
            )}
            {tps != null && (
              <span className="text-amber-400/80">{tps.toFixed(1)}&thinsp;t/s</span>
            )}
          </div>

          {/* Sparkline */}
          {tpsHistory.length > 1 && (
            <TpsSparkline values={tpsHistory} />
          )}
        </div>
      )}

      {/* "Agent flow" button — opens the side panel */}
      {(isRunning || selected) && (
        <div className="pl-4 mt-1.5">
          {/* span, not button: the whole card is already a <button> and
              nesting one inside another is invalid HTML (React warns about
              the hydration risk). Same pattern as the stop control above. */}
          <span
            role="button"
            tabIndex={0}
            onClick={openAgentFlow}
            className="text-[12px] text-zinc-500 hover:text-zinc-300 underline underline-offset-2 transition-colors cursor-pointer"
          >
            Agent flow →
          </span>
        </div>
      )}
    </button>
  )
}
