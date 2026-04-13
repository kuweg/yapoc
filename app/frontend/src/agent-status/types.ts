export type AgentState = 'running' | 'idle' | 'done' | 'error' | 'spawning' | 'terminated' | ''
export type HealthStatus = 'ok' | 'warning' | 'critical'
export type StatusFilterType = 'all' | 'running' | 'idle' | 'error'
export type SortBy = 'status' | 'name' | 'activity' | 'health'
export type DensityMode = 'compact' | 'comfortable'

export interface AgentStatus {
  name: string
  status: string
  model: string
  has_task: boolean
  memory_entries: number
  health_errors: number
  process_state: string
  pid: number | null
  task_summary: string
  adapter: string
  state: AgentState
  health: HealthStatus
  started_at: string | null
  updated_at: string | null
  idle_since: string | null
  last_memory_entry: string | null
}

export interface HealthLogEntry {
  timestamp: string
  level: string
  message: string
  context: string | null
}

export interface TaskDetail {
  status: string
  assigned_by: string
  assigned_at: string
  completed_at: string | null
  task_text: string
  result_text: string | null
  error_text: string | null
}

export interface AgentDetail extends AgentStatus {
  task: TaskDetail | null
  health_log: HealthLogEntry[]
  memory_log: string[]
  uptime_seconds: number | null
}

export interface AgentEvent {
  id: string
  timestamp: string
  agent_name: string
  event_type: string
  message: string
  level: 'info' | 'warning' | 'error'
}
