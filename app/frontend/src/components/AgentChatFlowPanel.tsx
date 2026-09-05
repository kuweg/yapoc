import { useEffect, useMemo, useRef, useCallback } from 'react'
import type { AgentActivityLog } from '../types/agentActivity'
import { getAgentColor, withAlpha, getAgentDisplayName } from '../lib/agentIdentity'
import { useAgentActivity } from '../hooks/useAgentActivity'

interface Props {
  agentName: string
  onClose: () => void
}

/** Tool arg worth showing inline — the path/agent/command, not the whole blob. */
function toolArg(input: Record<string, unknown>): string {
  const v = input.path ?? input.agent_name ?? input.command ?? input.query ?? input.entry
  const s = typeof v === 'string' ? v : ''
  return s.length > 60 ? `${s.slice(0, 57)}…` : s
}

/** Readable, short one-line summary of a (non-error) tool result. */
function shortResult(result: string): string {
  const joined = (result || '')
    .replace(/\s+/g, ' ')
    .trim()
  if (!joined) return ''
  return joined.length > 120 ? `${joined.slice(0, 117)}…` : joined
}

/**
 * Logical chat rows derived from the raw activity stream:
 *   msg      — assistant prose (consecutive llm_output joined defensively)
 *   tool     — compact tool chip; absorbs an immediately-following tool_result
 *   status   — turn divider / status line (system events)
 *   error    — error chip (red-tinted, keeps agent avatar placement)
 */
type Row =
  | { kind: 'msg'; text: string; ts: string }
  | { kind: 'tool'; name: string; arg: string; result?: string; ts: string }
  | { kind: 'status'; label: string; ts: string }
  | { kind: 'error'; name: string | null; text: string; ts: string }

/** Fold the raw (already api-side coalesced) stream into chat rows. */
function toRows(activities: AgentActivityLog[]): Row[] {
  const rows: Row[] = []
  let openMsg = ''

  const flushMsg = () => {
    if (!openMsg) return
    const trimmed = openMsg.trim()
    if (trimmed) {
      rows.push({ kind: 'msg', text: trimmed, ts: rows.length ? rows[rows.length - 1].ts : '' })
    }
    openMsg = ''
  }

  for (const a of activities) {
    if (a.type === 'llm_output') {
      openMsg += a.content ?? ''
      continue
    }

    // Any non-llm event closes an in-progress assistant message.
    flushMsg()

    if (a.type === 'tool_call') {
      const meta = (a.metadata ?? {}) as Record<string, unknown>
      const name = String(meta.name ?? 'tool')
      rows.push({
        kind: 'tool',
        name,
        arg: toolArg((meta.input ?? {}) as Record<string, unknown>),
        ts: a.timestamp,
      })
    } else if (a.type === 'tool_result') {
      // Attach to the immediately-preceding tool if there was no prose/split
      // between the call and its result; otherwise show a muted one-liner.
      const last = rows[rows.length - 1]
      const summary = shortResult(a.content)
      if (last && last.kind === 'tool' && !last.result && summary) {
        last.result = summary
      } else if (summary) {
        rows.push({ kind: 'status', label: summary, ts: a.timestamp })
      }
    } else if (a.type === 'system') {
      // turn_start / turn_done etc → a numbered divider/status line.
      const label = (a.content ?? '').trim()
      rows.push({ kind: 'status', label, ts: a.timestamp })
    } else if (a.type === 'error') {
      const meta = (a.metadata ?? {}) as Record<string, unknown>
      rows.push({
        kind: 'error',
        name: typeof meta.name === 'string' ? meta.name : null,
        text: String(a.content ?? 'Unknown error'),
        ts: a.timestamp,
      })
    }
  }
  flushMsg()
  return rows
}

