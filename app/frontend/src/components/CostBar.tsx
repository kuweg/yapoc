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

  return (
    <div className="px-4 py-2 border-t border-zinc-700 bg-zinc-900 flex items-center gap-3 text-xs text-zinc-500 flex-shrink-0">
      <span>{(inputTokens / 1000).toFixed(1)}k in</span>
      <span>·</span>
      <span>{(outputTokens / 1000).toFixed(1)}k out</span>
      {tokensPerSecond > 0 && (
        <>
          <span>·</span>
          <span>{tokensPerSecond.toFixed(0)} tok/s</span>
        </>
      )}
      <span>·</span>
      <span className="text-zinc-400">${cost.toFixed(4)}</span>
      {ctxPct > 0 && (
        <>
          <span>·</span>
          <span
            className={
              ctxPct >= 80 ? 'text-red-400' : ctxPct >= 60 ? 'text-amber-400' : 'text-zinc-500'
            }
          >
            ctx {ctxPct.toFixed(0)}%
          </span>
        </>
      )}
    </div>
  )
}
