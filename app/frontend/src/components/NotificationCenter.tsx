/**
 * Unified Notification Centre.
 *
 * Three feeds used to live in three separate corners of the app — the
 * notification trace panel, the stale-tasks panel, and whatever Doctor wrote
 * into an agent's health log. A person watching a run had to know which corner
 * to look in. This merges them into one inbox with severity grouping, filters
 * and read state.
 */
import { useEffect, useMemo, useState } from 'react'
import { useWsStore } from '../store/wsStore'
import { getNotificationTrace, getObservability, getStaleTasks, relativeTime } from '../insights/api'
import { usePolled } from '../insights/shared'

type Severity = 'critical' | 'warning' | 'info'
type Source = 'error' | 'stale' | 'handoff' | 'task'

interface Item {
  id: string
  severity: Severity
  source: Source
  title: string
  detail?: string
  agent?: string
  ts: string
}

const SEVERITY_TONE: Record<Severity, string> = {
  critical: 'var(--color-error)',
  warning: 'var(--color-warning)',
  info: 'var(--color-info)',
}

const SOURCE_LABEL: Record<Source, string> = {
  error: 'error',
  stale: 'stale task',
  handoff: 'handoff',
  task: 'task',
}

const READ_KEY = 'yapoc-notifications-read'

function loadRead(): Set<string> {
  try {
    const raw = localStorage.getItem(READ_KEY)
    return new Set<string>(raw ? (JSON.parse(raw) as string[]) : [])
  } catch {
    return new Set()
  }
}

