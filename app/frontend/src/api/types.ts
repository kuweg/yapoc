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
export type StreamEvent =
  | TextEvent
  | ThinkingEvent
  | ToolStartEvent
  | ToolDoneEvent
  | UsageEvent

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
}

export interface AdapterInfo {
  name: string
  has_key: boolean
  models: ModelEntry[]
}

export interface ModelsResponse {
  adapters: AdapterInfo[]
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
  source?: string  // 'ui' | 'cli' | 'telegram' | etc.
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
