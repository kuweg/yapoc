import type { AgentStatus, Message, ModelsResponse } from './types'

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

export async function approveToolCall(requestId: string, approved: boolean): Promise<void> {
  const res = await fetch(`/api/task/approve/${requestId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ approved }),
  })
  if (!res.ok) throw new Error(`POST /task/approve: ${res.status}`)
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