export function NotificationCenter({ open, onClose }: { open: boolean; onClose: () => void }) {
  const obs = usePolled(getObservability, 20_000, open)
  const stale = usePolled(getStaleTasks, 20_000, open)
  const trace = usePolled(getNotificationTrace, 20_000, open)
  const unread = useWsStore((s) => s.unreadNotifications)

  const [read, setRead] = useState<Set<string>>(loadRead)
  const [filter, setFilter] = useState<Severity | 'all'>('all')

  useEffect(() => {
    try {
      localStorage.setItem(READ_KEY, JSON.stringify([...read]))
    } catch {
      /* private mode / blocked storage — read state is a convenience, not state we depend on */
    }
  }, [read])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const items = useMemo<Item[]>(() => {
    const out: Item[] = []

    for (const e of obs.data?.recent_errors ?? []) {
      out.push({
        id: `err:${e.agent}:${e.timestamp}:${e.message.slice(0, 40)}`,
        severity: 'critical',
        source: 'error',
        title: `${e.agent} reported an error`,
        detail: e.message,
        agent: e.agent,
        ts: e.timestamp,
      })
    }

    for (const t of stale.data?.stale_tasks ?? []) {
      out.push({
        id: `stale:${t.agent}:${t.task_id ?? ''}`,
        severity: 'warning',
        source: 'stale',
        title: `${t.agent} has a task past the ${stale.data?.threshold_seconds ?? 600}s threshold`,
        detail: t.task_summary,
        agent: t.agent,
        ts: new Date(Date.now() - (t.age_seconds ?? 0) * 1000).toISOString(),
      })
    }

    for (const n of unread) {
      out.push({
        id: `task:${n.task_id}`,
        severity: n.status === 'error' ? 'critical' : 'info',
        source: 'task',
        title: n.status === 'error' ? 'Background task failed' : 'Background task finished',
        detail: n.result ?? n.error ?? n.prompt,
        ts: n.completed_at ?? n.created_at ?? new Date().toISOString(),
      })
    }

    for (const e of (trace.data?.events ?? []).slice(0, 25)) {
      out.push({
        id: `handoff:${e.ts}:${e.parent_agent}:${e.child_agent}`,
        severity: 'info',
        source: 'handoff',
        title: `${e.child_agent} → ${e.parent_agent}`,
        detail: `${e.event}${e.status ? ` · ${e.status}` : ''}`,
        agent: e.child_agent,
        ts: e.ts,
      })
    }

    return out.sort((a, b) => b.ts.localeCompare(a.ts))
  }, [obs.data, stale.data, trace.data, unread])

  const visible = filter === 'all' ? items : items.filter((i) => i.severity === filter)
  const unreadCount = items.filter((i) => !read.has(i.id)).length
  const counts = {
    critical: items.filter((i) => i.severity === 'critical').length,
    warning: items.filter((i) => i.severity === 'warning').length,
    info: items.filter((i) => i.severity === 'info').length,
  }

  if (!open) return null

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40" onClick={onClose} aria-hidden="true" />
      <aside
        className="fixed right-0 top-0 bottom-0 z-50 w-[420px] max-w-[92vw] flex flex-col border-l shadow-2xl"
        style={{ background: 'var(--color-bg-panel)', borderColor: 'var(--color-border)' }}
        role="dialog"
        aria-label="Notifications"
      >
        <header className="flex items-center gap-3 px-4 py-3 border-b flex-shrink-0" style={{ borderColor: 'var(--color-border)' }}>
          <h2 className="text-[13px] font-mono uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-secondary)' }}>
            Notifications
          </h2>
          {unreadCount > 0 && (
            <span className="text-[12px] font-mono px-1.5 py-0.5 rounded" style={{ color: 'var(--color-accent)', border: '1px solid var(--color-accent)' }}>
              {unreadCount} new
            </span>
          )}
          <button
            onClick={() => setRead(new Set(items.map((i) => i.id)))}
            className="ml-auto text-[12px] font-mono hover:opacity-80"
            style={{ color: 'var(--color-text-muted)' }}
          >
            Mark all read
          </button>
          <button onClick={onClose} className="text-[12px] font-mono hover:opacity-80" style={{ color: 'var(--color-text-muted)' }} aria-label="Close notifications">
            ✕
          </button>
        </header>

        <div className="flex gap-1 px-4 py-2 border-b flex-shrink-0" style={{ borderColor: 'var(--color-border)' }}>
          {(['all', 'critical', 'warning', 'info'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className="text-[12px] font-mono px-2 py-0.5 rounded border capitalize"
              style={{
                borderColor: filter === f ? 'var(--color-accent)' : 'var(--color-border)',
                color: filter === f ? 'var(--color-accent)' : 'var(--color-text-muted)',
              }}
            >
              {f}
              {f !== 'all' && counts[f] > 0 ? ` ${counts[f]}` : ''}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-auto">
          {visible.length === 0 ? (
            <p className="py-10 text-center text-xs font-mono" style={{ color: 'var(--color-text-muted)' }}>
              Nothing here. A quiet system is a good sign.
            </p>
          ) : (
            visible.map((i, idx) => {
              const isRead = read.has(i.id)
              return (
                <button
                  key={`${i.id}::${idx}`}
                  onClick={() => setRead((prev) => new Set(prev).add(i.id))}
                  className="w-full text-left px-4 py-3 border-b hover:bg-white/5 transition-colors"
                  style={{ borderColor: 'var(--color-border-muted)', opacity: isRead ? 0.55 : 1 }}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: SEVERITY_TONE[i.severity] }} />
                    <span className="text-[13px] font-mono truncate" style={{ color: 'var(--color-text-primary)' }}>{i.title}</span>
                    <span className="ml-auto text-[12px] font-mono flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>
                      {relativeTime(i.ts)}
                    </span>
                  </div>
                  <div className="flex items-baseline gap-2">
                    <span className="text-[12px] font-mono uppercase tracking-[0.1em] flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>
                      {SOURCE_LABEL[i.source]}
                    </span>
                    {i.detail && (
                      <span className="text-[12px] font-mono line-clamp-2" style={{ color: 'var(--color-text-secondary)' }}>
                        {i.detail}
                      </span>
                    )}
                  </div>
                </button>
              )
            })
          )}
        </div>
      </aside>
    </>
  )
}

/** Bell button for the header — shows the unread count. */
export function NotificationBell({ onClick }: { onClick: () => void }) {
  const unread = useWsStore((s) => s.unreadNotifications)
  const obs = usePolled(getObservability, 60_000)
  const count = unread.length + (obs.data?.totals.recent_error_count ?? 0)

  return (
    <button
      onClick={onClick}
      className="relative px-2 py-1 text-xs font-mono border border-zinc-600 bg-zinc-700 text-zinc-200 hover:bg-zinc-600"
      aria-label={`Notifications${count > 0 ? `, ${count} unread` : ''}`}
      title="Notifications"
    >
      BELL
      {count > 0 && (
        <span
          className="absolute -top-1 -right-1 min-w-[14px] h-[14px] px-0.5 rounded-full text-[12px] font-mono leading-[14px] text-center"
          style={{ background: 'var(--color-error)', color: '#fff' }}
        >
          {count > 99 ? '99+' : count}
        </span>
      )}
    </button>
  )
}
