import type { AgentStatus, ChannelsResponse, ChannelSessionMessagesResponse, CommandResponse, Message, ModelsResponse, TTSRequest, TTSVoicesResponse, STTResponse } from './types'

export async function getAgents(): Promise<AgentStatus[]> {
  const res = await fetch('/api/agents')
  if (!res.ok) throw new Error(`GET /agents: ${res.status}`)
  return res.json() as Promise<AgentStatus[]>
}

export async function spawnAgent(name: string): Promise<{ status: string; name: string; pid?: number }> {
  const res = await fetch(`/api/agents/${name}/spawn`, { method: 'POST' })
  if (!res.ok) throw new Error(`POST /agents/${name}/spawn: ${res.status}`)
  return res.json() as Promise<{ status: string; name: string; pid?: number }>
}

export async function killAgent(name: string): Promise<{ status: string; name: string }> {
  const res = await fetch(`/api/agents/${name}/kill`, { method: 'POST' })
  if (!res.ok) throw new Error(`POST /agents/${name}/kill: ${res.status}`)
  return res.json() as Promise<{ status: string; name: string }>
}

// ── Task queue (live task tracking) ──────────────────────────────────────────
export interface QueuedTask {
  id: string
  prompt: string
  status: string // pending | running | done | error | blocked | cancelled
  source?: string
  session_id?: string
  assigned_agent?: string | null
  result?: string | null
  error?: string | null
  cost_usd?: number
  created_at?: string
  started_at?: string | null
  completed_at?: string | null
  updated_at?: string
}

// Start the YAPOC backend manually. Hits a dev-server middleware (NOT /api, so
// it is not proxied to the backend) — the Vite dev server is always up, so this
// works even when the backend is down. Dev-only (no-op in a built/prod deploy).
export async function startBackend(): Promise<{ status: string; detail?: string }> {
  const res = await fetch('/__yapoc/start', { method: 'POST' })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { detail = (await res.json()).error || detail } catch { /* ignore */ }
    throw new Error(detail)
  }
  return res.json()
}

export async function getTasks(limit = 50, status?: string): Promise<QueuedTask[]> {
  const qs = new URLSearchParams({ limit: String(limit) })
  if (status) qs.set('status', status)
  const res = await fetch(`/api/tasks?${qs.toString()}`)
  if (!res.ok) throw new Error(`GET /tasks: ${res.status}`)
  return res.json() as Promise<QueuedTask[]>
}

export async function getMasterResult(): Promise<{ name: string; content: string }> {
  const res = await fetch('/api/agents/master/result')
  if (!res.ok) throw new Error(`GET /agents/master/result: ${res.status}`)
  return res.json() as Promise<{ name: string; content: string }>
}

export async function getModels(): Promise<ModelsResponse> {
  const res = await fetch('/api/models')
  if (!res.ok) throw new Error(`GET /models: ${res.status}`)
  return res.json() as Promise<ModelsResponse>
}

export async function updateAgentConfig(
  name: string,
  adapter: string,
  model: string,
): Promise<{ status: string; name: string; adapter: string; model: string }> {
  const res = await fetch(`/api/models/agents/${name}/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ adapter, model }),
  })
  if (!res.ok) throw new Error(`PUT /models/agents/${name}/config: ${res.status}`)
  return res.json()
}

export async function getAgentFiles(name: string): Promise<{ name: string; files: string[] }> {
  const res = await fetch(`/api/agents/${name}/files`)
  if (!res.ok) throw new Error(`GET /agents/${name}/files: ${res.status}`)
  return res.json()
}

export async function readAgentFile(name: string, filename: string): Promise<{ name: string; filename: string; content: string }> {
  const res = await fetch(`/api/agents/${name}/file/${filename}`)
  if (!res.ok) throw new Error(`GET /agents/${name}/file/${filename}: ${res.status}`)
  return res.json()
}

export async function postTask(
  task: string,
  history: Message[],
): Promise<{ status: string; response: string }> {
  const res = await fetch('/api/task', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task, history, source: 'ui' }),
  })
  if (!res.ok) throw new Error(`POST /task: ${res.status}`)
  return res.json() as Promise<{ status: string; response: string }>
}

export async function synthesizeSpeech(req: TTSRequest): Promise<Blob> {
  const res = await fetch('/api/tts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new Error(`POST /tts: ${res.status}`)
  return res.blob()
}

export async function transcribeSpeech(
  audio: Blob,
  engine: string = 'offline',
  language: string = 'en-US',
): Promise<STTResponse> {
  const formData = new FormData()
  formData.append('audio', audio, 'recording.wav')
  formData.append('engine', engine)
  formData.append('language', language)
  const res = await fetch('/api/stt', {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) throw new Error(`POST /stt: ${res.status}`)
  return res.json() as Promise<STTResponse>
}

export async function summarizeSession(messages: Message[]): Promise<{ summary: string }> {
  const res = await fetch('/api/sessions/summarize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
  })
  if (!res.ok) throw new Error(`POST /sessions/summarize: ${res.status}`)
  return res.json() as Promise<{ summary: string }>
}

export async function getTTSVoices(): Promise<TTSVoicesResponse> {
  const res = await fetch('/api/tts/voices')
  if (!res.ok) throw new Error(`GET /tts/voices: ${res.status}`)
  return res.json() as Promise<TTSVoicesResponse>
}

// ── Slash commands ──────────────────────────────────────────────────────────

export async function handleCommand(command: string, args: string = ''): Promise<CommandResponse> {
  const res = await fetch('/api/commands', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command, args }),
  })
  if (!res.ok) throw new Error(`POST /commands: ${res.status}`)
  return res.json() as Promise<CommandResponse>
}

// ── Channel Dashboard ───────────────────────────────────────────────────────

export async function getChannelSessions(): Promise<ChannelsResponse> {
  const res = await fetch('/api/sessions/channels')
  if (!res.ok) throw new Error(`GET /sessions/channels: ${res.status}`)
  return res.json() as Promise<ChannelsResponse>
}

// ── File upload (images + text files) ────────────────────────────────────────

export interface FileUploadResult {
  path: string
  type?: string
  content?: string
}

export async function uploadFile(file: File): Promise<FileUploadResult> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch('/api/files/upload', { method: 'POST', body: form })
  if (!res.ok) throw new Error(`POST /files/upload: ${res.status}`)
  return res.json() as Promise<FileUploadResult>
}

// Legacy alias — old import paths still reference uploadImage
export const uploadImage = uploadFile

// ── Multi-file attachment upload (two-phase: upload → ids → chat) ─────────────
export interface UploadedAttachment {
  id: string
  name: string
  mime: string
  size: number
  hash: string
  width?: number
  height?: number
  is_duplicate?: boolean
}

export async function uploadFiles(
  files: File[],
): Promise<{ files: UploadedAttachment[]; errors: { name: string; error: string }[] }> {
  const form = new FormData()
  files.forEach((f) => form.append('files', f, f.name || 'paste.png'))
  const res = await fetch('/api/upload', { method: 'POST', body: form })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      detail = body.detail || body.error || detail
    } catch { /* ignore */ }
    throw new Error(detail)
  }
  return res.json()
}

export async function getChannelSessionMessages(source: string, sessionId: string): Promise<ChannelSessionMessagesResponse> {
  const res = await fetch(`/api/sessions/channel/${encodeURIComponent(source)}/${encodeURIComponent(sessionId)}`)
  if (!res.ok) throw new Error(`GET /sessions/channel/${source}/${sessionId}: ${res.status}`)
  return res.json() as Promise<ChannelSessionMessagesResponse>
}
