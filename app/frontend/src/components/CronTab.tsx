import { useEffect, useState, useCallback } from 'react'
import { Plus, RefreshCw, Trash2, Play, Clock, ChevronDown, ChevronRight } from 'lucide-react'
import { StudioDialog } from '../studio/StudioDialog'
import {
  getCronJobs,
  createCronJob,
  updateCronJob,
  deleteCronJob,
  runCronJob,
  getCronHistory,
  type CronJob,
  type CronHistoryEntry,
} from '../api/cronClient'

const inputClass =
  'w-full bg-zinc-900 text-zinc-100 text-sm border border-zinc-800 rounded px-3 py-2 focus:outline-none focus:ring-1 focus:ring-zinc-600 placeholder-zinc-600'

/** Parse the hour field (2nd field) of a 5-field cron expression.
 *  Returns the integer hour if it's a plain 0-23, otherwise null (recurring). */
function cronHour(cron: string): number | null {
  const fields = cron.trim().split(/\s+/)
  if (fields.length < 2) return null
  const hour = fields[1]
  if (/^\d+$/.test(hour)) {
    const n = Number(hour)
    if (n >= 0 && n <= 23) return n
  }
  return null
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString()
}

export default function CronTab() {
  const [jobs, setJobs] = useState<CronJob[]>([])
  const [agents, setAgents] = useState<string[]>([])
  const [history, setHistory] = useState<CronHistoryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)

  // dialog state
  const [editing, setEditing] = useState<CronJob | null>(null)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ id: '', assign_to: '', task: '', cron: '', silent: false })

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    Promise.all([getCronJobs(), getCronHistory()])
      .then(([jobsRes, histRes]) => {
        setJobs(jobsRes.jobs)
        setAgents(jobsRes.agents)
        setHistory(histRes.history)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'failed'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const openCreate = () => {
    setForm({ id: '', assign_to: agents[0] ?? '', task: '', cron: '', silent: false })
    setEditing(null)
    setCreating(true)
  }

  const openEdit = (job: CronJob) => {
    setForm({
      id: job.id,
      assign_to: job.assign_to,
      task: job.task ?? '',
      cron: job.cron,
      silent: Boolean(job.silent),
    })
    setEditing(job)
    setCreating(false)
  }

  const closeDialog = () => {
    setCreating(false)
    setEditing(null)
  }

  const submit = async () => {
    try {
      if (editing) {
        await updateCronJob(editing.id, {
          assign_to: form.assign_to,
          task: form.task,
          cron: form.cron,
          silent: form.silent,
        })
      } else {
        await createCronJob({
          id: form.id,
          assign_to: form.assign_to,
          task: form.task,
          cron: form.cron,
          silent: form.silent,
        })
      }
      closeDialog()
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'save failed')
    }
  }

  const doDelete = async (job: CronJob) => {
    if (!window.confirm(`Delete cron job "${job.id}"?`)) return
    try {
      await deleteCronJob(job.id)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'delete failed')
    }
  }

  const doRun = async (job: CronJob) => {
    try {
      await runCronJob(job.id)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'run failed')
    }
  }

  // Distinct agents across jobs, sorted — the y-axis rows.
  const scheduleAgents = Array.from(new Set(jobs.map((j) => j.assign_to))).sort()

  const hourOf = (job: CronJob) => cronHour(job.cron)

  return (
    <div className="studio-settings relative flex flex-col h-full bg-zinc-950 text-zinc-100 overflow-hidden">
      <div className="studio-section-header">
        <div><h1>Scheduled jobs</h1><p>Visualize and manage recurring agent tasks.</p></div>
        <button className="studio-secondary-button" onClick={load} aria-label="Refresh cron jobs"><RefreshCw size={16} /></button>
        <button className="studio-primary-button" onClick={openCreate}><Plus size={16} /> New job</button>
      </div>
      <div className="studio-settings-body">
        {error && <div role="alert" className="studio-error"><strong>Could not load or update cron jobs.</strong><span>{error}</span><button onClick={load}>Try again</button></div>}
        {loading ? <div className="studio-loading" role="status">Loading scheduled jobs…<div /><div /><div /></div>
          : <>
            {/* ── Schedule grid (DAG-style) ── */}
            <div className="overflow-x-auto mb-6">
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '120px repeat(24, minmax(0, 1fr))',
                  minWidth: '720px',
                }}
              >
                {/* header row */}
                <div style={{ color: 'var(--color-text-muted)', fontSize: '11px', padding: '4px' }} />
                {Array.from({ length: 24 }, (_, h) => (
                  <div key={h} style={{ color: 'var(--color-text-muted)', fontSize: '10px', textAlign: 'center', padding: '4px 0', borderLeft: '1px solid var(--color-border)' }}>
                    {h}
                  </div>
                ))}

                {scheduleAgents.map((agent) => {
                  const agentJobs = jobs.filter((j) => j.assign_to === agent)
                  return (
                    <FragmentRow key={agent} agent={agent} agentJobs={agentJobs} hourOf={hourOf} onEdit={openEdit} />
                  )
                })}
              </div>
            </div>

            {/* ── Job list ── */}
            <div className="studio-table-scroll">
              <table className="studio-table" aria-label="Cron jobs">
                <thead><tr><th>ID</th><th>Cron</th><th>Agent</th><th>Last run</th><th>Status</th><th><span className="sr-only">Actions</span></th></tr></thead>
                <tbody>
                  {jobs.map((job) => (
                    <tr key={job.id}>
                      <td><strong>{job.id}</strong></td>
                      <td><code>{job.cron}</code></td>
                      <td>{job.assign_to}</td>
                      <td>{fmtTime(job.last_run)}</td>
                      <td>{job.disabled ? <span className="studio-badge" style={{ color: 'var(--color-error)', borderColor: 'var(--color-error)' }}>Disabled</span> : <span className="studio-badge" style={{ color: 'var(--color-success)', borderColor: 'var(--color-success)' }}>Active</span>}</td>
                      <td>
                        <div className="studio-row-actions">
                          <button className="studio-secondary-button" onClick={() => doRun(job)} aria-label={`Run ${job.id} now`}><Play size={14} /> Run</button>
                          <button className="studio-secondary-button" onClick={() => openEdit(job)}>Edit</button>
                          <button className="studio-danger-button" onClick={() => doDelete(job)} aria-label={`Delete ${job.id}`}><Trash2 size={14} /> Delete</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {jobs.length === 0 && (
                    <tr><td colSpan={6} className="studio-empty"><Clock size={24} /><h2>No scheduled jobs</h2><p>Create a job to schedule recurring work.</p></td></tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* ── History ── */}
            <div className="mt-6">
              <button className="studio-secondary-button" onClick={() => setHistoryOpen((v) => !v)} aria-expanded={historyOpen}>
                {historyOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />} History ({history.length})
              </button>
              {historyOpen && (
                <div className="mt-2 space-y-1">
                  {history.length === 0 && <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>No history yet.</p>}
                  {history.map((entry) => (
                    <div key={entry.id} className="border rounded p-2" style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-secondary)' }}>
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="studio-badge" style={{
                          color: entry.status === 'success' || entry.status === 'done' ? 'var(--color-success)'
                            : entry.status === 'error' || entry.status === 'failed' ? 'var(--color-error)'
                            : 'var(--color-text-muted)',
                          borderColor: 'currentColor',
                        }}>{entry.status}</span>
                        <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>{entry.assigned_agent ?? '—'}</span>
                        <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>${entry.cost_usd?.toFixed(4) ?? '0.0000'}</span>
                        <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>{fmtTime(entry.created_at)}</span>
                      </div>
                      <p className="text-xs mt-1 truncate" style={{ color: 'var(--color-text-primary)' }}>{entry.prompt}</p>
                      {entry.error && <p className="text-xs mt-1" style={{ color: 'var(--color-error)' }}>{entry.error}</p>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>}
      </div>

      {/* ── Create/Edit dialog ── */}
      {(creating || editing) && (
        <StudioDialog label={editing ? `Edit ${editing.id}` : 'New cron job'} onClose={closeDialog}>
          <div className="w-full max-w-lg border border-zinc-800 bg-zinc-900 rounded p-4 space-y-3 max-h-full overflow-y-auto">
            <h3 className="text-sm font-medium text-zinc-100">{editing ? `Edit ${editing.id}` : 'New cron job'}</h3>
            <label className="block">
              <span className="block text-xs uppercase tracking-widest text-zinc-500 mb-1">ID</span>
              <input className={inputClass} value={form.id} disabled={Boolean(editing)} placeholder="my-job"
                onChange={(e) => setForm((f) => ({ ...f, id: e.target.value }))} />
            </label>
            <label className="block">
              <span className="block text-xs uppercase tracking-widest text-zinc-500 mb-1">Assign to</span>
              <select className={inputClass} value={form.assign_to} onChange={(e) => setForm((f) => ({ ...f, assign_to: e.target.value }))}>
                <option value="">— select agent —</option>
                {agents.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="block text-xs uppercase tracking-widest text-zinc-500 mb-1">Task</span>
              <textarea className={inputClass} rows={3} value={form.task} placeholder="Optional — leave blank for self-contained agents"
                onChange={(e) => setForm((f) => ({ ...f, task: e.target.value }))} />
            </label>
            <label className="block">
              <span className="block text-xs uppercase tracking-widest text-zinc-500 mb-1">Cron</span>
              <input className={inputClass} value={form.cron} placeholder="0 8 * * *"
                onChange={(e) => setForm((f) => ({ ...f, cron: e.target.value }))} />
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={form.silent} onChange={(e) => setForm((f) => ({ ...f, silent: e.target.checked }))} className="accent-[#FFB633]" />
              <span className="text-xs text-zinc-300">Silent (no notification)</span>
            </label>
            <div className="flex gap-2">
              <button onClick={submit} className="px-3 py-1.5 text-xs rounded bg-[#FFB633] text-zinc-900 font-medium">Save</button>
              <button onClick={closeDialog} className="px-3 py-1.5 text-xs rounded border border-zinc-800 text-zinc-400 hover:text-zinc-200">Cancel</button>
            </div>
          </div>
        </StudioDialog>
      )}
    </div>
  )
}

function FragmentRow({ agent, agentJobs, hourOf, onEdit }: {
  agent: string
  agentJobs: CronJob[]
  hourOf: (job: CronJob) => number | null
  onEdit: (job: CronJob) => void
}) {
  return (
    <>
      <div style={{ color: 'var(--color-text-primary)', fontSize: '12px', padding: '4px', borderTop: '1px solid var(--color-border)', display: 'flex', alignItems: 'center' }}>
        <span className="truncate">{agent}</span>
      </div>
      {Array.from({ length: 24 }, (_, h) => {
        // find a job placed at this hour, or a recurring job spanning all columns
        const atHour = agentJobs.filter((j) => hourOf(j) === h)
        const recurring = agentJobs.filter((j) => hourOf(j) === null)
        const cells = [...atHour, ...recurring]
        return (
          <div key={h} style={{ borderLeft: '1px solid var(--color-border)', borderTop: '1px solid var(--color-border)', minHeight: '28px', position: 'relative' }}>
            {cells.map((job) => {
              const isRecurring = hourOf(job) === null
              const bg = job.disabled
                ? 'var(--color-error)'
                : 'var(--color-accent)'
              return (
                <button
                  key={job.id}
                  onClick={() => onEdit(job)}
                  title={`${job.id} — ${job.cron}`}
                  style={{
                    position: 'absolute',
                    inset: 0,
                    background: isRecurring
                      ? `repeating-linear-gradient(45deg, ${bg}22, ${bg}22 6px, transparent 6px, transparent 12px)`
                      : bg,
                    border: `1px solid ${bg}`,
                    borderRadius: '3px',
                    color: isRecurring ? 'var(--color-text-primary)' : 'var(--studio-accent-ink)',
                    fontSize: '10px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    overflow: 'hidden',
                    cursor: 'pointer',
                  }}
                >
                  {isRecurring && h === 0 ? <span className="truncate px-1">{job.id}</span> : !isRecurring ? <span className="truncate px-1">{job.id}</span> : null}
                  {job.last_run && h === 0 && <span style={{ position: 'absolute', top: 2, right: 2, width: 5, height: 5, borderRadius: '50%', background: 'var(--color-success)' }} />}
                </button>
              )
            })}
          </div>
        )
      })}
    </>
  )
}
