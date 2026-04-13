import { useState } from 'react'
import { restartAgent, pingAgent, type PingResult } from '../../api/agentStatusClient'

interface Props {
  agentName: string
  state: string
  onRefresh?: () => void
}

export function AgentActions({ agentName, state, onRefresh }: Props) {
  const [restarting, setRestarting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [isPinging, setIsPinging] = useState(false)
  const [pingResult, setPingResult] = useState<PingResult | null>(null)
  const [pingError, setPingError] = useState<string | null>(null)

  async function handleRestart() {
    if (!confirm(`Restart agent "${agentName}"?`)) return
    setRestarting(true)
    setError(null)
    try {
      await restartAgent(agentName)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRestarting(false)
    }
  }

  async function handlePing() {
    setIsPinging(true)
    setPingResult(null)
    setPingError(null)
    try {
      const result = await pingAgent(agentName)
      setPingResult(result)
      onRefresh?.()
    } catch (e) {
      setPingError((e as Error).message)
    } finally {
      setIsPinging(false)
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <button
          onClick={handleRestart}
          disabled={restarting}
          className="px-3 py-1.5 text-xs rounded-md bg-[#21262D] border border-[#30363D]
            text-[#8B949E] hover:text-[#E6EDF3] hover:border-[#484F58]
            disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {restarting ? 'Restarting…' : 'Restart'}
        </button>

        <button
          onClick={handlePing}
          disabled={isPinging}
          className="px-3 py-1.5 text-xs rounded-md bg-[#21262D] border border-[#30363D]
            text-[#8B949E] hover:text-[#E6EDF3] hover:border-[#484F58]
            disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isPinging ? '🏓 Pinging…' : '🏓 Ping'}
        </button>

        <div className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full ${
            state === 'running' || state === 'spawning' ? 'bg-[#FFB633] animate-pulse' :
            state === 'error' ? 'bg-[#F85149]' :
            state === 'idle' ? 'bg-[#484F58]' : 'bg-[#3FB950]'
          }`} />
          <span className="text-xs text-[#8B949E] capitalize">{state || 'unknown'}</span>
        </div>
      </div>

      {error && (
        <p className="text-xs text-[#F85149]">{error}</p>
      )}

      {pingResult && (
        <p className={`text-xs ${pingResult.alive ? 'text-[#3FB950]' : 'text-[#E3B341]'}`}>
          {pingResult.diagnostic}
        </p>
      )}

      {pingError && (
        <p className="text-xs text-[#F85149]">{pingError}</p>
      )}
    </div>
  )
}
