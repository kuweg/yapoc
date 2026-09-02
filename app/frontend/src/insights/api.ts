// Typed fetchers for the Insights tab. All paths go through Vite's /api proxy,
// which strips the prefix before forwarding to the backend (see vite.config.ts).
import type {
  AgentCostSummary,
  CostHistoryResponse,
  HierarchyResponse,
  NotificationTraceResponse,
  ObservabilityResponse,
  StaleTasksResponse,
  UsageResponse,
} from './types'

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`GET ${path}: ${res.status}`)
  return res.json() as Promise<T>
}

export const getCostSummary = () => getJSON<AgentCostSummary[]>('/api/costs/summary')

export const getUsage = () => getJSON<UsageResponse>('/api/metrics/usage')

export const getCostHistory = (hours = 24) =>
  getJSON<CostHistoryResponse>(`/api/metrics/cost-history?hours=${hours}`)

export const getHierarchy = () => getJSON<HierarchyResponse>('/api/metrics/hierarchy')

export const getObservability = () => getJSON<ObservabilityResponse>('/api/metrics/observability')

export const getNotificationTrace = () =>
  getJSON<NotificationTraceResponse>('/api/notifications/trace')

export const getStaleTasks = () => getJSON<StaleTasksResponse>('/api/stale-tasks')

// ── Formatting helpers shared across the insight views ───────────────────────

export function formatUSD(n: number): string {
  if (n >= 1) return `$${n.toFixed(2)}`
  if (n >= 0.01) return `$${n.toFixed(3)}`
  if (n > 0) return `$${n.toFixed(5)}`
  return '$0'
}

export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

export function formatDuration(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60)
    return `${m}m ${Math.round(seconds % 60)}s`
  }
  if (seconds < 86_400) {
    const h = Math.floor(seconds / 3600)
    return `${h}h ${Math.round((seconds % 3600) / 60)}m`
  }
  const d = Math.floor(seconds / 86_400)
  return `${d}d ${Math.round((seconds % 86_400) / 3600)}h`
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const diff = (Date.now() - then) / 1000
  if (diff < 0) return 'just now'
  if (diff < 60) return `${Math.floor(diff)}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

// Stable per-agent hue so an agent keeps the same colour across every view.
export function agentColor(name: string): string {
  let hash = 0
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) | 0
  const hue = Math.abs(hash) % 360
  return `hsl(${hue}, 55%, 58%)`
}
