import { useTaskProgressStore } from '../store/taskProgressStore'
import type { StructuredTaskResult } from '../api/types'

/** Runtime evidence stays separate from the agent's answer and completion claim. */
export function StructuredResultCard({ result: r }: { result: StructuredTaskResult }) {
  const live = useTaskProgressStore(s => s.byId[r.task_id])
  const progress = live ?? r.progress
  if (r.schema_version !== 1) return <p>Unsupported task result version.</p>
  const count = (n: number | null) => n == null ? '—' : n.toLocaleString()
  return (
    <details className="my-3 rounded-lg border border-zinc-700 p-3 text-xs" data-testid="structured-result-card" onClick={e => e.stopPropagation()}>
      <summary className="cursor-pointer flex-wrap text-zinc-300">
        <strong>Task result · {progress?.state ?? r.status}</strong>
        <span className="ml-3 text-zinc-400">Command checks: {r.verification_status.replace(/_/g, ' ')}</span>
      </summary>
      <div className="mt-3 space-y-3 min-w-0 break-words">
        <p className="whitespace-pre-wrap">{r.summary}</p>
        {progress && <p>{progress.next_action}</p>}
        {r.changes.files.length > 0 && <div><strong>Observed file changes</strong><ul>{r.changes.files.map(f => <li key={f} className="font-mono break-all">{f}</li>)}</ul></div>}
        {r.verification.length > 0 && <div><strong>Command evidence</strong><ul className="space-y-2 mt-1">{r.verification.map(v => <li key={v.evidence_event_seq}>
          <code className="block whitespace-pre-wrap">{v.command}</code>
          <span>{v.status} · exit {v.exit_code ?? 'unknown'} · </span>
          <a className="underline" href={`/api/tasks/${encodeURIComponent(r.task_id)}/evidence/${v.evidence_event_seq}`} target="_blank" rel="noreferrer">View log</a>
        </li>)}</ul></div>}
        {r.artifacts.length > 0 && <div><strong>Artifacts</strong><ul>{r.artifacts.map(a => <li key={a.id}><a className="underline" href={`/api/artifacts/${encodeURIComponent(a.id)}/download`}>{a.name}</a> · {a.type}</li>)}</ul></div>}
        <p title={r.usage.scope}>{count(r.usage.input_tokens)} input tokens · {count(r.usage.output_tokens)} output tokens · {r.usage.estimated_cost_usd == null ? 'Cost unknown' : `≈$${r.usage.estimated_cost_usd.toFixed(4)}`}</p>
        <p className="text-zinc-500">{r.usage.scope}</p>
        <ul className="text-zinc-500 space-y-1">{r.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>
        <a className="underline" download={`task-${r.task_id}.json`} href={`data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(r, null, 2))}`}>Download result JSON</a>
      </div>
    </details>
  )
}
