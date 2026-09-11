/**
 * Branch Costs — how much budget flowed through a parent AND its whole subtree.
 *
 * The Cost Explorer shows flat per-agent spend and the Topology view shows flat
 * per-parent delegation counts, but neither joins cost onto the delegation
 * tree. This view does: each row is an agent with its own cost, the cost of
 * everything beneath it, the task count of that subtree, and its depth.
 */
import { useMemo } from 'react'
import { agentColor, formatUSD, getBranchCosts } from './api'
import { Panel, Stat, ViewState, usePolled } from './shared'
import type { BranchCost } from './types'

export function BranchCosts() {
  const { data, error, loading, refresh } = usePolled(getBranchCosts, 20_000)

  const branches = useMemo(
    () => (data?.branches ?? []).sort((a, b) => b.subtree_cost_usd - a.subtree_cost_usd),
    [data],
  )

  const totalSubtree = useMemo(() => branches.reduce((s, b) => s + b.subtree_cost_usd, 0), [branches])
  const busiest = branches[0] ?? null

  return (
    <div className="flex flex-col gap-3 h-full min-h-0">
      <div className="flex flex-wrap gap-8 px-4 py-3 rounded border flex-shrink-0" style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-panel)' }}>
        <Stat label="Total subtree cost" value={formatUSD(totalSubtree)} tone="var(--color-accent)" />
        <Stat label="Branches" value={String(branches.length)} />
        <Stat
          label="Busiest branch"
          value={busiest ? `${busiest.agent} · ${formatUSD(busiest.subtree_cost_usd)}` : '—'}
        />
      </div>

      <Panel title="Cost by delegation subtree" subtitle="own vs. subtree — sorted by subtree cost">
        <ViewState
          loading={loading && !data}
          error={error}
          empty={branches.length === 0}
          emptyLabel="No task cost recorded yet."
          onRetry={refresh}
        />
        {branches.length > 0 && (
          <div className="overflow-auto max-h-full">
            <table className="w-full text-[13px] font-mono">
              <thead>
                <tr style={{ color: 'var(--color-text-muted)' }}>
                  <th className="text-left font-normal px-3 py-1.5">Agent</th>
                  <th className="text-right font-normal px-3 py-1.5">Own cost</th>
                  <th className="text-right font-normal px-3 py-1.5">Subtree cost</th>
                  <th className="text-right font-normal px-3 py-1.5">Tasks</th>
                  <th className="text-right font-normal px-3 py-1.5">Depth</th>
                  <th className="text-right font-normal px-3 py-1.5">Children</th>
                </tr>
              </thead>
              <tbody>
                {branches.map((b: BranchCost) => (
                  <tr key={b.agent} className="border-t" style={{ borderColor: 'var(--color-border-muted)' }}>
                    <td className="px-3 py-1.5 truncate max-w-[200px]">
                      <span className="inline-block w-2 h-2 rounded-full mr-2 align-middle" style={{ background: agentColor(b.agent) }} />
                      <span style={{ color: 'var(--color-text-primary)' }}>{b.agent}</span>
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums" style={{ color: 'var(--color-text-secondary)' }}>{formatUSD(b.own_cost_usd)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums" style={{ color: 'var(--color-accent)' }}>{formatUSD(b.subtree_cost_usd)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums" style={{ color: 'var(--color-text-secondary)' }}>{b.subtree_tasks}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums" style={{ color: 'var(--color-text-muted)' }}>{b.depth}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums" style={{ color: 'var(--color-text-muted)' }}>{b.direct_children.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}
