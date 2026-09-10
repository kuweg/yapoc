import { useEffect, useState } from 'react'

/**
 * What master is doing right now, for as long as a turn is in flight.
 *
 * The chat used to show a bare "Thinking…" only until the first part arrived,
 * after which a long turn gave no sign of life at all — a tool that takes two
 * minutes looked identical to a hung stream. This stays for the whole turn and
 * names the phase, the tool in flight, and how long it has been going.
 */
function formatElapsed(ms: number): string {
  const total = Math.floor(ms / 1000)
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return minutes > 0 ? `${minutes}m ${String(seconds).padStart(2, '0')}s` : `${seconds}s`
}

export function TurnStatusBar({
  spinner,
  label,
  tool,
  startedAt,
  tokensPerSecond,
  outputTokens,
  onStop,
}: {
  /** Animated activity glyph, supplied by the caller that owns the animation. */
  spinner?: React.ReactNode
  label: string
  tool?: string
  startedAt: number
  tokensPerSecond?: number
  outputTokens?: number
  onStop?: () => void
}) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  return (
    <div className="turn-status" role="status" aria-live="polite" data-testid="turn-status">
      {spinner}
      <span className="turn-status-phase">{label}</span>
      {tool && <span className="turn-status-tool">{tool}</span>}
      <span className="turn-status-meta">
        <span title="Elapsed time for this turn">{formatElapsed(Math.max(0, now - startedAt))}</span>
        {outputTokens ? <span title="Output tokens so far">{outputTokens.toLocaleString()} tok</span> : null}
        {tokensPerSecond ? <span title="Output tokens per second">{tokensPerSecond.toFixed(1)}/s</span> : null}
      </span>
      {onStop && (
        <button type="button" className="turn-status-stop" onClick={onStop} title="Stop this turn">
          Stop
        </button>
      )}
    </div>
  )
}
