import { useEffect, useRef, useCallback } from 'react'
import type { AgentActivityLog } from '../types/agentActivity'
import { ACTIVITY_TYPE_COLORS, ACTIVITY_TYPE_LABELS, getAgentColor } from '../types/agentActivity'
import { useAgentActivity } from '../hooks/useAgentActivity'

interface Props {
  agentName: string
  onClose: () => void
}

/** Format ISO timestamp to HH:MM:SS */
function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString('en-US', { hour12: false })
  } catch {
    return iso.slice(11, 19) || iso
  }
}

/** Single activity bubble */
function ActivityBubble({ activity }: { activity: AgentActivityLog }) {
  const borderColor = ACTIVITY_TYPE_COLORS[activity.type]
  const agentColor = getAgentColor(activity.agent_name)
  const typeLabel = ACTIVITY_TYPE_LABELS[activity.type]

  return (
    <div className="agent-activity-bubble" style={{ borderLeftColor: borderColor }}>
      {/* Header row: timestamp, agent badge, type badge */}
      <div className="agent-activity-bubble-header">
        <span className="agent-activity-timestamp">{formatTime(activity.timestamp)}</span>
        <span
          className="agent-activity-agent-badge"
          style={{ backgroundColor: agentColor, color: '#0a0a0a' }}
        >
          {activity.agent_name}
        </span>
        <span
          className="agent-activity-type-badge"
          style={{ backgroundColor: borderColor + '22', color: borderColor, borderColor }}
        >
          {typeLabel}
        </span>
      </div>

      {/* Content */}
      <div className="agent-activity-content">
        <pre className="agent-activity-pre">{activity.content}</pre>
      </div>
    </div>
  )
}

export function AgentChatFlowPanel({ agentName, onClose }: Props) {
  const activities = useAgentActivity(agentName)
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

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (!stickToBottomRef.current) return
    const el = listRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [activities])

  const agentColor = getAgentColor(agentName)

  return (
    <div className="agent-chat-flow-panel">
      {/* Header */}
      <div className="agent-chat-flow-header">
        <div className="agent-chat-flow-header-left">
          <span
            className="agent-chat-flow-agent-dot"
            style={{ backgroundColor: agentColor }}
          />
          <span className="agent-chat-flow-agent-name">{agentName}</span>
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
        {activities.length === 0 && (
          <div className="agent-chat-flow-empty">
            <div className="agent-chat-flow-empty-icon">⟳</div>
            <p>Waiting for agent activity...</p>
            <p className="agent-chat-flow-empty-sub">Events will appear here as the agent runs</p>
          </div>
        )}

        {activities.map((activity, i) => (
          <ActivityBubble key={`${activity.timestamp}-${i}`} activity={activity} />
        ))}
      </div>

      {/* Footer */}
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
