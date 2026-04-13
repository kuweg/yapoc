import { useRef, useEffect } from 'react'
import { useAgentStore } from '../../store/agentStore'
import { EventLogEntry } from './EventLogEntry'

export function EventLogFeed() {
  const events = useAgentStore((s) => s.events)
  const selectAgent = useAgentStore((s) => s.selectAgent)
  const bottomRef = useRef<HTMLDivElement>(null)
  const prevCountRef = useRef(events.length)

  // Auto-scroll when new events arrive
  useEffect(() => {
    if (events.length > prevCountRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
    prevCountRef.current = events.length
  }, [events.length])

  return (
    <div className="flex flex-col h-full">
      <h3 className="text-[10px] uppercase tracking-widest text-[#484F58] px-3 py-2 border-b border-[#21262D]">
        Live Events
      </h3>
      <div className="flex-1 overflow-y-auto py-1">
        {events.length === 0 && (
          <p className="px-3 py-4 text-xs text-[#484F58] text-center">
            No events yet
          </p>
        )}
        {[...events].reverse().map((event, i) => (
          <EventLogEntry
            key={event.id}
            event={event}
            isNew={i === 0 && events.length > prevCountRef.current}
            onClick={() => selectAgent(event.agent_name)}
          />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
