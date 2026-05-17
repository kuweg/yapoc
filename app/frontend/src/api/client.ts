import type { AgentStatus, CommandResponse, Message, ModelsResponse, TTSRequest, TTSVoicesResponse, STTResponse } from './types'

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
