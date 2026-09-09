interface CalendarEvent {
  summary: string
  start: string
  end: string
  location?: string
  description?: string
}

interface CalendarBlockProps {
  events: CalendarEvent[]
  weekStart?: string
}

function formatRange(start: string, end: string): string {
  const s = new Date(start)
  const e = new Date(end)
  const sValid = !Number.isNaN(s.getTime())
  const eVvalid = !Number.isNaN(e.getTime())
  if (sValid && eVvalid) {
    return `${s.toLocaleString()} → ${e.toLocaleString()}`
  }
  if (sValid) return `${s.toLocaleString()} → ${end}`
  if (eVvalid) return `${start} → ${e.toLocaleString()}`
  return `${start} → ${end}`
}

const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const HOUR_START = 8
const HOUR_END = 20
const HOURS = Array.from({ length: HOUR_END - HOUR_START }, (_, i) => HOUR_START + i)

/** Clamp a Date to the local midnight of the same day (drops time-of-day). */
function startOfDay(d: Date): Date {
  const copy = new Date(d)
  copy.setHours(0, 0, 0, 0)
  return copy
}

/** Monday of the week containing `d`. */
function mondayOf(d: Date): Date {
  const day = d.getDay() // 0 = Sunday
  const diff = day === 0 ? -6 : 1 - day
  const monday = new Date(d)
  monday.setDate(d.getDate() + diff)
  return startOfDay(monday)
}

/** True when the event spans multiple calendar days (or is explicitly all-day). */
function isMultiDay(start: Date, end: Date): boolean {
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return false
  return startOfDay(start).getTime() !== startOfDay(end).getTime()
}

/**
 * Renders a Google-Calendar-style WEEK GRID (Mon–Sun) with a left-hand time
 * gutter. The grid always renders — even when `events` is empty — so an empty
 * week still shows the full day columns and time rows.
 */
export default function CalendarBlock({ events, weekStart }: CalendarBlockProps) {
  const list = Array.isArray(events) ? events : []

  // Determine the Monday anchoring the week: explicit prop → first event → now.
  let anchor: Date
  const ws = weekStart ? new Date(weekStart) : null
  if (ws && !Number.isNaN(ws.getTime())) {
    anchor = mondayOf(ws)
  } else {
    const firstValid = list
      .map((e) => new Date(e.start))
      .find((d) => !Number.isNaN(d.getTime()))
    anchor = firstValid ? mondayOf(firstValid) : mondayOf(new Date())
  }

  const days: Date[] = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(anchor)
    d.setDate(anchor.getDate() + i)
    return d
  })

  // Bucket events by day column. Multi-day events are shown in their start day
  // column (and marked as spanning). Invalid-date events are skipped.
  const byDay: CalendarEvent[][] = days.map(() => [])
  for (const event of list) {
    const s = new Date(event.start)
    if (Number.isNaN(s.getTime())) continue
    const col = Math.floor((startOfDay(s).getTime() - anchor.getTime()) / 86400000)
    if (col < 0 || col > 6) continue
    byDay[col].push(event)
  }

  // Sort each column by start time, then by duration.
  for (const col of byDay) {
    col.sort((a, b) => {
      const as = new Date(a.start).getTime()
      const bs = new Date(b.start).getTime()
      if (as !== bs) return as - bs
      const ae = new Date(a.end).getTime()
      const be = new Date(b.end).getTime()
      return ae - be
    })
  }

  const isToday = (d: Date) => startOfDay(d).getTime() === startOfDay(new Date()).getTime()

  return (
    <div className="w-full my-1 overflow-x-auto">
      <div className="min-w-[640px] rounded-lg border border-zinc-700/70 bg-zinc-900/60">
        {/* Header row: day names + dates */}
        <div className="grid grid-cols-[3.5rem_repeat(7,1fr)] border-b border-zinc-700/70">
          <div className="h-10" />
          {days.map((d, i) => {
            const today = isToday(d)
            return (
              <div
                key={i}
                className={`flex flex-col items-center justify-center py-1.5 border-l border-zinc-700/50 ${
                  today ? 'bg-zinc-800/80' : ''
                }`}
              >
                <span className="text-[11px] uppercase tracking-wide text-zinc-500">
                  {DAY_NAMES[i]}
                </span>
                <span
                  className={`text-sm font-semibold ${
                    today ? 'text-blue-400' : 'text-zinc-200'
                  }`}
                >
                  {d.getDate()}
                </span>
              </div>
            )
          })}
        </div>

        {/* Time rows */}
        {HOURS.map((hour) => (
          <div
            key={hour}
            className="grid grid-cols-[3.5rem_repeat(7,1fr)] border-b border-zinc-800/60 last:border-b-0"
          >
            <div className="relative h-12 pr-2 text-right">
              <span className="absolute -top-2 right-2 text-[10px] text-zinc-500">
                {String(hour).padStart(2, '0')}:00
              </span>
            </div>
            {days.map((_, col) => {
              const cellEvents = byDay[col].filter((event) => {
                const s = new Date(event.start)
                if (Number.isNaN(s.getTime())) return false
                return s.getHours() === hour
              })
              return (
                <div key={col} className="relative border-l border-zinc-700/50">
                  {cellEvents.map((event, j) => {
                    const multi = isMultiDay(new Date(event.start), new Date(event.end))
                    return (
                      <div
                        key={j}
                        title={formatRange(event.start, event.end)}
                        className="absolute inset-x-0.5 top-0.5 rounded bg-blue-600/80 px-1.5 py-0.5 text-[11px] leading-tight text-white shadow-sm"
                      >
                        <div className="truncate font-medium">{event.summary}</div>
                        {multi && (
                          <div className="truncate text-[10px] text-blue-200">
                            ↕ multi-day
                          </div>
                        )}
                        {event.location && (
                          <div className="truncate text-[10px] text-blue-200">
                            📍 {event.location}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}
