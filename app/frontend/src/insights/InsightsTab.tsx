/**
 * Insights tab — the four analytical views that the Observability tab's
 * aggregate counters could never answer: where the money went, where the time
 * went, who delegates to whom, and what's failing together.
 */
import { useState } from 'react'
import { CostExplorer } from './CostExplorer'
import { DelegationTopology } from './DelegationTopology'
import { ErrorHeatmap } from './ErrorHeatmap'
import { TraceWaterfall } from './TraceWaterfall'

const VIEWS = [
  { id: 'cost', label: 'Cost', hint: 'Spend by agent and model' },
  { id: 'trace', label: 'Trace', hint: 'Task waterfall over time' },
  { id: 'topology', label: 'Topology', hint: 'Delegation graph' },
  { id: 'errors', label: 'Errors', hint: 'Cross-agent failure heatmap' },
] as const

type ViewId = (typeof VIEWS)[number]['id']

export function InsightsTab() {
  const [view, setView] = useState<ViewId>('cost')

  return (
    <div className="flex flex-col h-full min-h-0 p-3 gap-3" data-testid="insights-tab">
      <nav
        className="flex items-center gap-1 flex-shrink-0"
        role="tablist"
        aria-label="Insight views"
      >
        {VIEWS.map((v) => {
          const active = view === v.id
          return (
            <button
              key={v.id}
              role="tab"
              aria-selected={active}
              onClick={() => setView(v.id)}
              title={v.hint}
              className="text-[13px] font-mono uppercase tracking-[0.1em] px-3 py-1.5 rounded border transition-colors"
              style={{
                borderColor: active ? 'var(--color-accent)' : 'var(--color-border)',
                color: active ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                background: active ? 'var(--color-bg-tertiary)' : 'transparent',
              }}
            >
              {v.label}
            </button>
          )
        })}
        <span className="ml-auto text-[12px] font-mono" style={{ color: 'var(--color-text-muted)' }}>
          {VIEWS.find((v) => v.id === view)?.hint}
        </span>
      </nav>

      <div className="flex-1 min-h-0">
        {view === 'cost' && <CostExplorer />}
        {view === 'trace' && <TraceWaterfall />}
        {view === 'topology' && <DelegationTopology />}
        {view === 'errors' && <ErrorHeatmap />}
      </div>
    </div>
  )
}
