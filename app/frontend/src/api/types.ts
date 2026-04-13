// Backend SSE events (mirrors Python dataclasses)
export type TextEvent = { type: 'text'; text: string }
export type ThinkingEvent = { type: 'thinking'; text: string }
export type ToolStartEvent = { type: 'tool_start'; name: string; input: Record<string, unknown> }
export type ToolDoneEvent = { type: 'tool_done'; name: string; result: string; is_error: boolean }
export type UsageEvent = {
  type: 'usage_stats'
  input_tokens: number
  output_tokens: number
  tokens_per_second: number
  context_window: number
}
export type ToolApprovalRequestEvent = {
  type: 'tool_approval_request'
  request_id: string
  name: string
  input: Record<string, unknown>
}
export type ToolApprovalResultEvent = {
  type: 'tool_approval_result'
  request_id: string
  approved: boolean
}
export type StreamEvent =
  | TextEvent
  | ThinkingEvent
  | ToolStartEvent
  | ToolDoneEvent
  | UsageEvent
  | ToolApprovalRequestEvent
  | ToolApprovalResultEvent

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
  // Extended fields
  adapter: string
  state: string
  health: 'ok' | 'warning' | 'critical'
  started_at: string | null
  updated_at: string | null
  idle_since: string | null
  last_memory_entry: string | null
  tokens_per_second: number | null
  input_tokens: number | null
  output_tokens: number | null
}

export interface Message {
  role: 'user' | 'assistant'
  content: string
}

// Client-side session (localStorage)
export interface Session {
  id: string
  name: string
  createdAt: string
  history: Message[]
}
