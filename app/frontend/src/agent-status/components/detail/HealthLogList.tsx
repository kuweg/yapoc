import type { HealthLogEntry } from '../../types'
import { formatAbsoluteTime } from '../../hooks/useRelativeTime'

interface Props {
  entries: HealthLogEntry[]
}

const LEVEL_COLORS: Record<string, string> = {
  ERROR: 'text-[#F85149]',
  WARNING: 'text-[#D29922]',
  WARN: 'text-[#D29922]',
  INFO: 'text-[#FFB633]',
}

export function HealthLogList({ entries }: Props) {
  if (entries.length === 0) {
    return (
      <div className="py-4 text-center text-sm text-[#484F58]">
        No health log entries
      </div>
    )
  }

  return (
    <div className="space-y-1 max-h-48 overflow-y-auto">
      {entries.slice(0, 20).map((entry, i) => {
        const levelUpper = entry.level.toUpperCase()
        const color = LEVEL_COLORS[levelUpper] ?? 'text-[#8B949E]'
        return (
          <div
            key={i}
            className="flex gap-2 text-xs font-mono px-1 py-0.5 rounded hover:bg-[#21262D] transition-colors"
          >
            <span className="text-[#484F58] whitespace-nowrap flex-shrink-0">
              {formatAbsoluteTime(entry.timestamp).split(', ')[1] || entry.timestamp.slice(11, 19)}
            </span>
            <span className={`font-semibold flex-shrink-0 ${color}`}>{levelUpper}</span>
            <span className="text-[#E6EDF3] break-words">{entry.message}</span>
          </div>
        )
      })}
    </div>
  )
}
