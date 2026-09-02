/**
 * Connection state, modelled properly.
 *
 * docs/usability-audit-2026-04-18.md records the sidebar showing agents in red
 * "error" while their STATUS.json cleanly read `idle`. That was a state-
 * modelling failure, not a styling one: "no data" and "bad data" were collapsed
 * into the same visual. This component keeps the four states distinct — live,
 * reconnecting, stale, offline — and exposes the data's age so a reader can
 * tell a quiet system from a dead feed.
 */
import { useEffect, useState } from 'react'
import { useWsStore } from '../store/wsStore'

export type ConnState = 'live' | 'reconnecting' | 'stale' | 'offline'

const STALE_AFTER_MS = 30_000

export function useConnectionState(lastUpdated?: number | null): ConnState {
  const connected = useWsStore((s) => s.connected)
  const [, force] = useState(0)

  // Staleness is time-based, so re-evaluate on a timer even when nothing else
  // in the store changes.
  useEffect(() => {
    const id = setInterval(() => force((n) => n + 1), 5_000)
    return () => clearInterval(id)
  }, [])

  if (!connected) return 'offline'
  // `undefined` means the caller isn't tracking data age — the socket being up
  // is the whole signal, so report live. Only an explicit `null` means "tracking
  // age, nothing has arrived yet".
  if (lastUpdated === undefined) return 'live'
  if (lastUpdated === null) return 'reconnecting'
  return Date.now() - lastUpdated > STALE_AFTER_MS ? 'stale' : 'live'
}

const PRESENTATION: Record<ConnState, { label: string; color: string; pulse: boolean; help: string }> = {
  live: { label: 'Live', color: 'var(--color-success)', pulse: true, help: 'Receiving updates now' },
  reconnecting: { label: 'Connecting', color: 'var(--color-warning)', pulse: true, help: 'Connected, waiting for the first update' },
  stale: { label: 'Stale', color: 'var(--color-warning)', pulse: false, help: 'Connected, but no update recently — data below may be out of date' },
  offline: { label: 'Offline', color: 'var(--color-error)', pulse: false, help: 'No connection to the backend' },
}

function ageLabel(lastUpdated?: number | null): string {
  if (lastUpdated == null) return ''
  const secs = Math.floor((Date.now() - lastUpdated) / 1000)
  if (secs < 5) return 'just now'
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  return `${Math.floor(secs / 3600)}h ago`
}

export function ConnectionStatus({
  lastUpdated,
  showAge = true,
  className = '',
}: {
  lastUpdated?: number | null
  showAge?: boolean
  className?: string
}) {
  const state = useConnectionState(lastUpdated)
  const p = PRESENTATION[state]

  return (
    <span
      className={`inline-flex items-center gap-1.5 ${className}`}
      title={p.help}
      role="status"
      aria-live="polite"
      aria-label={`Connection: ${p.label}${showAge && lastUpdated ? `, updated ${ageLabel(lastUpdated)}` : ''}`}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${p.pulse ? 'animate-pulse' : ''}`}
        style={{ background: p.color, boxShadow: `0 0 0 2px color-mix(in srgb, ${p.color} 25%, transparent)` }}
      />
      <span className="text-[12px] font-mono uppercase tracking-[0.1em]" style={{ color: p.color }}>
        {p.label}
      </span>
      {showAge && lastUpdated != null && state !== 'offline' && (
        <span className="text-[12px] font-mono" style={{ color: 'var(--color-text-muted)' }}>
          {ageLabel(lastUpdated)}
        </span>
      )}
    </span>
  )
}
