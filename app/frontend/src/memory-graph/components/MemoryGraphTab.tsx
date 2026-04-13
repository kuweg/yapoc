import { useEffect, useState } from 'react'
import type { GraphPoint, GraphResponse } from '../types'
import { ClusterLegend } from './ClusterLegend'
import { EntryModal } from './EntryModal'
import { ScatterPlot } from './ScatterPlot'

async function fetchGraph(agent: string, source: string): Promise<GraphResponse> {
  const params = new URLSearchParams()
  if (agent) params.set('agent', agent)
  if (source) params.set('source', source)
  const qs = params.size ? '?' + params.toString() : ''
  const res = await fetch(`/api/memory/graph${qs}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json() as Promise<GraphResponse>
}

export function MemoryGraphTab() {
  const [data, setData] = useState<GraphResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [agent, setAgent] = useState('')
  const [source, setSource] = useState('')
  const [selected, setSelected] = useState<GraphPoint | null>(null)

  const load = (ag: string, src: string) => {
    setLoading(true)
    setError(null)
    fetchGraph(ag, src)
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load(agent, source) }, [agent, source])

  const knownAgents = data
    ? [...new Set(data.points.map((p) => p.agent))].sort()
    : []

  return (
    <div className="flex flex-col h-full bg-zinc-950 text-zinc-100 overflow-hidden">
      {/* Controls bar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-zinc-800 flex-shrink-0">
        <h2 className="text-[10px] uppercase tracking-widest text-zinc-500">Memory Graph</h2>

        <select
          value={agent}
          onChange={(e) => setAgent(e.target.value)}
          className="bg-zinc-800 text-zinc-200 text-xs rounded px-2 py-1 border border-zinc-700 focus:outline-none"
        >
          <option value="">All agents</option>
          {knownAgents.map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>

        <select
          value={source}
          onChange={(e) => setSource(e.target.value)}
          className="bg-zinc-800 text-zinc-200 text-xs rounded px-2 py-1 border border-zinc-700 focus:outline-none"
        >
          <option value="">All sources</option>
          <option value="MEMORY.MD">MEMORY.MD</option>
          <option value="NOTES.MD">NOTES.MD</option>
        </select>

        {data && (
          <span className="text-xs text-zinc-500 ml-auto">
            {data.points.length} shown · {data.total} total
          </span>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-hidden relative">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center text-xs text-zinc-500 animate-pulse">
            Loading…
          </div>
        )}

        {!loading && error && (
          <div className="absolute inset-0 flex items-center justify-center gap-2 text-xs text-red-400">
            <span>{error}</span>
            <button
              onClick={() => load(agent, source)}
              className="text-blue-400 hover:underline"
            >
              Retry
            </button>
          </div>
        )}

        {!loading && !error && data && data.points.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-xs text-zinc-500">
            No entries indexed yet. Run the indexer first.
          </div>
        )}

        {!loading && !error && data && data.points.length > 0 && (
          <div className="flex h-full gap-0">
            {/* Scatter plot — fills available space */}
            <div className="flex-1 p-4 overflow-hidden">
              <ScatterPlot
                points={data.points}
                clusters={data.clusters}
                onSelect={setSelected}
              />
            </div>

            {/* Cluster legend sidebar */}
            <div className="w-52 flex-shrink-0 p-4 border-l border-zinc-800 overflow-y-auto">
              <ClusterLegend clusters={data.clusters} />
            </div>
          </div>
        )}
      </div>

      {/* Entry modal */}
      {selected && (
        <EntryModal entry={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}
