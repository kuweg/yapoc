// Shared types for the Insights tab — cost, trace, delegation and error views.
// Mirrors the payloads served by app/backend/routers/metrics.py and costs.py.

// ── /api/costs/summary ───────────────────────────────────────────────────────
export interface AgentCostSummary {
  agent_name: string
  total_cost_usd: number
  total_tasks: number
  total_tokens_in: number
  total_tokens_out: number
}

// ── /api/metrics/usage ───────────────────────────────────────────────────────
export interface ModelUsage {
  input_tokens: number
  output_tokens: number
  cache_creation_tokens: number
  cache_read_tokens: number
  cost_usd: number
  turns: number
  tool_calls: number
}

export interface AgentUsage {
  name: string
  total_cost_usd: number
  total_input_tokens: number
  total_output_tokens: number
  total_tool_calls: number
  total_turns: number
  by_model: Record<string, ModelUsage>
}

export interface UsageResponse {
  total_cost_usd: number
  agent_usage: AgentUsage[]
}

// ── /api/metrics/cost-history ────────────────────────────────────────────────
export interface CostPoint {
  timestamp: string
  cost_usd: number
  agent: string
  model: string
  tokens_in: number
  tokens_out: number
}

export interface CostHistoryResponse {
  points: CostPoint[]
  bucket: string
}

// ── /api/metrics/hierarchy ───────────────────────────────────────────────────
export interface HierarchyResponse {
  generated_at: string
  total_task_records: number
  delegated_by_parent: Record<string, number>
  average_completion_seconds_by_parent: Record<string, number>
}

// ── /api/metrics/observability ───────────────────────────────────────────────
export interface ObsTotals {
  total_cost_usd: number
  total_tasks: number
  active_agents: number
  agents_with_errors: number
  recent_error_count: number
}

export interface ObsAgent {
  name: string
  status: string
  is_alive: boolean
  cost_usd: number
  input_tokens: number
  output_tokens: number
  task_count: number
  health_issues: number
  last_active_at: string | null
  models: string[]
}

export interface ObsError {
  agent: string
  timestamp: string
  level: string
  message: string
}

export interface ObsTask {
  agent: string
  task_id: string
  status: string
  assigned_by: string
  assigned_at: string
  completed_at: string
  duration_s: number | null
  task_summary: string
  error_summary: string
}

export interface ObservabilityResponse {
  generated_at: string
  totals: ObsTotals
  agents: ObsAgent[]
  recent_errors: ObsError[]
  recent_tasks: ObsTask[]
}

// ── /api/notifications/trace ─────────────────────────────────────────────────
export interface TraceNotification {
  ts: string
  event: string
  parent_agent: string
  child_agent: string
  status?: string
  session_id?: string
  completed_at?: string
  reason?: string
}

export interface NotificationTraceResponse {
  events: TraceNotification[]
}

// ── /api/stale-tasks ─────────────────────────────────────────────────────────
export interface StaleTask {
  agent: string
  task_id?: string
  age_seconds?: number
  task_summary?: string
  status?: string
}

export interface StaleTasksResponse {
  stale_tasks: StaleTask[]
  threshold_seconds: number
}
