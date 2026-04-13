import { useState, useEffect } from 'react'

interface Agent {
  name: string
  process_state: string
}

interface Props {
  currentAgent: string | null
  onAssign: (agentName: string) => Promise<void>
  disabled?: boolean
}

export function AssignAgentSelect({ currentAgent, onAssign, disabled }: Props) {
  const [agents, setAgents] = useState<Agent[]>([])
  const [selected, setSelected] = useState(currentAgent ?? '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/agents')
      .then((r) => r.json())
      .then((data: Agent[]) => {
        const infra = ['base', 'doctor', 'model_manager']
        setAgents(data.filter((a) => !infra.includes(a.name)))
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    setSelected(currentAgent ?? '')
  }, [currentAgent])

  async function handleAssign() {
    if (!selected) return
    setLoading(true)
    setError(null)
    try {
      await onAssign(selected)
    } catch (err: any) {
      setError(err.message ?? 'Assignment failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <label className="text-[#8B949E] text-xs font-medium">Assigned Agent</label>
      <div className="flex gap-2">
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          disabled={disabled || loading}
          className="flex-1 bg-[#21262D] text-[#E6EDF3] text-xs rounded px-2 py-1.5 border border-[#30363D] focus:outline-none focus:border-[#FFB633]"
        >
          <option value="">— select agent —</option>
          {agents.map((a) => (
            <option key={a.name} value={a.name}>
              {a.name} ({a.process_state || 'unknown'})
            </option>
          ))}
        </select>
        <button
          onClick={handleAssign}
          disabled={!selected || loading || disabled}
          className="px-3 py-1.5 rounded bg-[#1F6FEB] text-white text-xs font-medium hover:bg-[#388BFD] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? '…' : 'Assign'}
        </button>
      </div>
      {error && <span className="text-[#F85149] text-[11px]">{error}</span>}
      {currentAgent && (
        <span className="text-[#3FB950] text-[11px]">
          Currently assigned to <strong>{currentAgent}</strong>
        </span>
      )}
    </div>
  )
}
