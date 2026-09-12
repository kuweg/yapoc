import { useState } from 'react'
import { CheckCircle2, CircleAlert, CircleHelp, FileDiff, MessageSquarePlus } from 'lucide-react'
import { useFileViewerStore } from '../store/fileViewerStore'
import { ArtifactStrip } from '../artifacts/ArtifactStrip'
import type { Artifact } from '../artifacts/types'
import { useTaskProgressStore } from '../store/taskProgressStore'
import { useSessionStore } from '../store/session'
import type { StructuredTaskResult } from '../api/types'

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** Runtime evidence stays separate from the agent's answer and completion claim. */
export function StructuredResultCard({ result: r, artifacts }: { result: StructuredTaskResult; artifacts?: Artifact[] }) {
  const live = useTaskProgressStore(s => s.byId[r.task_id])
  const [showChanges, setShowChanges] = useState(false)
  const progress = live ?? r.progress
  if (r.schema_version !== 1) return <p>Unsupported task result version.</p>
  const count = (n: number | null) => n == null ? '—' : n.toLocaleString()

  const files = r.changes.files
  const failed = r.verification.filter(v => v.status === 'failed')
  const passed = r.verification.filter(v => v.status === 'passed')
  const state = progress?.state ?? r.status
  const running = ['running', 'queued', 'waiting'].includes(state)
  // Checks describe commands that ran, which is not the same as the task being
  // right — the wording stays deliberately narrow.
  const checks = r.verification_status === 'checks_passed' ? { tone: 'ok' as const, text: `${plural(passed.length, 'check')} passed` }
    : r.verification_status === 'failed' ? { tone: 'bad' as const, text: `${failed.length} of ${plural(r.verification.length, 'check')} failed` }
    : r.verification_status === 'unknown' ? { tone: 'warn' as const, text: 'Checks inconclusive' }
    : { tone: 'warn' as const, text: 'No checks run' }
  const tone = checks.tone === 'ok' ? 'text-emerald-300' : checks.tone === 'bad' ? 'text-red-300' : 'text-zinc-400'
  const Icon = checks.tone === 'ok' ? CheckCircle2 : checks.tone === 'bad' ? CircleAlert : CircleHelp

  function inspect() {
    setShowChanges(open => !open)
    if (!showChanges && files.length === 1) useFileViewerStore.getState().selectFile({ path: files[0], name: files[0].split('/').pop() })
  }
  function continueTask() {
    useSessionStore.getState().setPendingChatInput(`Continue the previous task: ${r.summary.slice(0, 300)}`)
  }

  return (
    <section className="my-3 rounded-lg border border-zinc-700 p-3 text-xs" data-testid="structured-result-card" onClick={e => e.stopPropagation()}>
      <header className="flex flex-wrap items-center gap-2 text-zinc-300">
        <strong>Task result · {state}</strong>
      </header>
      <div className="mt-3 space-y-3 min-w-0 break-words">
        {/* Changes and checks, at a glance — the detail stays one click away. */}
        <div className={`flex flex-wrap items-center gap-x-2 gap-y-1 ${tone}`} data-testid="result-checks">
          <Icon size={13} className="shrink-0" />
          <span>{checks.text}</span>
          <span className="text-zinc-600">·</span>
          <span className="text-zinc-400">{files.length ? plural(files.length, 'file') + ' changed' : 'No file changes recorded'}</span>
          {r.artifacts.length > 0 && <><span className="text-zinc-600">·</span><span className="text-zinc-400">{plural(r.artifacts.length, 'artifact')}</span></>}
        </div>

        {/* The one thing left unresolved, surfaced rather than buried in evidence. */}
        {failed.length > 0 && <ul className="space-y-1 rounded border border-red-500/40 bg-red-500/5 p-2" data-testid="result-failed-checks">
          {failed.map(v => <li key={v.evidence_event_seq} className="flex flex-wrap items-baseline gap-x-2">
            <code className="break-all text-red-200">{v.command}</code>
            <span className="text-red-300/80">exit {v.exit_code ?? 'unknown'}</span>
            <a className="underline" href={`/api/tasks/${encodeURIComponent(r.task_id)}/evidence/${v.evidence_event_seq}`} target="_blank" rel="noreferrer">View log</a>
          </li>)}
        </ul>}
        {!running && progress && ['blocked', 'failed', 'interrupted', 'unknown'].includes(state) &&
          <p className="text-amber-300" data-testid="result-next-action">{progress.next_action}</p>}

        {/* Full artifact records provide image thumbnails, Preview and Download. */}
        <ArtifactStrip artifacts={artifacts} />

        {/* Actions — inspect what changed, or keep the work going. */}
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={inspect} disabled={!files.length} aria-expanded={showChanges}
            data-testid="inspect-changes"
            className="inline-flex items-center gap-1.5 rounded border border-zinc-700 px-2 py-1 text-zinc-300 hover:border-emerald-400/60 hover:text-emerald-200 disabled:opacity-40 disabled:hover:border-zinc-700 disabled:hover:text-zinc-300">
            <FileDiff size={13} />{showChanges ? 'Hide changes' : 'Inspect changes'}
          </button>
          {!running && <button type="button" onClick={continueTask} data-testid="continue-task"
            className="inline-flex items-center gap-1.5 rounded border border-zinc-700 px-2 py-1 text-zinc-300 hover:border-emerald-400/60 hover:text-emerald-200">
            <MessageSquarePlus size={13} />Continue
          </button>}
        </div>

        {showChanges && files.length > 0 && <div data-testid="changed-files">
          <strong>Observed file changes</strong>
          <ul>{files.map(f => <li key={f} className="font-mono break-all">
            <button className="text-emerald-300 underline" onClick={() => useFileViewerStore.getState().selectFile({ path: f, name: f.split('/').pop() })}>{f}</button>
          </li>)}</ul>
        </div>}

        <details><summary className="cursor-pointer text-zinc-400">Evidence and usage details</summary>
        {progress && <p className="mt-1">{progress.next_action}</p>}
        {r.verification.length > 0 && <div><strong>Command evidence</strong><ul className="space-y-2 mt-1">{r.verification.map(v => <li key={v.evidence_event_seq}>
          <code className="block whitespace-pre-wrap">{v.command}</code>
          <span>{v.status} · exit {v.exit_code ?? 'unknown'} · </span>
          <a className="underline" href={`/api/tasks/${encodeURIComponent(r.task_id)}/evidence/${v.evidence_event_seq}`} target="_blank" rel="noreferrer">View log</a>
        </li>)}</ul></div>}
        <p title={r.usage.scope}>{count(r.usage.input_tokens)} input tokens · {count(r.usage.output_tokens)} output tokens · {r.usage.estimated_cost_usd == null ? 'Cost unknown' : `≈$${r.usage.estimated_cost_usd.toFixed(4)}`}</p>
        <p className="text-zinc-500">{r.usage.scope}</p>
        <ul className="text-zinc-500 space-y-1">{r.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>
        <a className="underline" download={`task-${r.task_id}.json`} href={`data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(r, null, 2))}`}>Download result JSON</a>
        </details>
      </div>
    </section>
  )
}
