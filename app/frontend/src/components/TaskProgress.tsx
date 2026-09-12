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

/** "2m 14s" — the mission bar reads at a glance, so no leading zero minutes. */
export function formatElapsed(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return ''
  const total = Math.floor(ms / 1000)
  const [h, m, s] = [Math.floor(total / 3600), Math.floor(total / 60) % 60, total % 60]
  if (h) return `${h}h ${String(m).padStart(2, '0')}m`
  if (m) return `${m}m ${String(s).padStart(2, '0')}s`
  return `${s}s`
}

const displayName = (name: string) => name.charAt(0).toUpperCase() + name.slice(1).replace(/[-_]/g, ' ')

/** Agents this task is actually staffed by: delegated children, else its own assignee. */
function taskAgents(task: QueuedTask): string[] {
  const waiting = task.progress?.waiting_on ?? []
  return waiting.length ? waiting : task.assigned_agent ? [task.assigned_agent] : []
}

/** Ticks once a second so elapsed time advances between the 5s task polls. */
function useNow(enabled: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!enabled) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [enabled])
  return now
}

/**
 * Live runtime state per agent, keyed by name. `runtime_state` is only 'running'
 * when the agent has a live PID and a STATUS.json that isn't stale, so an agent
 * that finished (or died with the server) stops being reported as busy — which a
 * task's own `waiting_on` list cannot tell us on its own.
 */
function useAgentRuntime(enabled: boolean): Record<string, string> {
  const [states, setStates] = useState<Record<string, string>>({})
  useEffect(() => {
    if (!enabled) { setStates({}); return }
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    const controller = new AbortController()
    const refresh = async () => {
      try {
        if (!document.hidden) {
          const response = await fetch('/api/agents', { signal: controller.signal })
          if (response.ok) {
            const rows: { name: string; runtime_state?: string }[] = await response.json()
            if (!stopped) setStates(Object.fromEntries(rows.map(r => [r.name, r.runtime_state ?? 'unknown'])))
          }
        }
      } catch { /* keep the last known roster; the task poll drives the bar */ }
      if (!stopped) timer = setTimeout(refresh, 5000)
    }
    void refresh()
    return () => { stopped = true; clearTimeout(timer); controller.abort() }
  }, [enabled])
  return states
}

