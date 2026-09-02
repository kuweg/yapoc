/**
 * Per-agent context-window usage gauge. Shows how full an agent's context is
 * (used tokens / window) — the signal for "why did the agent forget that" and
 * when a compaction is imminent. Green < 70%, amber < 85% (compaction threshold),
 * red at/above it.
 */
function gaugeColor(pct: number): string {
  if (pct >= 85) return '#f85149' // red — at/over the compaction threshold
  if (pct >= 70) return '#d29922' // amber — pre-emptive snapshot zone
  return '#3fb950' // green
}

// AgentStatus carries token usage but not the model's window, so derive it from
// the model name. Approximate (the chat's CostBar uses the adapter's exact
// value); good enough for a per-agent fill indicator.
const MODEL_WINDOWS: Array<[string, number]> = [
  ['claude', 200_000],
  ['gemini', 1_000_000],
  ['kimi', 200_000],
  ['deepseek', 64_000],
  ['gpt', 128_000],
  ['o1', 128_000],
  ['o3', 128_000],
  ['llama', 128_000],
  ['qwen', 128_000],
]

export function contextWindowForModel(model?: string | null): number {
  if (!model) return 0
  const m = model.toLowerCase()
  for (const [key, win] of MODEL_WINDOWS) if (m.includes(key)) return win
  return 128_000 // sensible default
}

export function ContextGauge({
  used,
  window,
  width = 40,
  showPct = true,
}: {
  used: number
  window: number
  width?: number
  showPct?: boolean
}) {
  if (!window || window <= 0 || used <= 0) return null
  const pct = Math.min(100, (used / window) * 100)
  const color = gaugeColor(pct)
  return (
    <span
      className="inline-flex items-center gap-1 flex-shrink-0"
      title={`Context ${(used / 1000).toFixed(1)}k / ${(window / 1000).toFixed(0)}k tokens (${pct.toFixed(0)}%)`}
    >
      <span className="h-1 rounded-full bg-zinc-700/60 overflow-hidden" style={{ width }}>
        <span className="block h-full rounded-full transition-all duration-300" style={{ width: `${pct}%`, backgroundColor: color }} />
      </span>
      {showPct && <span className="text-[12px] font-mono tabular-nums leading-none" style={{ color }}>{pct.toFixed(0)}%</span>}
    </span>
  )
}

/**
 * Inline marker shown in the chat/agent-flow when the context was compacted —
 * makes "the agent summarized its history here" visible (the roadmap's
 * compaction-wave). `.compact-marker` carries a one-shot sweep animation
 * (reduced-motion aware) defined in index.css.
 */
export function CompactionMarker({
  tokensBefore,
  tokensAfter,
  reason,
}: {
  tokensBefore: number
  tokensAfter: number
  reason?: string
}) {
  const saved = tokensBefore > 0 ? Math.round((1 - tokensAfter / tokensBefore) * 100) : 0
  return (
    <div
      className="compact-marker flex items-center gap-2 my-1 px-2.5 py-1 rounded-md border border-purple-500/30 bg-purple-500/5 text-[13px] font-mono text-purple-300/90"
      title={`Context compacted (${reason || 'auto'}) — the agent summarized older turns to free room`}
    >
      <span className="text-purple-400">⊟</span>
      <span className="uppercase tracking-wide text-[12px]">context compacted</span>
      {tokensBefore > 0 && (
        <span className="text-zinc-400 tabular-nums">
          {(tokensBefore / 1000).toFixed(0)}k → {(tokensAfter / 1000).toFixed(0)}k
        </span>
      )}
      {saved > 0 && <span className="text-emerald-400/80">saved {saved}%</span>}
    </div>
  )
}
