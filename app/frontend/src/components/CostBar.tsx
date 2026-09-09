import { useState, useEffect, useRef } from 'react'

import { getModels } from '../api/client'
import type { ModelEntry } from '../api/types'

/** Number of block characters for the ASCII progress bar */
const PROGRESS_BAR_WIDTH = 12

/**
 * Render a color-coded ASCII progress bar:
 *   `[██████░░░░] 60%`
 * Green (< 50%), yellow (50-80%), red (> 80%).
 */
function ProgressBar({ pct }: { pct: number }) {
  const clamped = Math.min(100, Math.max(0, pct))
  const filled = Math.round((clamped / 100) * PROGRESS_BAR_WIDTH)
  const colorClass =
    clamped >= 80 ? 'text-red-400' : clamped >= 50 ? 'text-yellow-400' : 'text-green-400'

  const bar = '█'.repeat(filled) + '░'.repeat(PROGRESS_BAR_WIDTH - filled)

  return (
    <span className={`font-mono ${colorClass}`}>
      [{bar}] {clamped.toFixed(0)}%
    </span>
  )
}

/**
 * Animate a numeric value by counting from a previous value toward a target,
 * ticking every ~40ms (25 fps) with an ease-out feel.
 */
function useAnimatedToken(target: number): number {
  const [display, setDisplay] = useState(target)
  const prevTargetRef = useRef(target)
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    const prev = prevTargetRef.current
    prevTargetRef.current = target
    if (target === prev) return

    const duration = 300 // ms — snappy enough to feel live
    const start = performance.now()
    const from = prev

    function tick(now: number) {
      const elapsed = now - start
      const t = Math.min(elapsed / duration, 1)
      // ease-out quad
      const eased = 1 - (1 - t) * (1 - t)
      setDisplay(Math.round(from + (target - from) * eased))
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick)
      }
    }

    rafRef.current = requestAnimationFrame(tick)

    return () => {
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
    }
  }, [target])

  return display
}

/** Color class for token numbers based on context usage ratio. */
function tokenColorClass(pct: number): string {
  if (pct >= 80) return 'text-red-400'
  if (pct >= 50) return 'text-yellow-400'
  return 'text-green-400'
}

interface CostBarProps {
  model: string
  adapter?: string
  agentName?: string
  hideAgent?: boolean
  inputTokens: number
  outputTokens: number
  tokensPerSecond: number
  contextWindow: number
  estimated?: boolean
  inputKnown?: boolean
  showModel?: boolean
  outputKnown?: boolean
  compact?: boolean
}

export function CostBar({ model, adapter, agentName = 'master', hideAgent = false, inputTokens, outputTokens, tokensPerSecond, contextWindow, estimated = false, inputKnown = true, outputKnown = true, showModel = false, compact = false }: CostBarProps) {
  const [catalog, setCatalog] = useState<{adapter: string; entry: ModelEntry}[]>([])
  useEffect(() => {
    let active = true
    getModels().then(result => {
      if (active) setCatalog(result.adapters.flatMap(a => a.models.map(entry => ({ adapter: a.name, entry }))))
    }).catch(() => { if (active) setCatalog([]) })
    return () => { active = false }
  }, [model, adapter])
  const entry = catalog.find(row => row.entry.id === model && (!adapter || row.adapter === adapter))?.entry
  // A catalog record without provenance is historical, not a verified current quote.
  const known = entry?.pricing_verified_at && Number.isFinite(entry.input_price) && Number.isFinite(entry.output_price)
  const cost = known && inputKnown
    ? (inputTokens * entry!.input_price! + outputTokens * entry!.output_price!) / 1_000_000
    : null
  const priceTitle = cost == null
    ? 'Verified pricing unavailable for this model, or input usage not reported yet'
    : `Base-rate estimate (uncached input). ${entry?.pricing_notes || ''} Verified ${entry?.pricing_verified_at}. ${entry?.pricing_source}`
  const totalTokens = inputTokens + outputTokens
  const ctxPct = contextWindow > 0 ? (totalTokens / contextWindow) * 100 : 0

  // Animated display values
  const animInput = useAnimatedToken(inputTokens)
  const animOutput = useAnimatedToken(outputTokens)

  const colorCls = tokenColorClass(ctxPct)

  return (
    <div data-testid="live-usage" data-estimated={estimated} title="Latest model response. Streaming estimates use roughly four characters per token; provider counts replace them when available." className={`usage-bar ${compact ? 'usage-bar-compact' : 'px-4 py-2 border-t border-zinc-700 bg-zinc-900'} flex items-center gap-3 text-xs flex-shrink-0 flex-wrap`}>
      {!hideAgent && <span className="text-purple-400 font-semibold">[{agentName}]</span>}
      {showModel && <span className="usage-model" title={model || 'Model loading'}>[{model || 'model loading…'}]</span>}

      <span className={colorCls} data-testid="usage-input">{inputKnown ? `${estimated ? "≈" : ""}${(animInput / 1000).toFixed(1)}k` : "—"} in</span>
      <span className="text-zinc-600">·</span>
      <span className={colorCls} data-testid="usage-output">{outputKnown ? `${estimated ? "≈" : ""}${animOutput < 1000 ? Math.round(animOutput) : `${(animOutput / 1000).toFixed(1)}k`}` : '—'} out</span>

      <span className="text-zinc-600">·</span>
      <span className="text-zinc-500" data-testid="usage-speed">{tokensPerSecond > 0 ? `${estimated ? '≈' : ''}${tokensPerSecond.toFixed(0)}` : '—'} tok/s</span>

      <span className="text-zinc-600">·</span>
      <span className="text-zinc-400" data-testid="usage-cost" title={priceTitle}>{cost == null ? "Cost —" : `≈$${cost.toFixed(4)}`}</span>

      <span className="text-zinc-600">·</span>
      <span data-testid="usage-context" title={contextWindow > 0 ? 'Context usage; streaming uses the last reported input as an estimate until updated by the provider' : 'Context usage not reported yet'}>
        {contextWindow > 0 ? <>{estimated && '≈'}<ProgressBar pct={ctxPct} /></> : <span className="font-mono text-zinc-500">[░░░░░░░░░░░░] —</span>}
      </span>
    </div>
  )
}
