// Small primitives shared by the Insights views: a polling hook, panel chrome,
// and the load/empty/error states every view needs.
import { useCallback, useEffect, useRef, useState } from 'react'

export interface Polled<T> {
  data: T | null
  error: string | null
  loading: boolean
  lastUpdated: number | null
  refresh: () => void
}

/**
 * Polls `fetcher` on an interval. Keeps the previous payload visible while a
 * refresh is in flight so the view never flashes empty, and stops polling while
 * the tab is hidden (these endpoints scan the task DB — no point burning it).
 */
export function usePolled<T>(fetcher: () => Promise<T>, intervalMs = 10_000, enabled = true): Polled<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<number | null>(null)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  const cancelled = useRef(false)

  const run = useCallback(async () => {
    setLoading(true)
    try {
      const next = await fetcherRef.current()
      if (cancelled.current) return
      setData(next)
      setError(null)
      setLastUpdated(Date.now())
    } catch (e) {
      if (!cancelled.current) setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (!cancelled.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    cancelled.current = false
    if (!enabled) return
    void run()
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') void run()
    }, intervalMs)
    return () => {
      cancelled.current = true
      clearInterval(id)
    }
  }, [run, intervalMs, enabled])

  return { data, error, loading, lastUpdated, refresh: run }
}

export function Panel({
  title,
  subtitle,
  right,
  children,
  className = '',
}: {
  title: string
  subtitle?: string
  right?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section
      className={`rounded border overflow-hidden flex flex-col ${className}`}
      style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-panel)' }}
    >
      <header
        className="flex items-baseline gap-3 px-4 py-2.5 border-b flex-shrink-0"
        style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-secondary)' }}
      >
        <h3 className="text-[13px] font-mono uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-secondary)' }}>
          {title}
        </h3>
        {subtitle && (
          <span className="text-[12px] font-mono" style={{ color: 'var(--color-text-muted)' }}>
            {subtitle}
          </span>
        )}
        {right && <div className="ml-auto flex items-center gap-2">{right}</div>}
      </header>
      <div className="flex-1 min-h-0">{children}</div>
    </section>
  )
}

export function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[12px] font-mono uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-muted)' }}>
        {label}
      </span>
      <span className="text-lg font-mono tabular-nums leading-none" style={{ color: tone ?? 'var(--color-text-primary)' }}>
        {value}
      </span>
    </div>
  )
}

export function ViewState({
  loading,
  error,
  empty,
  emptyLabel,
  onRetry,
}: {
  loading: boolean
  error: string | null
  empty: boolean
  emptyLabel: string
  onRetry?: () => void
}) {
  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-10 px-4 text-center">
        <span className="text-xs font-mono" style={{ color: 'var(--color-error)' }}>
          Couldn't load this view — {error}
        </span>
        {onRetry && (
          <button
            onClick={onRetry}
            className="text-[12px] font-mono px-2 py-1 rounded border hover:opacity-80"
            style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)' }}
          >
            Try again
          </button>
        )}
      </div>
    )
  }
  if (loading) {
    return (
      <div className="py-10 text-center text-xs font-mono" style={{ color: 'var(--color-text-muted)' }}>
        Loading…
      </div>
    )
  }
  if (empty) {
    return (
      <div className="py-10 text-center text-xs font-mono" style={{ color: 'var(--color-text-muted)' }}>
        {emptyLabel}
      </div>
    )
  }
  return null
}
