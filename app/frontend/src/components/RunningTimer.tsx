import { useEffect, useState } from 'react'

interface RunningTimerProps {
  /** Cumulative active seconds reported by the backend (static base). */
  totalSeconds: number
  /** When true, additionally tick the live portion every 1s. */
  running?: boolean
  /** Extra classes merged into the root (defaults: text-zinc-500 text-xs). */
  className?: string
}

function formatDuration(total: number): string {
  const s = Math.max(0, Math.floor(total))
  const hours = Math.floor(s / 3600)
  const minutes = Math.floor((s % 3600) / 60)
  const secs = s % 60
  const mm = String(minutes).padStart(2, '0')
  const ss = String(secs).padStart(2, '0')
  if (hours >= 1) {
    const hh = String(hours).padStart(2, '0')
    return `${hh}:${mm}:${ss}`
  }
  return `${minutes}:${ss}`
}

/**
 * A compact live-ticking "active running time" clock.
 *
 * `totalSeconds` is the static cumulative figure from the backend. When
 * `running` is true the component also ticks a live baseline (captured on
 * mount and whenever `running` flips true) so the running task's elapsed time
 * keeps incrementing client-side — no polling required. Formatting is
 * monospace + tabular so the digits don't jitter as it updates.
 */
export function RunningTimer({
  totalSeconds,
  running = false,
  className = '',
}: RunningTimerProps) {
  // Baseline for the live-ticked portion (epoch ms captured when running starts).
  const [baseline, setBaseline] = useState<number | null>(running ? Date.now() : null)
  const [, tick] = useState(0)

  // Capture a fresh baseline the moment `running` flips to true.
  useEffect(() => {
    if (running) setBaseline((prev) => (prev == null ? Date.now() : prev))
    else setBaseline(null)
  }, [running])

  // 1s interval drives re-render while running. It's a clock, not an
  // animation, so it updates regardless of prefers-reduced-motion.
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [running])

  let liveExtra = 0
  if (running && baseline != null) {
    liveExtra = (Date.now() - baseline) / 1000
  }

  const display = totalSeconds <= 0 && !running ? '—' : formatDuration(totalSeconds + liveExtra)

  return (
    <span
      className={`font-mono tabular-nums text-zinc-500 text-xs ${className}`.trim()}
    >
      {display}
    </span>
  )
}
