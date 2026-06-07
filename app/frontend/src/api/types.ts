// Backend SSE events (mirrors Python dataclasses)
export type TextEvent = { type: 'text'; text: string }
export type ThinkingEvent = { type: 'thinking'; text: string }
export type ToolStartEvent = { type: 'tool_start'; name: string; input: Record<string, unknown> }
export type ToolDoneEvent = { type: 'tool_done'; name: string; result: string; is_error: boolean }
export type MessageBoundaryEvent = {
  type: 'message_boundary'
}

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
export type StreamEvent =
  | TextEvent
  | ThinkingEvent
  | ToolStartEvent
  | ToolDoneEvent
  | ErrorEvent
  | UsageEvent
  | MessageBoundaryEvent

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

export interface Attachment {
  id?: string          // server upload id (present after upload)
  name: string
  mime: string
  size?: number
  width?: number
  height?: number
  previewUrl?: string  // object-URL (session-only) for instant preview
}

export interface Message {
  role: 'user' | 'assistant'
  content: string
  parts?: TaskPart[]         // execution trace for structured assistant messages
  attachments?: Attachment[] // files attached to a user message
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
