import { useAgentStore } from '../store/agentStore'

const STATUS_COLORS = {
  connected: 'bg-[#3FB950]',
  reconnecting: 'bg-[#D29922] animate-pulse',
  disconnected: 'bg-[#F85149]',
}

const STATUS_LABELS = {
  connected: 'Connected',
  reconnecting: 'Reconnecting…',
  disconnected: 'Disconnected',
}

export function DashboardFooter() {
  const { connectionStatus, lastRefreshedAt } = useAgentStore()

  const lastRefreshStr = lastRefreshedAt
    ? new Date(lastRefreshedAt).toLocaleTimeString()
    : '—'

  return (
    <footer className="flex-shrink-0 bg-[#1C2128] border-t border-[#30363D] px-4 py-1.5 flex items-center gap-4 text-xs">
      {/* Connection status */}
      <div className="flex items-center gap-1.5">
        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${STATUS_COLORS[connectionStatus]}`} />
        <span className="text-[#8B949E]">{STATUS_LABELS[connectionStatus]}</span>
      </div>

      {/* Last refresh */}
      <span className="text-[#484F58]">
        Last refresh: {lastRefreshStr}
      </span>

      <div className="flex-1" />

      {/* App version */}
      <span className="text-[#484F58]">YAPOC v0.1.0</span>
    </footer>
  )
}
