import { useEffect, useState } from 'react'
import { getAgentFiles, getAgentLive, readAgentFile } from '../../api/agentStatusClient'

interface Props {
  agentName: string
}

const FILE_COLORS: Record<string, string> = {
  'PROMPT.MD': 'border-blue-500/40 text-blue-400',
  'CONFIG.yaml': 'border-amber-500/40 text-amber-400',
  'MEMORY.MD': 'border-emerald-500/40 text-emerald-400',
  'NOTES.MD': 'border-purple-500/40 text-purple-400',
  'HEALTH.MD': 'border-red-500/40 text-red-400',
  'TASK.MD':   'border-cyan-500/40 text-cyan-400',
  'LIVE.MD':   'border-lime-500/40 text-lime-400',
  'CRASH.MD':  'border-red-600/40 text-red-500',
}

export function AgentFileViewer({ agentName }: Props) {
  const [files, setFiles] = useState<string[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [content, setContent] = useState<string>('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    getAgentFiles(agentName)
      .then(setFiles)
      .catch(() => setFiles([]))
    setSelected(null)
    setContent('')
  }, [agentName])

  useEffect(() => {
    if (!selected) { setContent(''); return }
    setLoading(true)
    const loader = selected === 'LIVE.MD'
      ? getAgentLive(agentName)
      : readAgentFile(agentName, selected)
    loader
      .then(setContent)
      .catch((e) => setContent(`Error: ${e instanceof Error ? e.message : String(e)}`))
      .finally(() => setLoading(false))
  }, [agentName, selected])

  useEffect(() => {
    if (selected !== 'LIVE.MD') return
    const id = setInterval(() => {
      getAgentLive(agentName)
        .then(setContent)
        .catch(() => {})
    }, 1000)
    return () => clearInterval(id)
  }, [agentName, selected])

  return (
    <div>
      {/* File tabs */}
      <div className="flex flex-wrap gap-1.5 mb-2">
        {files.map((f) => {
          const color = FILE_COLORS[f] || 'border-[#30363D] text-[#8B949E]'
          const isActive = selected === f
          return (
            <button
              key={f}
              onClick={() => setSelected((s) => (s === f ? null : f))}
              className={`px-2 py-0.5 text-[11px] font-mono rounded border transition-colors ${
                isActive
                  ? `${color} bg-[#21262D]`
                  : 'border-[#30363D] text-[#484F58] hover:text-[#8B949E] hover:border-[#484F58]'
              }`}
            >
              {f}
            </button>
          )
        })}
      </div>

      {/* Content */}
      {selected && (
        <div className="bg-[#0D1117] border border-[#21262D] rounded-lg overflow-hidden">
          <div className="flex items-center justify-between px-3 py-1.5 border-b border-[#21262D]">
            <span className="text-[11px] font-mono text-[#8B949E]">{selected}</span>
            <button
              onClick={() => {
                setLoading(true)
                const loader = selected === 'LIVE.MD'
                  ? getAgentLive(agentName)
                  : readAgentFile(agentName, selected)
                loader
                  .then(setContent)
                  .catch((e) => setContent(`Error: ${e instanceof Error ? e.message : String(e)}`))
                  .finally(() => setLoading(false))
              }}
              className="text-[10px] text-[#484F58] hover:text-[#8B949E] transition-colors"
            >
              {loading ? 'Loading...' : 'Refresh'}
            </button>
          </div>
          <div className="max-h-60 overflow-auto p-3">
            <pre className="text-[11px] font-mono text-[#8B949E] whitespace-pre-wrap break-words leading-relaxed">
              {content || <span className="text-[#484F58] italic">(empty)</span>}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}
