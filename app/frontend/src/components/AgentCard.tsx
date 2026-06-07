import { useEffect, useRef, useState } from 'react'
import type { AgentStatus } from '../api/types'
import { useAgentChatStore } from '../store/agentChatStore'
import { AgentAvatar, getAgentDisplayName } from '../lib/agentIdentity'
import { AgentPresenceIndicator } from './AgentPresence'

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

  return (
    <button
      onClick={handleClick}
      className={`w-full text-left px-4 py-2.5 hover:bg-zinc-800 transition-colors ${
        selected ? 'bg-zinc-800' : ''
      }`}
    >
      {/* Row 1: identity avatar + name + live presence */}
      <div className="flex items-center gap-2">
        <AgentAvatar name={agent.name} size={18} />
        <span className="text-sm text-zinc-200 truncate flex-1">{getAgentDisplayName(agent.name)}</span>
        <AgentPresenceIndicator name={agent.name} status={state} />
      </div>

      {/* Row 2: pid / task summary */}
      {(agent.pid != null || agent.task_summary) && (
        <div className="pl-4 mt-0.5">
          {agent.pid != null && (
            <span className="text-xs text-zinc-600">pid {agent.pid}</span>
          )}
          {agent.task_summary && (
            <p className="text-xs text-zinc-500 truncate">{agent.task_summary}</p>
          )}
        </div>
      )}

      {/* Row 3: model info (when selected) */}
      {selected && (
        <div className="pl-4 mt-0.5">
          <span className="text-[10px] text-zinc-500">{agent.adapter}/{agent.model}</span>
        </div>
      )}

      {/* Row 4: token stats (only when running) */}
      {isRunning && (tps != null || outTokens != null) && (
        <div className="pl-4 mt-1 flex items-center gap-3">
          {/* Counts */}
          <div className="flex flex-col gap-0.5 text-[10px] text-zinc-500 tabular-nums">
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
          <button
            onClick={openAgentFlow}
            className="text-[10px] text-zinc-500 hover:text-zinc-300 underline underline-offset-2 transition-colors"
          >
            Agent flow →
          </button>
        </div>
      )}
    </button>
  )
}
