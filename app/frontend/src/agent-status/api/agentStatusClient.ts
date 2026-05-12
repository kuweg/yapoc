import type { AgentStatus, AgentDetail, AdapterInfo } from '../types'

export async function getAgents(): Promise<AgentStatus[]> {
  const res = await fetch('/api/agents')
  if (!res.ok) throw new Error(`agents ${res.status}`)
  return res.json()
}

export async function getAgentDetail(name: string): Promise<AgentDetail> {
  const res = await fetch(`/api/agents/${name}`)
  if (!res.ok) throw new Error(`agent detail ${res.status}`)
  return res.json()
}

export async function restartAgent(name: string): Promise<void> {
  const res = await fetch(`/api/agents/${name}/restart`, { method: 'POST' })
  if (!res.ok) throw new Error(`restart ${res.status}`)
}

export interface PingResult {
  name: string
  alive: boolean
  state: string
  pid: number | null
  stale: boolean
  last_heartbeat: string | null
  diagnostic: string
}

export async function pingAgent(name: string): Promise<PingResult> {
  const res = await fetch(`/api/agents/${name}/ping`, { method: 'POST' })
  if (!res.ok) throw new Error(`ping ${res.status}`)
  return res.json()
}

export interface AgentCpuMetrics {
  agent_name: string
  pid: number | null
  cpu_percent: number
  memory_mb: number
  timestamp: string
}

export async function getAgentCpuMetrics(): Promise<AgentCpuMetrics[]> {
  const res = await fetch('/api/metrics/agents/cpu')
  if (!res.ok) throw new Error(`cpu metrics ${res.status}`)
  return res.json()
}

export async function getAgentFiles(name: string): Promise<string[]> {
  const res = await fetch(`/api/agents/${name}/files`)
  if (!res.ok) throw new Error(`agent files ${res.status}`)
  const data = await res.json()
  return data.files
}

export async function readAgentFile(name: string, filename: string): Promise<string> {
  const res = await fetch(`/api/agents/${name}/file/${filename}`)
  if (!res.ok) throw new Error(`read file ${res.status}`)
  const data = await res.json()
  return data.content
}

export async function getAgentLive(name: string): Promise<string> {
  const res = await fetch(`/api/agents/${name}/live`)
  if (!res.ok) throw new Error(`agent live ${res.status}`)
  const data = await res.json()
  return String(data.content ?? '')
}

export async function getModels(): Promise<AdapterInfo[]> {
  const res = await fetch('/api/models')
  if (!res.ok) throw new Error(`models ${res.status}`)
  const data = await res.json()
  return data.adapters
}

export async function updateAgentModel(name: string, adapter: string, model: string): Promise<void> {
  const res = await fetch(`/api/models/agents/${name}/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ adapter, model }),
  })
  if (!res.ok) throw new Error(`update model ${res.status}`)
}
