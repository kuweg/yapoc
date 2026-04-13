import { useEffect, useRef, useState } from 'react'
import type { AgentStatus } from '../api/types'
import { AgentLogDrawer } from './AgentLogDrawer'

const STATUS_DOT: Record<string, string> = {
  running: 'bg-amber-400',
  idle: 'bg-emerald-400',
  terminated: 'bg-zinc-500',
  error: 'bg-red-400',
  spawning: 'bg-amber-400 animate-pulse',
}

const STATUS_TEXT: Record<string, string> = {
  running: 'text-amber-400',
  idle: 'text-emerald-400',
  terminated: 'text-zinc-500',
  error: 'text-red-400',
  spawning: 'text-amber-400',
}

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
  const state = agent.process_state || agent.status || 'idle'
  const dotColor = STATUS_DOT[state] ?? 'bg-zinc-500'
  const textColor = STATUS_TEXT[state] ?? 'text-zinc-500'
  const isRunning = state === 'running' || state === 'spawning'

  // Accumulate TPS history locally
  const tpsHistoryRef = useRef<number[]>([])
  const [tpsHistory, setTpsHistory] = useState<number[]>([])
  const [drawerOpen, setDrawerOpen] = useState(false)

  useEffect(() => {
    if (!isRunning) {
      // Fade out: clear history when agent goes idle
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

  function openDrawer(e: React.MouseEvent) {
    e.stopPropagation()
    setDrawerOpen(true)
  }

  return (
    <>
      <button
        onClick={handleClick}
        className={`w-full text-left px-4 py-2.5 hover:bg-zinc-800 transition-colors ${
          selected ? 'bg-zinc-800' : ''
        }`}
      >
        {/* Row 1: dot + name + status */}
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full flex-shrink-0 ${dotColor}`} />
          <span className="text-sm text-zinc-200 truncate flex-1">{agent.name}</span>
          <span className={`text-xs ${textColor}`}>{state}</span>
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

        {/* Row 3: token stats (only when running) */}
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

        {/* Row 4: "View logs" button when running or selected */}
        {(isRunning || selected) && (
          <div className="pl-4 mt-1.5">
            <button
              onClick={openDrawer}
              className="text-[10px] text-zinc-500 hover:text-zinc-300 underline underline-offset-2 transition-colors"
            >
              View logs →
            </button>
          </div>
        )}
      </button>

      {drawerOpen && (
        <AgentLogDrawer
          agentName={agent.name}
          state={state}
          onClose={() => setDrawerOpen(false)}
        />
      )}
    </>
  )
}
