import { useState } from 'react'

interface SearchHit {
  id: number
  agent: string
  source: string
  content: string
  timestamp: string
  score: number
}

interface SearchResponse {
  query: string
  results: SearchHit[]
  total_indexed: number
}

interface SearchPanelProps {
  agent: string
  onClose: () => void
  onSelect: (hit: SearchHit) => void
}

const PALETTE: Record<string, string> = {
  master: 'text-purple-400',
  planning: 'text-blue-400',
  builder: 'text-green-400',
  keeper: 'text-yellow-400',
  cron: 'text-orange-400',
  doctor: 'text-red-400',
  model_manager: 'text-cyan-400',
  researcher: 'text-pink-400',
  shared: 'text-zinc-300',
}

function agentColor(name: string): string {
  return PALETTE[name] ?? 'text-zinc-400'
}

async function runSearch(q: string, agent: string): Promise<SearchResponse> {
  const params = new URLSearchParams({ q })
  if (agent) params.set('agent', agent)
  params.set('top_k', '20')
  const res = await fetch(`/api/memory/search?${params.toString()}`)
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}${detail ? `: ${detail}` : ''}`)
  }
  return res.json() as Promise<SearchResponse>
}

export function SearchPanel({ agent, onClose, onSelect }: SearchPanelProps) {
  const [query, setQuery] = useState('')
  const [data, setData] = useState<SearchResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e?: React.FormEvent<HTMLFormElement>) {
    e?.preventDefault()
    const q = query.trim()
    if (!q) return
    setLoading(true)
    setError(null)
    try {
      const r = await runSearch(q, agent)
      setData(r)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-full bg-zinc-950 text-zinc-100">
      <div className="flex items-center gap-3 px-4 py-2 border-b border-zinc-800 flex-shrink-0">
        <h2 className="text-[10px] uppercase tracking-widest text-zinc-500">
          Semantic Search
        </h2>
        <form onSubmit={submit} className="flex-1 flex items-center gap-2">
          <input
            autoFocus
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={
              agent
                ? `Search ${agent}'s memory… (natural language)`
                : 'Search all agent memory… (natural language)'
            }
            className="flex-1 bg-zinc-800 text-zinc-200 text-xs px-2 py-1 border border-zinc-700 focus:outline-none focus:border-[#FFB633] font-mono"
          />
          <button
            type="submit"
            disabled={loading || !query.trim()}
            className="px-3 py-1 text-[11px] font-mono uppercase tracking-wider border border-zinc-700 text-zinc-200 hover:text-[#FFB633] hover:border-[#FFB633] disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {loading ? 'Searching…' : 'Search'}
          </button>
        </form>
        <button
          onClick={onClose}
          className="px-2 py-1 text-[11px] font-mono uppercase tracking-wider border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500"
        >
          Close
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        {error && (
          <div className="mb-3 px-3 py-2 border border-red-700 bg-red-950/50 text-red-300 text-xs font-mono">
            {error}
          </div>
        )}

        {!data && !error && !loading && (
          <div className="text-zinc-500 text-xs font-mono">
            Try a natural-language query like &quot;what was decided about authentication&quot;
            or &quot;recent errors in builder&quot;. Hybrid keyword + semantic ranking.
          </div>
        )}

        {data && data.results.length === 0 && (
          <div className="text-zinc-500 text-xs font-mono">
            No matches for &quot;{data.query}&quot; across {data.total_indexed} indexed entries.
          </div>
        )}

        {data && data.results.length > 0 && (
          <div className="space-y-2">
            <div className="text-[11px] text-zinc-500 font-mono">
              {data.results.length} result{data.results.length === 1 ? '' : 's'} ·{' '}
              {data.total_indexed} indexed
            </div>
            {data.results.map((hit, i) => (
              <button
                key={hit.id}
                onClick={() => onSelect(hit)}
                className="block w-full text-left px-3 py-2 border border-zinc-800 bg-zinc-900 hover:border-[#FFB633]/60 hover:bg-zinc-900/80 transition-colors"
              >
                <div className="flex items-center gap-2 text-[11px] font-mono mb-1">
                  <span className="text-zinc-500">#{i + 1}</span>
                  <span className={agentColor(hit.agent)}>{hit.agent}</span>
                  <span className="text-zinc-600">/</span>
                  <span className="text-zinc-400">{hit.source}</span>
                  <span className="ml-auto text-zinc-600">
                    {hit.timestamp} · score {hit.score.toFixed(3)}
                  </span>
                </div>
                <div className="text-xs text-zinc-200 whitespace-pre-wrap break-words line-clamp-6">
                  {hit.content}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
