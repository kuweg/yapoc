import { Fragment } from 'react'
import { RefreshCw, Plus, Unplug, ChevronDown, ChevronRight } from 'lucide-react'
import { StudioDialog } from '../studio/StudioDialog'
import { useEffect, useState, useCallback } from 'react'
import { getMcpServers, addMcpServer, deleteMcpServer, type McpServer } from '../api/pluginsClient'

const inputClass =
  'w-full bg-zinc-900 text-zinc-100 text-sm border border-zinc-800 rounded px-3 py-2 focus:outline-none focus:ring-1 focus:ring-zinc-600 placeholder-zinc-600'

const TRANSPORTS = ['stdio', 'streamable_http', 'sse', 'http']

interface EnvVar {
  key: string
  value: string
}

export function McpTab() {
  const [servers, setServers] = useState<McpServer[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // add-server form state
  const [showAdd, setShowAdd] = useState(false)
  const [name, setName] = useState('')
  const [transport, setTransport] = useState('stdio')
  const [command, setCommand] = useState('')
  const [url, setUrl] = useState('')
  const [args, setArgs] = useState('')
  const [envVars, setEnvVars] = useState<EnvVar[]>([])
  const [enabled, setEnabled] = useState(true)

  // delete confirm
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [expandedTools, setExpandedTools] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    getMcpServers()
      .then(setServers)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'failed'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const submitAdd = async () => {
    if (!name.trim()) return
    const payload: Record<string, unknown> = {
      name: name.trim(),
      transport,
      enabled,
    }
    if (transport === 'stdio') {
      if (!command.trim()) { setError('command is required for stdio transport'); return }
      payload.command = command.trim()
      if (args.trim()) payload.args = args.split(',').map((a) => a.trim()).filter(Boolean)
    } else {
      if (!url.trim()) { setError('url is required for this transport'); return }
      payload.url = url.trim()
    }
    const env: Record<string, string> = {}
    for (const e of envVars) {
      if (e.key.trim()) env[e.key.trim()] = e.value
    }
    if (Object.keys(env).length > 0) payload.env = env

    try {
      await addMcpServer(payload)
      setShowAdd(false)
      setName(''); setCommand(''); setUrl(''); setArgs(''); setEnvVars([]); setEnabled(true)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'add failed')
    }
  }

  const doDelete = async (serverName: string) => {
    try {
      await deleteMcpServer(serverName)
      setConfirmDelete(null)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'delete failed')
    }
  }

  const statusDot = (state: string) => {
    if (state === 'connected') return 'bg-green-500'
    if (state === 'error') return 'bg-red-500'
    return 'bg-zinc-500'
  }

  return (
    <div className="studio-settings relative flex flex-col h-full bg-zinc-950 text-zinc-100 overflow-hidden">
      <div className="studio-section-header">
        <div><h1>MCP servers</h1><p>Connect external tools to your agent workspace.</p></div>
        <button className="studio-secondary-button" onClick={load} aria-label="Refresh servers"><RefreshCw size={16} /></button>
        <button className="studio-primary-button" onClick={() => setShowAdd(true)}><Plus size={16} /> Add server</button>
      </div>
      <div className="studio-settings-body">
        {error && <div role="alert" className="studio-error"><strong>Could not load or update servers.</strong><span>{error}</span><button onClick={load}>Try again</button></div>}
        {loading ? <div className="studio-loading" role="status">Loading servers…<div /><div /><div /></div>
          : servers.length === 0 ? !error && <div className="studio-empty"><Unplug size={24} /><h2>No servers connected</h2><p>Add an MCP server to make its tools available to YAPOC.</p><button className="studio-primary-button" onClick={() => setShowAdd(true)}>Add your first server</button></div>
          : <div className="studio-table-scroll"><table className="studio-table" aria-label="MCP servers">
            <thead><tr><th>Server</th><th>Status</th><th>Transport</th><th>Tools</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{servers.map(server => <Fragment key={server.name}>
              <tr><td><strong>{server.name}</strong>{server.error && <p className="text-red-400 text-xs mt-1">{server.error}</p>}</td>
                <td><span className="studio-table-status"><span className={`w-1.5 h-1.5 rounded-full ${statusDot(server.state)}`} />{server.state || 'Disconnected'}</span></td>
                <td><code>{server.transport}</code></td><td><button className="studio-secondary-button" onClick={() => setExpandedTools(expandedTools === server.name ? null : server.name)} aria-expanded={expandedTools === server.name}>{expandedTools === server.name ? <ChevronDown size={14} /> : <ChevronRight size={14} />}{server.tool_count}</button></td>
                <td><button className="studio-secondary-button" onClick={() => setConfirmDelete(server.name)} aria-label={`Remove ${server.name}`}>Remove</button></td></tr>
              {expandedTools === server.name && <tr><td colSpan={5}>
                <div className="mt-2 border border-zinc-800 bg-zinc-950 rounded p-2">
                  {(server.tools ?? []).map((tool) => (
                    <div key={tool.name} className="py-1">
                      <code className="text-xs text-zinc-200">{tool.name}</code>
                      {tool.description && <p className="text-xs text-zinc-500 mt-0.5">{tool.description}</p>}
                    </div>
                  ))}
                  {(server.tools?.length ?? 0) === 0 && (
                    <p className="text-xs text-zinc-500">No tools exposed.</p>
                  )}
                </div>
              </td></tr>}
              {confirmDelete === server.name && <tr><td colSpan={5}><div className="studio-inline-confirm">
                <p>Remove “{server.name}” from this workspace?</p><button className="studio-danger-button" onClick={() => doDelete(server.name)}>Remove server</button><button className="studio-secondary-button" onClick={() => setConfirmDelete(null)}>Cancel</button>
              </div></td></tr>}
            </Fragment>)}</tbody>
          </table></div>}
      </div>

      {/* Add server overlay */}
      {showAdd && (
        <StudioDialog label="Add MCP server" onClose={() => setShowAdd(false)}>
          <div className="w-full max-w-lg border border-zinc-800 bg-zinc-900 rounded p-4 space-y-3 max-h-full overflow-y-auto">
            <h3 className="text-sm font-medium text-zinc-100">Add MCP server</h3>
            <label className="block">
              <span className="block text-xs uppercase tracking-widest text-zinc-500 mb-1">Name</span>
              <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="block">
              <span className="block text-xs uppercase tracking-widest text-zinc-500 mb-1">Transport</span>
              <select
                className={inputClass}
                value={transport}
                onChange={(e) => setTransport(e.target.value)}
              >
                {TRANSPORTS.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </label>
            {transport === 'stdio' ? (
              <>
                <label className="block">
                  <span className="block text-xs uppercase tracking-widest text-zinc-500 mb-1">Command</span>
                  <input className={inputClass} value={command} onChange={(e) => setCommand(e.target.value)} placeholder="npx -y @modelcontextprotocol/server-filesystem" />
                </label>
                <label className="block">
                  <span className="block text-xs uppercase tracking-widest text-zinc-500 mb-1">Args (comma-separated)</span>
                  <input className={inputClass} value={args} onChange={(e) => setArgs(e.target.value)} />
                </label>
              </>
            ) : (
              <label className="block">
                <span className="block text-xs uppercase tracking-widest text-zinc-500 mb-1">URL</span>
                <input className={inputClass} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/mcp" />
              </label>
            )}
            <div className="space-y-2">
              <span className="block text-xs uppercase tracking-widest text-zinc-500">Env vars</span>
              {envVars.map((env, i) => (
                <div key={i} className="flex gap-2">
                  <input
                    className={inputClass}
                    placeholder="KEY"
                    value={env.key}
                    onChange={(e) => setEnvVars((v) => v.map((x, xi) => (xi === i ? { ...x, key: e.target.value } : x)))}
                  />
                  <input
                    className={inputClass}
                    placeholder="value"
                    value={env.value}
                    onChange={(e) => setEnvVars((v) => v.map((x, xi) => (xi === i ? { ...x, value: e.target.value } : x)))}
                  />
                  <button
                    onClick={() => setEnvVars((v) => v.filter((_, xi) => xi !== i))}
                    className="text-zinc-500 hover:text-red-400 text-sm px-1"
                    title="Remove env var"
                  >
                    ×
                  </button>
                </div>
              ))}
              <button
                onClick={() => setEnvVars((v) => [...v, { key: '', value: '' }])}
                className="text-[11px] text-zinc-400 hover:text-[#FFB633] transition-colors"
              >
                + add env var
              </button>
            </div>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="accent-[#FFB633]" />
              <span className="text-xs text-zinc-300">Enabled</span>
            </label>
            <div className="flex gap-2">
              <button
                onClick={submitAdd}
                disabled={!name.trim()}
                className="px-3 py-1.5 text-xs rounded bg-[#FFB633] text-zinc-900 font-medium disabled:opacity-40"
              >
                Add
              </button>
              <button
                onClick={() => { setShowAdd(false); setName(''); setCommand(''); setUrl(''); setArgs(''); setEnvVars([]); setEnabled(true) }}
                className="px-3 py-1.5 text-xs rounded border border-zinc-800 text-zinc-400 hover:text-zinc-200"
              >
                Cancel
              </button>
            </div>
          </div>
        </StudioDialog>
      )}
    </div>
  )
}
