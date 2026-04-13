import { useRelativeTime, formatAbsoluteTime } from '../../hooks/useRelativeTime'

interface Props {
  timestamp: string | null
  fallback?: string
  isStale?: boolean
}

export function TimestampCell({ timestamp, fallback = '—', isStale = false }: Props) {
  const relative = useRelativeTime(timestamp)
  const absolute = formatAbsoluteTime(timestamp)

  return (
    <span
      className={`text-sm tabular-nums ${isStale ? 'text-[#D29922]' : 'text-[#8B949E]'}`}
      title={absolute || undefined}
    >
      {isStale && <span className="mr-1" aria-label="stale data">⚠</span>}
      {timestamp ? relative : fallback}
    </span>
  )
}
