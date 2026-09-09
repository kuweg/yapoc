import { Fragment } from 'react'
import { RefreshCw, Blocks, Trash2, ChevronDown, ChevronRight } from 'lucide-react'
import { StudioDialog } from '../studio/StudioDialog'
import { useEffect, useState, useCallback } from 'react'
import {
  getPlugins,
  savePluginConfig,
  setPluginEnabled,
  reloadPlugins,
  setPluginAssignments,
  deletePlugin,
  type Plugin,
  type PluginConfigSchemaField,
} from '../api/pluginsClient'
import { getAgents } from '../api/client'

const inputClass =
  'w-full bg-zinc-900 text-zinc-100 text-sm border border-zinc-800 rounded px-3 py-2 focus:outline-none focus:ring-1 focus:ring-zinc-600 placeholder-zinc-600'

const REDACTED = '********'

export function PluginsTab() {
  const [plugins, setPlugins] = useState<Plugin[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloading, setReloading] = useState(false)

  // configure state
  const [configName, setConfigName] = useState<string | null>(null)
  const [configValues, setConfigValues] = useState<Record<string, string | boolean>>({})

  // assign tools state
  const [agents, setAgents] = useState<string[]>([])
  const [assignOpen, setAssignOpen] = useState<string | null>(null)
  const [assignSelection, setAssignSelection] = useState<Record<string, string[]>>({})
  const [expandedTools, setExpandedTools] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    getPlugins()
      .then(setPlugins)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'failed'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    getAgents()
      .then((list) => setAgents(list.map((a) => a.name)))
      .catch(() => setAgents([]))
  }, [])

  const toggleEnabled = async (plugin: Plugin) => {
    try {
      await setPluginEnabled(plugin.name, !plugin.enabled)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'toggle failed')
    }
  }

  const openAssign = (plugin: Plugin) => {
    if (assignOpen === plugin.name) {
      setAssignOpen(null)
      return
    }
    setAssignSelection((sel) => ({
      ...sel,
      [plugin.name]: plugin.assigned_agents ? [...plugin.assigned_agents] : [],
    }))
    setAssignOpen(plugin.name)
  }

  const persistAssign = async (pluginName: string, selection: string[]) => {
    try {
      await setPluginAssignments(pluginName, selection)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'assign failed')
    }
  }

  const toggleAgent = (pluginName: string, agent: string) => {
    const current = assignSelection[pluginName] ?? []
    const next = current.includes(agent)
      ? current.filter((a) => a !== agent)
      : [...current, agent]
    setAssignSelection((sel) => ({ ...sel, [pluginName]: next }))
    persistAssign(pluginName, next)
  }

  const toggleAllAgents = (pluginName: string) => {
    const current = assignSelection[pluginName] ?? []
    const allSelected = agents.length > 0 && agents.every((a) => current.includes(a))
    const next = allSelected ? [] : [...agents]
    setAssignSelection((sel) => ({ ...sel, [pluginName]: next }))
    persistAssign(pluginName, next)
  }

  const doDelete = async (plugin: Plugin) => {
    const displayName = plugin.display_name || plugin.name
    if (!window.confirm(`Delete plugin "${displayName}"? This removes its files and tools.`)) return
    try {
      await deletePlugin(plugin.name)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'delete failed')
    }
  }

  const doReload = async () => {
    setReloading(true)
    setError(null)
    try {
      await reloadPlugins()
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'reload failed')
    } finally {
      setReloading(false)
    }
  }

  const openConfig = (plugin: Plugin) => {
    const values: Record<string, string | boolean> = {}
    for (const [key, spec] of Object.entries(plugin.config_schema || {})) {
      const current = plugin.config?.[key]
      if (spec.type === 'bool') {
        values[key] = Boolean(current)
      } else if (spec.type === 'list') {
        values[key] = Array.isArray(current) ? current.join(', ') : String(current ?? '')
      } else if (spec.type === 'secret') {
        // Secret values come back redacted — leave empty so the user can re-enter.
        values[key] = current === REDACTED ? '' : String(current ?? '')
      } else {
        values[key] = current == null ? '' : String(current)
      }
    }
    setConfigValues(values)
    setConfigName(plugin.name)
  }

  const submitConfig = async () => {
    if (!configName) return
    const plugin = plugins.find((p) => p.name === configName)
    if (!plugin) return

    const config: Record<string, unknown> = {}
    for (const [key, spec] of Object.entries(plugin.config_schema || {})) {
      const value = configValues[key]
      if (spec.type === 'bool') {
        config[key] = Boolean(value)
      } else if (spec.type === 'number') {
        const text = String(value ?? '').trim()
        if (text === '') continue
        const num = Number(text)
        config[key] = Number.isNaN(num) ? text : num
      } else if (spec.type === 'list') {
        const text = String(value ?? '')
        config[key] = text.split(',').map((s) => s.trim()).filter(Boolean)
      } else if (spec.type === 'secret') {
        // Omit empty secret fields so the existing secret is preserved.
        if (String(value ?? '').trim() === '') continue
        config[key] = String(value)
      } else {
        config[key] = String(value ?? '')
      }
    }

    try {
      await savePluginConfig(configName, config)
      setConfigName(null)
      setConfigValues({})
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'save failed')
    }
  }

  const renderField = (key: string, spec: PluginConfigSchemaField) => {
    const label = spec.label || key
    const value = configValues[key]
    if (spec.type === 'bool') {
      return (
        <label key={key} className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(e) => setConfigValues((v) => ({ ...v, [key]: e.target.checked }))}
            className="accent-[#FFB633]"
          />
          <span className="text-xs text-zinc-300">{label}</span>
        </label>
      )
    }
    if (spec.type === 'secret') {
      return (
        <label key={key} className="block">
          <span className="block text-xs uppercase tracking-widest text-zinc-500 mb-1">{label}</span>
          <input
            type="password"
            className={inputClass}
            value={String(value ?? '')}
            placeholder="leave blank to keep existing secret"
            onChange={(e) => setConfigValues((v) => ({ ...v, [key]: e.target.value }))}
          />
        </label>
      )
    }
    if (spec.type === 'number') {
      return (
        <label key={key} className="block">
          <span className="block text-xs uppercase tracking-widest text-zinc-500 mb-1">{label}</span>
          <input
            type="number"
            className={inputClass}
            value={String(value ?? '')}
            onChange={(e) => setConfigValues((v) => ({ ...v, [key]: e.target.value }))}
          />
        </label>
      )
    }
    if (spec.type === 'list') {
      return (
        <label key={key} className="block">
          <span className="block text-xs uppercase tracking-widest text-zinc-500 mb-1">{label} (comma-separated)</span>
          <input
            className={inputClass}
            value={String(value ?? '')}
            onChange={(e) => setConfigValues((v) => ({ ...v, [key]: e.target.value }))}
          />
        </label>
      )
    }
    return (
      <label key={key} className="block">
        <span className="block text-xs uppercase tracking-widest text-zinc-500 mb-1">{label}</span>
        <input
          className={inputClass}
          value={String(value ?? '')}
          onChange={(e) => setConfigValues((v) => ({ ...v, [key]: e.target.value }))}
        />
      </label>
    )
  }

  const configPlugin = plugins.find((p) => p.name === configName)

  return (
    <div className="studio-settings relative flex flex-col h-full bg-zinc-950 text-zinc-100 overflow-hidden">
      <div className="studio-section-header">
        <div><h1>Plugins</h1><p>Manage capabilities and choose which agents can use them.</p></div>
        <button className="studio-secondary-button" onClick={load} aria-label="Refresh plugins"><RefreshCw size={16} /></button>
        <button className="studio-secondary-button" onClick={doReload} disabled={reloading}><RefreshCw size={16} />{reloading ? 'Reloading…' : 'Reload plugins'}</button>
      </div>
      <div className="studio-settings-body">
        {error && <div role="alert" className="studio-error"><strong>Could not load or update plugins.</strong><span>{error}</span><button onClick={load}>Try again</button></div>}
        {loading ? <div className="studio-loading" role="status">Loading plugins…<div /><div /><div /></div>
          : plugins.length === 0 ? !error && <div className="studio-empty"><Blocks size={24} /><h2>No plugins installed</h2><p>Add a plugin to your workspace’s plugins folder, then reload.</p><button className="studio-secondary-button" onClick={doReload} disabled={reloading}>Reload plugins</button></div>
          : <div className="studio-table-scroll"><table className="studio-table" aria-label="Plugins">
            <thead><tr><th>Plugin</th><th>Version</th><th>Tools</th><th>Status</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{plugins.map(plugin => <Fragment key={plugin.name}>
              <tr><td><strong>{plugin.display_name || plugin.name}</strong>{plugin.description && <p className="studio-table-description">{plugin.description}</p>}</td>
                <td><code>{plugin.version}</code></td><td><button className="studio-secondary-button" onClick={() => setExpandedTools(expandedTools === plugin.name ? null : plugin.name)} aria-expanded={expandedTools === plugin.name}>{expandedTools === plugin.name ? <ChevronDown size={14} /> : <ChevronRight size={14} />}{plugin.registered_tools?.length ?? 0}</button></td>
                <td><label className="studio-table-status"><input type="checkbox" checked={plugin.enabled} onChange={() => toggleEnabled(plugin)} aria-label={`Enable ${plugin.display_name || plugin.name}`} />{plugin.enabled ? 'Enabled' : 'Disabled'}</label></td>
                <td><div className="studio-row-actions"><button className="studio-secondary-button" onClick={() => openAssign(plugin)} aria-expanded={assignOpen === plugin.name}>Assign tools</button><button className="studio-secondary-button" onClick={() => openConfig(plugin)}>Configure</button><button className="studio-danger-button" onClick={() => doDelete(plugin)} aria-label={`Delete ${plugin.display_name || plugin.name}`}><Trash2 size={14} /> Delete</button></div></td></tr>
              {expandedTools === plugin.name && <tr><td colSpan={5}>
                <div className="mt-2 border border-zinc-800 bg-zinc-950 rounded p-2">
                  {(plugin.tool_details && plugin.tool_details.length > 0 ? plugin.tool_details : (plugin.registered_tools ?? []).map((t) => ({ name: t, description: '' }))).map((tool) => (
                    <div key={tool.name} className="py-1">
                      <code className="text-xs text-zinc-200">{tool.name}</code>
                      {tool.description && <p className="text-xs text-zinc-500 mt-0.5">{tool.description}</p>}
                    </div>
                  ))}
                  {(plugin.tool_details?.length ?? 0) === 0 && (plugin.registered_tools?.length ?? 0) === 0 && (
                    <p className="text-xs text-zinc-500">No tools registered.</p>
                  )}
                </div>
              </td></tr>}
              {assignOpen === plugin.name && <tr><td colSpan={5}>

                <div className="mt-2 border border-zinc-800 bg-zinc-950 rounded p-2">
                  <label className="flex items-center gap-2 py-1 border-b border-zinc-800 mb-1 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={agents.length > 0 && agents.every((a) => (assignSelection[plugin.name] ?? []).includes(a))}
                      onChange={() => toggleAllAgents(plugin.name)}
                      className="accent-[#FFB633]"
                    />
                    <span className="text-xs text-zinc-300">All agents</span>
                  </label>
                  <div className="max-h-48 overflow-y-auto space-y-1">
                    {agents.length === 0 ? (
                      <p className="text-xs text-zinc-500 px-1 py-1">No agents found.</p>
                    ) : (
                      agents.map((agent) => (
                        <label key={agent} className="flex items-center gap-2 px-1 py-0.5 cursor-pointer hover:bg-zinc-900 rounded">
                          <input
                            type="checkbox"
                            checked={(assignSelection[plugin.name] ?? []).includes(agent)}
                            onChange={() => toggleAgent(plugin.name, agent)}
                            className="accent-[#FFB633]"
                          />
                          <span className="text-xs text-zinc-300">{agent}</span>
                        </label>
                      ))
                    )}
                  </div>
                </div>

              </td></tr>}
            </Fragment>)}</tbody>
          </table></div>}
      </div>

      {/* Config overlay */}
      {configName !== null && configPlugin && (
        <StudioDialog label={`Configure ${configPlugin.display_name || configPlugin.name}`} onClose={() => { setConfigName(null); setConfigValues({}) }}>
          <div className="w-full max-w-lg border border-zinc-800 bg-zinc-900 rounded p-4 space-y-3 max-h-full overflow-y-auto">
            <h3 className="text-sm font-medium text-zinc-100">{configPlugin.display_name || configPlugin.name}</h3>
            {Object.keys(configPlugin.config_schema || {}).length === 0 ? (
              <p className="text-xs text-zinc-500">This plugin has no configurable fields.</p>
            ) : (
              Object.entries(configPlugin.config_schema).map(([key, spec]) => renderField(key, spec))
            )}
            <div className="flex gap-2">
              <button
                onClick={submitConfig}
                className="px-3 py-1.5 text-xs rounded bg-[#FFB633] text-zinc-900 font-medium"
              >
                Save
              </button>
              <button
                onClick={() => { setConfigName(null); setConfigValues({}) }}
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
