import { useEffect, useState } from 'react'
import type { AdapterInfo } from '../../types'
import { getModels, updateAgentModel } from '../../api/agentStatusClient'

interface Props {
  agentName: string
  currentAdapter: string
  currentModel: string
  onUpdated: () => void
}

export function AgentModelPicker({ agentName, currentAdapter, currentModel, onUpdated }: Props) {
  const [adapters, setAdapters] = useState<AdapterInfo[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    getModels().then(setAdapters).catch(() => {})
  }, [])

  async function handleSelect(adapter: string, model: string) {
    if (adapter === currentAdapter && model === currentModel) return
    setSaving(true)
    setError(null)
    setSuccess(false)
    try {
      await updateAgentModel(agentName, adapter, model)
      setSuccess(true)
      onUpdated()
      setTimeout(() => setSuccess(false), 2000)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      {/* Current model */}
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[11px] text-[#484F58]">Current:</span>
        <span className="text-[11px] font-mono text-[#E6EDF3]">
          <span className="text-[#FFB633]">{currentAdapter}</span>
          <span className="text-[#484F58]">/</span>
          {currentModel}
        </span>
        {saving && <span className="text-[10px] text-[#E3B341] animate-pulse">Saving...</span>}
        {success && <span className="text-[10px] text-[#3FB950]">Saved</span>}
        {error && <span className="text-[10px] text-[#F85149]">{error}</span>}
      </div>

      {/* Adapter groups */}
      <div className="space-y-1 max-h-64 overflow-y-auto">
        {adapters.map((adapter) => (
          <div key={adapter.name}>
            {/* Adapter header */}
            <div className="flex items-center gap-1.5 px-2 py-1">
              <span className={`text-[10px] font-semibold uppercase tracking-wider ${
                adapter.has_key ? 'text-[#8B949E]' : 'text-[#484F58]'
              }`}>
                {adapter.name}
              </span>
              {adapter.has_key ? (
                <span className="w-1.5 h-1.5 rounded-full bg-[#3FB950] flex-shrink-0" />
              ) : (
                <span className="text-[9px] text-[#484F58]">no key</span>
              )}
            </div>
            {/* Models */}
            <div className="grid grid-cols-1 gap-0.5">
              {adapter.models.map((model) => {
                const isActive = adapter.name === currentAdapter && model.id === currentModel
                const disabled = !adapter.has_key
                return (
                  <button
                    key={`${adapter.name}/${model.id}`}
                    onClick={() => !disabled && handleSelect(adapter.name, model.id)}
                    disabled={disabled || saving}
                    className={`text-left px-2 py-1 rounded flex items-center gap-2 transition-colors text-[11px] ${
                      disabled
                        ? 'opacity-30 cursor-not-allowed'
                        : isActive
                          ? 'bg-[#21262D] border border-[#FFB633]/30'
                          : 'hover:bg-[#21262D] border border-transparent'
                    }`}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                      isActive ? 'bg-[#FFB633]' : 'bg-transparent'
                    }`} />
                    <span className={`font-mono flex-1 truncate ${
                      disabled ? 'text-[#484F58]' : isActive ? 'text-[#E6EDF3]' : 'text-[#8B949E]'
                    }`}>
                      {model.id}
                    </span>
                    <span className={`text-[9px] tabular-nums flex-shrink-0 ${
                      disabled ? 'text-[#30363D]' : 'text-[#484F58]'
                    }`}>
                      {model.context_window >= 1_000_000
                        ? `${(model.context_window / 1_000_000).toFixed(1)}M`
                        : `${(model.context_window / 1_000).toFixed(0)}K`}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
