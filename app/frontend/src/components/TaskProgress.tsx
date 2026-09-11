import { useTaskProgressStore } from '../store/taskProgressStore'
import { useEffect, useState } from 'react'
import { ChevronDown, CircleAlert, LoaderCircle } from 'lucide-react'
import type { QueuedTask } from '../api/client'
import { useSessionStore } from '../store/session'

export function TaskProgressDetails({ task }: { task: QueuedTask }) {
  const [resuming, setResuming] = useState(false)
  const [resumeError, setResumeError] = useState('')
  async function resume() {
    setResuming(true); setResumeError('')
    try {
      const response = await fetch(`/api/tasks/${encodeURIComponent(task.id)}/recover`, { method: 'POST' })
      if (!response.ok) throw new Error()
    } catch { setResumeError('Could not resume. Refresh task status and try again.'); setResuming(false) }
  }
  const p = task.progress
  if (!p) return null
  return <div className="text-xs text-zinc-400 space-y-1" data-testid="task-progress">
    <div><strong className="text-emerald-300 capitalize">{p.state}</strong>{p.waiting_on.length > 0 && ` · ${p.waiting_on.join(', ')}`}</div>
    <div>{p.last_activity}{p.last_activity_at && <> · <time dateTime={p.last_activity_at}>{new Date(p.last_activity_at).toLocaleString()}</time></>}</div>
    <div>{p.next_action}{p.recovery_count > 0 && ` · Recovered ${p.recovery_count} time(s)`}</div>
    {(['interrupted', 'blocked', 'error', 'timeout', 'failed'].includes(task.status) || p.state === 'blocked') && <button className="rounded border border-zinc-700 px-2 py-1 text-emerald-300" disabled={resuming} onClick={e => { e.stopPropagation(); void resume() }}>{resuming ? 'Resuming…' : 'Resume from checkpoint'}</button>}
    {resumeError && <p role="alert">{resumeError}</p>}
  </div>
}

export function TaskProgressPanel({ conversation = false, active = true }: { conversation?: boolean; active?: boolean }) {
  const sessionId = useSessionStore(s => s.activeId)
  const [tasks, setTasks] = useState<QueuedTask[]>([])
  const [error, setError] = useState(false)
  const [expanded, setExpanded] = useState(false)
  useEffect(() => { setExpanded(false); setTasks([]); setError(false) }, [sessionId])
  useEffect(() => {
    if (!active || (conversation && !sessionId)) { setTasks([]); return }
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    const controller = new AbortController()
    const refresh = async () => {
      try {
        if (!document.hidden) {
          const query = new URLSearchParams({ limit: '30' })
          if (conversation && sessionId) query.set('session_id', sessionId)
          const response = await fetch(`/api/tasks?${query}`, { signal: controller.signal })
          if (!response.ok) throw new Error('unavailable')
          const rows: QueuedTask[] = await response.json()
          if (!stopped) { setTasks(rows); useTaskProgressStore.getState().ingest(rows); setError(false) }
        }
      } catch { if (!stopped) setError(true) }
      if (!stopped) timer = setTimeout(refresh, 5000)
    }
    void refresh()
    return () => { stopped = true; clearTimeout(timer); controller.abort() }
  }, [active, conversation, sessionId])
  // Continuation prompts repeat the user's request followed by orchestration
  // instructions. Display only the request, and fold repeated handoffs together.
  const title = (task: QueuedTask) => task.prompt
    .replace(/^Original user request:\s*/i, '')
    .split(/\s+You stopped waiting for /i)[0].trim() || 'Background task'
  const unique = new Map<string, QueuedTask>()
  for (const task of tasks) {
    if (!task.progress || ['completed', 'cancelled'].includes(task.progress.state)) continue
    const key = `${title(task)}:${task.progress.state}:${[...task.progress.waiting_on].sort().join(',')}`
    if (!unique.has(key)) unique.set(key, task)
  }
  const visible = [...unique.values()]
  if (!active || (!visible.length && !error)) return null
  const unknown = visible.some(task => task.progress!.state === 'unknown')
  const needsAttention = visible.some(task => ['blocked', 'failed', 'interrupted'].includes(task.progress!.state))
  const agents = [...new Set(visible.flatMap(task => task.progress!.waiting_on.length
    ? task.progress!.waiting_on : task.assigned_agent ? [task.assigned_agent] : []))]
  const label = error ? 'Reconnecting to task updates' : needsAttention ? 'Task needs attention' : unknown ? 'Past task status unavailable'
    : visible.every(task => task.progress!.state === 'queued') ? 'Task queued'
    : visible.some(task => task.progress!.state === 'waiting') ? 'Waiting for task results'
    : agents.length === 1 ? `${agents[0].charAt(0).toUpperCase()}${agents[0].slice(1)} is working` : 'Work in progress'
  return <section aria-label="Task progress" className="shrink-0 border-b border-zinc-800/60 px-4 sm:px-6">
    <button type="button" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}
      className="flex min-h-11 w-full items-center gap-2.5 rounded text-left text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400">
      {needsAttention || error || unknown
        ? <CircleAlert size={14} className="shrink-0 text-amber-300" />
        : <LoaderCircle size={14} className="shrink-0 text-emerald-300 motion-safe:animate-spin" />}
      <span className={needsAttention || error || unknown ? 'text-amber-300' : 'text-zinc-300'}>{label}</span>
      {visible.length > 1 && <span className="rounded-full bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400">{visible.length}</span>}
      <span className="ml-auto hidden text-zinc-500 sm:block">{expanded ? 'Hide details' : 'Details'}</span>
      <ChevronDown size={14} className={`shrink-0 text-zinc-500 transition-transform ${expanded ? 'rotate-180' : ''}`} />
    </button>
    {expanded && <div className="max-h-56 space-y-2 overflow-y-auto pb-3">
      {error && <p className="text-xs text-zinc-400">Showing the last update. Reconnecting automatically.</p>}
      {visible.map(task => <div key={task.id} className="rounded-lg border border-zinc-800/70 bg-zinc-900/40 px-3 py-2.5">
        <p className="mb-1 truncate text-xs font-medium text-zinc-200" title={title(task)}>{title(task)}</p>
        {['blocked', 'failed', 'interrupted'].includes(task.progress!.state)
          ? <TaskProgressDetails task={task} />
          : <p className="text-xs text-zinc-500">{task.progress!.state === 'unknown' ? 'No current run or confirmed completion was found. Check retained results in Tasks.' : task.progress!.state === 'queued' ? 'Waiting to start' : task.progress!.state === 'waiting' ? 'Waiting for the delegated result to be processed.' : 'Working in the background. Results will appear here.'}</p>}
      </div>)}
    </div>}
  </section>
}
