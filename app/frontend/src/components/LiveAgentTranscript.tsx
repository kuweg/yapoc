/**
 * Live transcript of an agent's work, rendered INTO the chat.
 *
 * Autonomous turns (a post-restart resume, a cron tick, a goal) are dispatched
 * through the task queue, not through the chat's own SSE stream — and their
 * session_id is often synthetic (RESUME.MD carries no session, so the queue
 * falls back to the task's own id). The browser is not subscribed to that
 * session, so the chat receives nothing while the agent-flow panel fills up
 * with the real work. That is the "master is clearly running but the chat is
 * empty" case.
 *
 * The agent-activity channel is keyed by AGENT rather than session, so it is
 * always available. This renders it in the chat, so post-restart work is
 * visible where the user is actually looking.
 */
import { useEffect, useMemo, useRef } from 'react'
import { useAgentActivity } from '../hooks/useAgentActivity'
import { AgentAvatar, getAgentColor, getAgentDisplayName, withAlpha } from '../lib/agentIdentity'

interface Line {
  kind: 'text' | 'tool'
  body: string
  detail?: string
}

/** Tool arg worth showing inline — the path/agent/command, not the whole blob. */
function toolArg(input: Record<string, unknown>): string {
  const v = input.path ?? input.agent_name ?? input.command ?? input.query ?? input.entry
  const s = typeof v === 'string' ? v : ''
  return s.length > 60 ? `${s.slice(0, 57)}…` : s
}

export function LiveAgentTranscript({
  agentName = 'master',
  sinceIso,
}: {
  agentName?: string
  /** Only show work from this point on, so old buffer content isn't replayed. */
  sinceIso?: string
}) {
  const activity = useAgentActivity(agentName)
  const endRef = useRef<HTMLDivElement>(null)

  const lines = useMemo<Line[]>(() => {
    const since = sinceIso ? Date.parse(sinceIso) : 0
    const out: Line[] = []
    for (const e of activity) {
      const ts = Date.parse(e.timestamp)
      if (since && !Number.isNaN(ts) && ts < since) continue

      if (e.type === 'llm_output') {
        const text = (e.content || '').trim()
        if (!text) continue
        // Coalesce consecutive output into one paragraph.
        const last = out[out.length - 1]
        if (last && last.kind === 'text') last.body += text
        else out.push({ kind: 'text', body: text })
      } else if (e.type === 'tool_call') {
        const meta = (e.metadata ?? {}) as Record<string, unknown>
        const name = String(meta.name ?? 'tool')
        out.push({ kind: 'tool', body: name, detail: toolArg((meta.input ?? {}) as Record<string, unknown>) })
      }
    }
    return out.slice(-40)
  }, [activity, sinceIso])

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'nearest' })
  }, [lines.length])

  if (lines.length === 0) return null
  const color = getAgentColor(agentName)

  return (
    <div
      className="my-2 rounded-md border overflow-hidden"
      style={{ borderColor: withAlpha(color, 0.35), background: withAlpha(color, 0.04) }}
      data-testid="live-agent-transcript"
    >
      <div className="flex items-center gap-2 px-3 py-1.5 border-b" style={{ borderColor: withAlpha(color, 0.2) }}>
        <AgentAvatar name={agentName} size={14} />
        <span className="text-[13px] font-mono font-semibold" style={{ color }}>
          {getAgentDisplayName(agentName)}
        </span>
        <span className="text-[12px] font-mono uppercase tracking-wider text-zinc-500">
          working — live
        </span>
        <span
          className="subagent-pulse w-1.5 h-1.5 rounded-full ml-auto"
          style={{ background: color }}
          aria-label="running"
        />
      </div>
      <div className="px-3 py-2 space-y-1 max-h-80 overflow-y-auto">
        {lines.map((l, i) =>
          l.kind === 'text' ? (
            <p key={i} className="text-[13px] leading-relaxed text-zinc-300 whitespace-pre-wrap break-words">
              {l.body}
            </p>
          ) : (
            <div key={i} className="flex items-center gap-2 text-[12px] font-mono">
              <span style={{ color }}>▸</span>
              <span className="text-zinc-400">{l.body}</span>
              {l.detail && <span className="text-zinc-600 truncate">{l.detail}</span>}
            </div>
          ),
        )}
        <div ref={endRef} />
      </div>
    </div>
  )
}
