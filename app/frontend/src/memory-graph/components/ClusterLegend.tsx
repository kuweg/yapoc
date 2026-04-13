import type { ClusterInfo } from '../types'

interface Props {
  clusters: ClusterInfo[]
}

export function ClusterLegend({ clusters }: Props) {
  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-[10px] uppercase tracking-widest text-zinc-500 mb-1">
        Clusters
      </h3>
      {clusters.map((c) => (
        <div key={c.id} className="flex items-center gap-2 text-xs">
          <span
            className="inline-block w-3 h-3 rounded-full flex-shrink-0"
            style={{ backgroundColor: c.color }}
          />
          <span className="text-zinc-300 truncate" title={c.label}>
            {c.label}
          </span>
          <span className="text-zinc-500 ml-auto flex-shrink-0">{c.count}</span>
        </div>
      ))}
    </div>
  )
}
