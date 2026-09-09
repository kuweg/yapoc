export interface PluginConfigSchemaField {
  type: string // 'string' | 'secret' | 'list' | 'bool' | 'number'
  required?: boolean
  default?: unknown
  label?: string
}

export interface Plugin {
  name: string
  display_name: string
  description: string
  version: string
  author: string
  category: string
  enabled: boolean
  config_schema: Record<string, PluginConfigSchemaField>
  tools: string[]
  registered_tools: string[]
  tool_details: { name: string; description: string }[]
  source: string
  config: Record<string, unknown>
  assigned_agents: string[]
}

export interface McpServer {
  name: string
  transport: string
  command: string
  url: string
  enabled: boolean
  auth: string
  tools_allowlist: string[]
  timeout_s: number
  auto_reconnect: boolean
  env: Record<string, string>
  state: string
  error: string | null
  tool_count: number
  tools: { name: string; description: string }[]
}

export async function getPlugins(): Promise<Plugin[]> {
  const res = await fetch(`/api/plugins`)
  if (!res.ok) throw new Error(`getPlugins: ${res.status}`)
  const data = await res.json()
  return data.plugins as Plugin[]
}

export async function savePluginConfig(
  name: string,
  config: Record<string, unknown>,
): Promise<{ status: string; name: string; config: Record<string, unknown> }> {
  const res = await fetch(`/api/plugins/${encodeURIComponent(name)}/config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!res.ok) throw new Error(`savePluginConfig: ${res.status}`)
  return res.json()
}

export async function setPluginEnabled(
  name: string,
  enabled: boolean,
): Promise<{ status: string; name: string; enabled: boolean }> {
  const res = await fetch(`/api/plugins/${encodeURIComponent(name)}/${enabled ? 'enable' : 'disable'}`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error(`setPluginEnabled: ${res.status}`)
  return res.json()
}

export async function getPluginAssignments(name: string): Promise<{ name: string; agents: string[] }> {
  const res = await fetch(`/api/plugins/${encodeURIComponent(name)}/assignments`)
  if (!res.ok) throw new Error(`getPluginAssignments: ${res.status}`)
  return res.json()
}

export async function setPluginAssignments(name: string, agents: string[]): Promise<{ status: string; name: string; agents: string[] }> {
  const res = await fetch(`/api/plugins/${encodeURIComponent(name)}/assignments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agents }),
  })
  if (!res.ok) throw new Error(`setPluginAssignments: ${res.status}`)
  return res.json()
}

export async function deletePlugin(name: string): Promise<{ status: string; name: string }> {
  const res = await fetch(`/api/plugins/${encodeURIComponent(name)}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`deletePlugin: ${res.status}`)
  return res.json()
}

export async function reloadPlugins(): Promise<{ status: string; plugins_loaded: number }> {
  const res = await fetch(`/api/plugins/reload`, { method: 'POST' })
  if (!res.ok) throw new Error(`reloadPlugins: ${res.status}`)
  return res.json()
}

export async function getMcpServers(): Promise<McpServer[]> {
  const res = await fetch(`/api/mcp-servers/servers`)
  if (!res.ok) throw new Error(`getMcpServers: ${res.status}`)
  const data = await res.json()
  return data.servers as McpServer[]
}

export async function addMcpServer(server: Record<string, unknown>): Promise<{ status: string; name: string }> {
  const res = await fetch(`/api/mcp-servers/servers`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(server),
  })
  if (!res.ok) throw new Error(`addMcpServer: ${res.status}`)
  return res.json()
}

export async function deleteMcpServer(name: string): Promise<{ status: string; name: string }> {
  const res = await fetch(`/api/mcp-servers/servers/${encodeURIComponent(name)}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`deleteMcpServer: ${res.status}`)
  return res.json()
}