export function TaskProgressPanel({ conversation = false, active = true }: { conversation?: boolean; active?: boolean }) {
  const sessionId = useSessionStore(s => s.activeId)
  const [tasks, setTasks] = useState<QueuedTask[]>([])
  const [error, setError] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [stopping, setStopping] = useState<Record<string, boolean>>({})
  const [stopError, setStopError] = useState('')
  useEffect(() => { setExpanded(false); setTasks([]); setError(false); setStopping({}); setStopError('') }, [sessionId])
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
  const runtime = useAgentRuntime(active && visible.length > 0)
  const now = useNow(active && visible.length > 0)
  // Hooks above must run every render; only bail out afterwards.
  if (!active || (!visible.length && !error)) return null

  const unknown = visible.some(task => task.progress!.state === 'unknown')
  const needsAttention = visible.some(task => ['blocked', 'failed', 'interrupted'].includes(task.progress!.state))
  const alert = needsAttention || error || unknown
  // The mission is whichever task is actually executing; otherwise the newest.
  const primary = visible.find(task => task.progress!.state === 'running') ?? visible[0]
  const goal = primary ? title(primary) : ''
  const startedAt = primary?.started_at || primary?.created_at
  const elapsed = startedAt ? formatElapsed(now - new Date(startedAt).getTime()) : ''
  // Only agents the runtime confirms are alive — a finished agent stays listed
  // in waiting_on, and reporting it as "working" is the bug this replaces.
  const working = [...new Set(visible.flatMap(taskAgents))].filter(name => runtime[name] === 'running')
  const staffed = [...new Set(visible.flatMap(taskAgents))]

  const status = error ? 'Reconnecting' : needsAttention ? 'Needs attention' : unknown ? 'Status unavailable'
    : working.length ? `${working.map(displayName).join(', ')} working`
    : visible.every(task => task.progress!.state === 'queued') ? 'Queued'
    : visible.some(task => task.progress!.state === 'waiting') ? 'Waiting for results'
    : 'Working'

  async function stop(task: QueuedTask) {
    setStopping(s => ({ ...s, [task.id]: true })); setStopError('')
    try {
      const response = await fetch(`/api/tasks/${encodeURIComponent(task.id)}/cancel`, { method: 'POST' })
      if (!response.ok) throw new Error()
      // Drop it immediately; the next poll confirms.
      setTasks(rows => rows.filter(row => row.id !== task.id))
    } catch {
      setStopError('Could not stop the task. It may have already finished.')
      setStopping(s => ({ ...s, [task.id]: false }))
    }
  }

  return <section aria-label="Mission status" data-testid="mission-bar" className="shrink-0 border-b border-zinc-800/60 px-4 sm:px-6">
    <div className="flex min-h-11 w-full items-center gap-2.5 text-xs">
      {alert
        ? <CircleAlert size={14} className="shrink-0 text-amber-300" />
        : <LoaderCircle size={14} className="shrink-0 text-emerald-300 motion-safe:animate-spin" />}
      <button type="button" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}
        className="flex min-w-0 flex-1 items-center gap-2 rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400">
        {goal && <span className="truncate font-medium text-zinc-200" title={goal}>{goal}</span>}
        <span className={`shrink-0 whitespace-nowrap ${alert ? 'text-amber-300' : 'text-zinc-400'}`}>
          {goal && <span className="text-zinc-600"> · </span>}{status}
        </span>
        {elapsed && !alert && <span className="shrink-0 tabular-nums text-zinc-500" title={`Started ${new Date(startedAt!).toLocaleString()}`}>· {elapsed}</span>}
        {visible.length > 1 && <span className="shrink-0 rounded-full bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400">+{visible.length - 1}</span>}
        <span className="ml-auto hidden shrink-0 text-zinc-500 sm:block">{expanded ? 'Hide details' : 'Details'}</span>
        <ChevronDown size={14} className={`shrink-0 text-zinc-500 transition-transform ${expanded ? 'rotate-180' : ''}`} />
      </button>
      {primary && !['unknown', 'queued'].includes(primary.progress!.state) && <button type="button" onClick={() => void stop(primary)}
        disabled={!!stopping[primary.id]}
        className="shrink-0 rounded border border-zinc-700 px-2 py-1 text-zinc-300 hover:border-amber-400/60 hover:text-amber-200 disabled:opacity-50">
        {stopping[primary.id] ? 'Stopping…' : 'Stop'}
      </button>}
    </div>
    {stopError && <p role="alert" className="pb-2 text-xs text-amber-300">{stopError}</p>}
    {expanded && <div className="max-h-56 space-y-2 overflow-y-auto pb-3">
      {error && <p className="text-xs text-zinc-400">Showing the last update. Reconnecting automatically.</p>}
      {staffed.length > 0 && <p className="text-xs text-zinc-500">
        Agents: {staffed.map(name => `${displayName(name)} (${runtime[name] === 'running' ? 'running' : runtime[name] === 'idle' ? 'finished' : 'status unknown'})`).join(' · ')}
      </p>}
      {visible.map(task => <div key={task.id} className="rounded-lg border border-zinc-800/70 bg-zinc-900/40 px-3 py-2.5">
        <p className="mb-1 truncate text-xs font-medium text-zinc-200" title={title(task)}>{title(task)}</p>
        {['blocked', 'failed', 'interrupted'].includes(task.progress!.state)
          ? <TaskProgressDetails task={task} />
          : <p className="text-xs text-zinc-500">{task.progress!.state === 'unknown' ? 'No current run or confirmed completion was found. Check retained results in Tasks.' : task.progress!.state === 'queued' ? 'Waiting to start' : task.progress!.state === 'waiting' ? 'Waiting for the delegated result to be processed.' : 'Working in the background. Results will appear here.'}</p>}
      </div>)}
    </div>}
  </section>
}