export function AgentChatFlowPanel({ agentName, onClose }: Props) {
  const activities = useAgentActivity(agentName)
  const rows = useMemo(() => toRows(activities), [activities])
  const listRef = useRef<HTMLDivElement>(null)
  const stickToBottomRef = useRef(true)
  const prefersReducedMotion = useRef(false)

  useEffect(() => {
    prefersReducedMotion.current = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  }, [])

  const handleScroll = useCallback(() => {
    const el = listRef.current
    if (!el) return
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    stickToBottomRef.current = distanceFromBottom < 60
  }, [])

  // Auto-scroll to bottom on new messages (stick-to-bottom preserved).
  useEffect(() => {
    if (!stickToBottomRef.current) return
    const el = listRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [rows])

  const agentColor = getAgentColor(agentName)
  const agentLabel = getAgentDisplayName(agentName)

  return (
    <div className="agent-chat-flow-panel">
      {/* Header (unchanged) */}
      <div className="agent-chat-flow-header">
        <div className="agent-chat-flow-header-left">
          <span
            className="agent-chat-flow-agent-dot"
            style={{ backgroundColor: agentColor }}
          />
          <span className="agent-chat-flow-agent-name">{agentLabel}</span>
          <span className="agent-chat-flow-msg-count">{activities.length} msgs</span>
        </div>
        <button
          onClick={onClose}
          className="agent-chat-flow-close-btn"
          aria-label="Close panel"
        >
          ×
        </button>
      </div>

      {/* Message list */}
      <div
        ref={listRef}
        onScroll={handleScroll}
        className="agent-chat-flow-list"
      >
        {rows.length === 0 && (
          <div className="agent-chat-flow-empty">
            <div className="agent-chat-flow-empty-icon">⟳</div>
            <p>Waiting for agent activity...</p>
            <p className="agent-chat-flow-empty-sub">Events will appear here as the agent runs</p>
          </div>
        )}

        {rows.map((row, i) => {
          switch (row.kind) {
            case 'msg':
              return (
                <div key={i} className="flowchat-msg-row" data-kind="msg">
                  <div
                    className="flowchat-msg-bubble"
                    style={{
                      backgroundColor: withAlpha(agentColor, 0.10),
                      borderColor: withAlpha(agentColor, 0.32),
                    }}
                  >
                    {row.text}
                  </div>
                </div>
              )

            case 'tool':
              return (
                <div key={i} className="flowchat-tool-row" data-kind="tool">
                  <div className="flowchat-tool-chip">
                    <span className="flowchat-tool-caret" style={{ color: agentColor }}>▸</span>
                    <span className="flowchat-tool-name" style={{ color: agentColor }}>
                      {row.name}
                    </span>
                    {row.arg && <span className="flowchat-tool-arg">{row.arg}</span>}
                  </div>
                  {row.result && (
                    <div className="flowchat-tool-result">
                      <span className="flowchat-tool-result-ok" style={{ color: agentColor }}>✓</span>
                      <span className="flowchat-tool-result-text">{row.result}</span>
                    </div>
                  )}
                </div>
              )

            case 'status':
              return (
                <div key={i} className="flowchat-status" data-kind="status">
                  <span className="flowchat-status-line" />
                  <span className="flowchat-status-text">{row.label}</span>
                  <span className="flowchat-status-line" />
                </div>
              )

            case 'error':
              return (
                <div key={i} className="flowchat-error-row" data-kind="error">
                  <div className="flowchat-error-chip">
                    <span className="flowchat-error-icon">⚠</span>
                    <span className="flowchat-error-title">
                      {row.name ? `${row.name} failed` : 'Error'}
                    </span>
                  </div>
                  <pre className="flowchat-error-body">{row.text}</pre>
                </div>
              )
          }
        })}
      </div>

      {/* Footer (unchanged) */}
      <div className="agent-chat-flow-footer">
        <span className="agent-chat-flow-footer-text">
          {activities.length > 0
            ? `${activities.length} events — auto-refreshing`
            : 'No events yet'}
        </span>
      </div>
    </div>
  )
}
