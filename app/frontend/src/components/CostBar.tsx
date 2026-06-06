import { useState, useEffect, useRef } from 'react'

// Pricing: [input_per_1M_tokens, output_per_1M_tokens] in USD
// Mirrors app/utils/adapters/models/anthropic.py ALL_PRICING
const PRICING: Record<string, [number, number]> = {
  'claude-opus-4-6': [5.0, 25.0],
  'claude-sonnet-4-6': [3.0, 15.0],
  'claude-haiku-4-5-20251001': [1.0, 5.0],
  'claude-sonnet-4-5-20250929': [3.0, 15.0],
  'claude-opus-4-5-20251101': [5.0, 25.0],
  'claude-opus-4-1-20250805': [15.0, 75.0],
  'claude-sonnet-4-20250514': [3.0, 15.0],
  'claude-opus-4-20250514': [15.0, 75.0],
}

function calcCost(model: string, inputTokens: number, outputTokens: number): number {
  const pricing = PRICING[model]
  if (!pricing) return 0
  const [inRate, outRate] = pricing
  return (inputTokens * inRate + outputTokens * outRate) / 1_000_000
}

/** Number of block characters for the ASCII progress bar */
const PROGRESS_BAR_WIDTH = 12

/**
 * Render a color-coded ASCII progress bar:
 *   `[██████░░░░] 60%`
 * Green (< 50%), yellow (50-80%), red (> 80%).
 */
function ProgressBar({ pct }: { pct: number }) {
  const filled = Math.round((pct / 100) * PROGRESS_BAR_WIDTH)
  const clamped = Math.min(100, Math.max(0, pct))
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
  inputTokens: number
  outputTokens: number
  tokensPerSecond: number
  contextWindow: number
}

export function CostBar({ model, inputTokens, outputTokens, tokensPerSecond, contextWindow }: CostBarProps) {
  const cost = calcCost(model, inputTokens, outputTokens)
  const totalTokens = inputTokens + outputTokens
  const ctxPct = contextWindow > 0 ? (totalTokens / contextWindow) * 100 : 0

  // Animated display values
  const animInput = useAnimatedToken(inputTokens)
  const animOutput = useAnimatedToken(outputTokens)

  const colorCls = tokenColorClass(ctxPct)

  return (
    <div className="px-4 py-2 border-t border-zinc-700 bg-zinc-900 flex items-center gap-3 text-xs flex-shrink-0 flex-wrap">
      <span className="text-purple-400 font-semibold">[master]</span>

      <span className={colorCls}>{(animInput / 1000).toFixed(1)}k in</span>
      <span className="text-zinc-600">·</span>
      <span className={colorCls}>{(animOutput / 1000).toFixed(1)}k out</span>

      {tokensPerSecond > 0 && (
        <>
          <span className="text-zinc-600">·</span>
          <span className="text-zinc-500">{tokensPerSecond.toFixed(0)} tok/s</span>
        </>
      )}

      <span className="text-zinc-600">·</span>
      <span className="text-zinc-400">${cost.toFixed(4)}</span>

      {ctxPct > 0 && (
        <>
          <span className="text-zinc-600">·</span>
          <ProgressBar pct={ctxPct} />
        </>
      )}
    </div>
  )
}
