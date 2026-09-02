import { AgentAvatar, getAgentColor, getAgentDisplayName } from '../lib/agentIdentity'
import type { BackgroundTask } from '../store/wsStore'

/**
 * Rich "what just finished" card shown when a background task completes.
 *
 * Replaces the old ambiguous bare '_Task completed_' text that told the user
 * *something* finished but not *what*, *who*, or *how it went*. Renders from a
 * BackgroundTask-like model so it works for live WebSocket completions, for
 * recovered completions after a reconnect, and for finalised task groups.
 *
 * External shape (camelCase to mirror the WS payload era; the only snake kept
 * is `task_id` because BackgroundTask and the backend task_queue both use it):
 *   task: {
 *     task_id, status, prompt?, result?, error?, agent?, source?,
 *     completed_at?, started_at?, created_at?
 *   }
 * Every field is optional — the card still renders gracefully when the backend
 * (or the recovery path) could not attach a prompt or an agent, never leaving
 * an empty/ambiguous body.
 */
export interface TaskCompletionCardModel {
  task_id?: string
  status?: string
  prompt?: string
  result?: string
  error?: string
  agent?: string
  source?: string
  session_id?: string
  created_at?: string
  started_at?: string
  completed_at?: string
}

interface TaskCompletionCardProps {
  task: TaskCompletionCardModel | BackgroundTask
  /** Override the header title (used when surfacing a task-group completion). */
  title?: string
}

const SOURCE_LABELS: Record<string, string> = {
  resume: 'auto-resume',
  goal: 'goal',
  cron: 'scheduled',
  notification: 'notification',
  delegation: 'delegation',
}

function isErrorStatus(status?: string): boolean {
  const s = (status ?? '').toLowerCase()
  return s === 'error' || s === 'failed'
}

function isRunningStatus(status?: string): boolean {
  return (status ?? '').toLowerCase() === 'running'
}

function stripResumePrefix(text: string): string {
  return text.replace(/^\[Resume\]\s*/i, '')
}

function relativeTime(iso?: string, fallback?: string): string {
  if (iso) {
    const ms = Date.parse(iso)
    if (!Number.isNaN(ms)) {
      const diff = Math.max(0, Date.now() - ms)
      const s = Math.floor(diff / 1000)
      if (s < 60) return `${s}s ago`
      const m = Math.floor(s / 60)
      if (m < 60) return `${m}m ago`
      const h = Math.floor(m / 60)
      if (h < 24) return `${h}h ago`
      return `${Math.floor(h / 24)}d ago`
    }
  }
  return fallback ?? 'recently'
}

function formatSource(source?: string): string {
  const s = (source ?? '').toLowerCase()
  return SOURCE_LABELS[s] ?? (s ? s.replace(/_/g, ' ') : 'task')
}

/** Determine the best single body paragraph from the data we have. */
function bodySummary(task: TaskCompletionCardModel): string {
  const prompt = stripResumePrefix((task.prompt ?? '').trim())
  if (prompt) return prompt
  // No explicit prompt — try to say something concrete rather than nothing.
  const result = (task.result ?? '').trim()
  if (result) return result
  return ''
}

export function TaskCompletionCard({ task, title }: TaskCompletionCardProps) {
  const status = task.status ?? (task.error ? 'error' : 'done')
  const isError = isErrorStatus(status) || Boolean(task.error)
  const isRunning = !isError && isRunningStatus(status)

  const agent = (task.agent ?? '').trim() || 'master'
  const color = getAgentColor(agent)
  const agentName = getAgentDisplayName(agent)
  const source = formatSource(task.source)
  const ts = task.completed_at ?? task.created_at

  const body = bodySummary(task)
  const result = (task.result ?? '').trim()
  const error = (task.error ?? '').trim()

  const statusText = isRunning
    ? 'Running'
    : isError
      ? 'Failed'
      : 'Complete'

  return (
    <div
      className="rounded-xl border border-zinc-700/70 bg-zinc-900/70 my-2 overflow-hidden"
      data-testid="task-completion-card"
    >
      {/* Header row — agent identity + status glyph + completion time. */}
      <div className="flex items-center gap-2 px-3.5 py-2.5 border-b border-zinc-700/50">
        <AgentAvatar name={agent} size={20} />
        <div className="flex flex-col min-w-0 leading-tight">
          <span className="text-xs uppercase tracking-wide font-semibold" style={{ color }}>
            {agentName}
          </span>
          <span className="text-[11px] text-zinc-500">
            {source} · {relativeTime(ts)}
          </span>
        </div>

        <span
          className={`inline-flex items-center gap-1.5 ml-auto rounded-full border px-2 py-0.5 text-[11px] font-medium ${
            isRunning
              ? 'text-zinc-300 border-zinc-600'
              : isError
                ? 'text-red-300 border-red-500/50 bg-red-500/10'
                : 'text-green-300 border-green-500/50 bg-green-500/10'
          }`}
          style={isRunning ? { color: 'var(--color-accent, #FFB633)', borderColor: 'rgba(255,182,51,0.4)', background: 'rgba(255,182,51,0.08)' } : undefined}
        >
          {isRunning ? (
            <span className="animate-spin inline-block text-[11px] leading-none" aria-hidden>⟳</span>
          ) : isError ? (
            <span aria-hidden>!</span>
          ) : (
            <span aria-hidden>✓</span>
          )}
          {statusText}
        </span>
      </div>

      {/* Body — the actual task/description. */}
      <div className="px-3.5 py-2.5 space-y-2">
        {title && (
          <p className="text-zinc-100 text-sm font-medium leading-relaxed line-clamp-3 break-words whitespace-pre-wrap">
            {title}
          </p>
        )}
        {body && (
          <p className="text-zinc-200 text-sm leading-relaxed line-clamp-3 break-words whitespace-pre-wrap">
            {body}
          </p>
        )}
        {!body && (
          <p className="text-zinc-400 text-sm italic">
            Task completed — no description recorded for this run.
          </p>
        )}

        {/* Result / error panel. */}
        {!isRunning && error && (
          <div
            className="rounded-lg border border-red-500/40 bg-red-500/5 px-2.5 py-2 text-xs whitespace-pre-wrap break-words text-red-200"
            data-testid="task-error"
          >
            <span className="font-semibold uppercase tracking-wide text-[10px] text-red-300 block mb-0.5">
              Error
            </span>
            {error}
          </div>
        )}
        {!isRunning && !isError && result && (
          <div
            className="rounded-lg border border-zinc-700 bg-zinc-800/60 px-2.5 py-2 text-xs whitespace-pre-wrap break-words text-zinc-300"
            data-testid="task-result"
          >
            <span className="font-semibold uppercase tracking-wide text-[10px] text-zinc-500 block mb-0.5">
              Result
            </span>
            {result}
          </div>
        )}
      </div>
    </div>
  )
}
