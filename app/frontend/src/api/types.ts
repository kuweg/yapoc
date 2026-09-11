// Backend SSE events (mirrors Python dataclasses)
export type TextEvent = { type: 'text'; text: string }
export type ThinkingEvent = { type: 'thinking'; text: string }
export type ToolStartEvent = { type: 'tool_start'; name: string; input: Record<string, unknown> }
export type ToolDoneEvent = { type: 'tool_done'; name: string; result: string; is_error: boolean }
export type MessageBoundaryEvent = {
  type: 'message_boundary'
}

/** Emitted when a chat turn is queued behind master's background work. */
export type StatusEvent = { type: 'status'; state: string; text: string }

export type ErrorEvent = {
  type: 'error'
  error: string
}
export type UsageEvent = {
  type: 'usage_stats'
  input_tokens: number
  output_tokens: number
  tokens_per_second: number
  context_window: number
}
export type CompactEvent = {
  type: 'compact'
  reason: string
  tokens_before: number
  tokens_after: number
}
/** An agent was rebound to a new provider partway through this turn. */
export type ModelSwappedEvent = {
  type: 'model_swapped'
  agent: string
  adapter: string
  model: string
}
export type StreamEvent =
  | { type: 'task_result'; result: StructuredTaskResult }
  | TextEvent
  | ThinkingEvent
  | ToolStartEvent
  | ToolDoneEvent
  | ErrorEvent
  | UsageEvent
  | CompactEvent
  | MessageBoundaryEvent
  | ModelSwappedEvent
  | StatusEvent

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

export interface ModelEntry {
  id: string
  description: string
  context_window: number
  supports_tools: boolean
  input_price?: number
  output_price?: number
  pricing_source?: string
  pricing_verified_at?: string
  pricing_notes?: string
  cached_input_price?: number | null
  off_peak_input_price?: number | null
  off_peak_output_price?: number | null
  off_peak_cached_input_price?: number | null
  long_context_input_price?: number | null
  long_context_output_price?: number | null
}

export interface AdapterInfo {
  name: string
  has_key: boolean
  models: ModelEntry[]
}

export interface ModelsResponse {
  adapters: AdapterInfo[]
}

// A single part inside a structured assistant message
export type TaskPart =
  | { kind: 'text'; text: string }
  | { kind: 'thinking'; id: string; text: string; done: boolean }
  | {
      kind: 'tool'
      id: string
      name: string
      input: Record<string, unknown>
      result?: string
      isError?: boolean
      done: boolean
    }
  | { kind: 'compact'; id: string; tokensBefore: number; tokensAfter: number; reason: string }
  | { kind: 'chart'; option: Record<string, unknown> }
  | { kind: 'mermaid'; source: string }
  | { kind: 'calendar'; events: Array<{ summary: string; start: string; end: string; location?: string; description?: string }>; weekStart?: string }

export interface Attachment {
  id?: string          // server upload id (present after upload)
  name: string
  mime: string
  size?: number
  width?: number
  height?: number
  previewUrl?: string  // object-URL (session-only) for instant preview
}

export interface TaskCompletionMeta {
  structured_result?: StructuredTaskResult

  status?: string
  prompt?: string
  result?: string
  error?: string
  agent?: string
  source?: string
  session_id?: string
  created_at?: string
  started_at?: string
  completed_at?: string
}

export interface Message {
  completionId?: string // persisted delivery ID, independent of task-card presentation
  role: 'user' | 'assistant'
  content: string
  parts?: TaskPart[]         // execution trace for structured assistant messages
  attachments?: Attachment[] // files attached to a user message
  taskCompletion?: TaskCompletionMeta // rich "what just finished" card metadata
}

// Client-side session (localStorage)
export interface Session {
  noteContext?: Array<{ id: string; title: string }>
  /** Delivery receipts survive message-history trimming. */
  completionIds?: string[]
  id: string
  name: string
  createdAt: string
  history: Message[]
  source?: string  // 'ui' | 'cli' | 'telegram' | etc.
}

export interface ActiveTimeAgent {
  name: string
  running: boolean
  current_elapsed_s: number
  total_active_s: number
  task_count: number
}
export interface ActiveTimeSession {
  name: string
  running: boolean
  current_elapsed_s: number
  total_active_s: number
  task_count: number
}
export interface ActiveTimesResponse {
  generated_at: string
  agents: ActiveTimeAgent[]
  sessions: ActiveTimeSession[]
}

// Voice API types
export interface TTSRequest {
  text: string
  engine?: 'offline' | 'openai' | 'google'
  voice?: string
  speed?: number
  format?: 'wav' | 'mp3' | 'ogg'
}

export interface TTSVoice {
  id: string
  name: string
  language: string
  gender: string
}

export interface TTSVoicesResponse {
  engines: Record<string, { available: boolean; voices: TTSVoice[] }>
}

export interface STTResponse {
  text: string
  confidence: number
  engine: string
  duration_ms: number
}

// Slash command response
export interface CommandResponse {
  response: string
}

// Channel Dashboard types
export interface SessionInfo {
  id: string
  name: string
  createdAt: string
  messageCount: number
  source: string
  preview: string
}

export interface ChannelInfo {
  source: string
  count: number
  sessions: SessionInfo[]
}

export interface ChannelsResponse {
  channels: ChannelInfo[]
}

export interface ChannelSessionMessagesResponse {
  session_id: string
  source: string
  messages: Message[]
}

export interface StructuredTaskResult {
  progress?: import('./client').QueuedTask['progress']
  schema_version: 1
  task_id: string
  status: 'succeeded' | 'partial' | 'failed' | 'blocked' | 'cancelled'
  summary: string
  changes: { files: string[] }
  verification_status: 'checks_passed' | 'failed' | 'unknown' | 'not_run'
  verification: Array<{ command: string; status: string; exit_code: number | null; evidence_event_seq: number; evidence_url: string }>
  artifacts: Array<{ id: string; type: string; name: string; url: string }>
  usage: { input_tokens: number | null; output_tokens: number | null; estimated_cost_usd: number | null; scope: string }
  limitations: string[]
}
