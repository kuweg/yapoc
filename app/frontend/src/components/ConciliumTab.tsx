import { useCallback, useEffect, useState } from 'react'

// ── Types ───────────────────────────────────────────────────────────────────

interface CounselorRole {
  key: string
  label: string
  focus: string
  weight: number
}

interface DeliberationSession {
  session_id: string
  started_at: string
  last_event_at: string
  event_count: number
  status: string
  roles: string[]
}

interface DeliberationLogEvent {
  timestamp: string
  session_id: string
  type: string
  data: Record<string, unknown>
}

interface DeliberationResult {
  session_id: string
  status: string
  rounds_completed: number
  duration_s: number
  approved_plan: string | null
  escalation_summary: Record<string, unknown> | null
}

// ── Constants ───────────────────────────────────────────────────────────────

const COUNSELOR_ROLES: CounselorRole[] = [
  { key: 'architect', label: 'Architect', focus: 'Technical soundness, scalability, design patterns', weight: 0.30 },
  { key: 'critic', label: 'Critic', focus: 'Edge cases, failure modes, logical gaps', weight: 0.25 },
  { key: 'security', label: 'Security', focus: 'Vulnerabilities, credential handling, access control', weight: 0.20 },
  { key: 'cost_analyst', label: 'Cost Analyst', focus: 'Resource usage, token consumption, cost efficiency', weight: 0.15 },
  { key: 'ux_advocate', label: 'UX Advocate', focus: 'User experience, error handling, rollback paths', weight: 0.10 },
]

const STATUS_COLORS: Record<string, string> = {
  approved: 'text-green-400 border-green-700/40 bg-green-900/40',
  rejected: 'text-red-400 border-red-700/40 bg-red-900/40',
  escalated: 'text-yellow-400 border-yellow-700/40 bg-yellow-900/40',
  in_progress: 'text-blue-400 border-blue-700/40 bg-blue-900/40',
  pending: 'text-zinc-400 border-zinc-700 bg-zinc-800',
}

const ROLE_COLORS: Record<string, string> = {
  architect: 'text-blue-400',
  critic: 'text-purple-400',
  security: 'text-red-400',
  cost_analyst: 'text-[#FFB633]',
  ux_advocate: 'text-emerald-400',
}

function roleColor(key: string): string {
  return ROLE_COLORS[key] ?? 'text-zinc-300'
}

function fmtTimestamp(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString()
}

function shortTimestamp(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function fmtDuration(s: number): string {
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const r = Math.round(s - m * 60)
  return `${m}m${r}s`
}

// ── Sub-components ──────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const color = STATUS_COLORS[status] ?? STATUS_COLORS.pending
  return (
    <span className={`inline-block px-1.5 py-0.5 text-[10px] border font-mono ${color}`}>
      {status}
    </span>
  )
}

function RoleTag({ role }: { role: string }) {
  const info = COUNSELOR_ROLES.find((r) => r.key === role)
  return (
    <span
      className={`inline-block px-1.5 py-0.5 text-[10px] border border-zinc-700 font-mono ${roleColor(role)}`}
      title={info?.focus ?? ''}
    >
      {info?.label ?? role}
    </span>
  )
}

// ── New Deliberation Form ───────────────────────────────────────────────────

function NewDeliberationForm({
  onStart,
  loading,
}: {
  onStart: (planText: string, roles: string[], maxRounds: number) => void
  loading: boolean
}) {
  const [planText, setPlanText] = useState('')
  const [selectedRoles, setSelectedRoles] = useState<string[]>(
    COUNSELOR_ROLES.map((r) => r.key)
  )
  const [maxRounds, setMaxRounds] = useState(3)

  const toggleRole = (key: string) => {
    setSelectedRoles((prev) =>
      prev.includes(key) ? prev.filter((r) => r !== key) : [...prev, key]
    )
  }

  const handleSubmit = () => {
    if (!planText.trim() || selectedRoles.length === 0) return
    onStart(planText.trim(), selectedRoles, maxRounds)
  }

  return (
    <div className="border border-zinc-800 bg-zinc-900/40 p-4 space-y-4">
      <h3 className="text-[10px] uppercase tracking-widest text-zinc-500 font-mono">
        New Deliberation
      </h3>

      {/* Plan text area */}
      <div>
        <label className="text-[10px] font-mono text-zinc-500 block mb-1">
          Plan to evaluate
        </label>
        <textarea
          value={planText}
          onChange={(e) => setPlanText(e.target.value)}
          placeholder="Paste the plan text here..."
          rows={8}
          className="w-full bg-zinc-950 border border-zinc-700 text-zinc-200 text-xs font-mono px-3 py-2 focus:outline-none focus:border-[#FFB633] resize-y"
        />
      </div>

      {/* Role selection */}
      <div>
        <label className="text-[10px] font-mono text-zinc-500 block mb-1">
          Counselors ({selectedRoles.length}/{COUNSELOR_ROLES.length})
        </label>
        <div className="flex flex-wrap gap-2">
          {COUNSELOR_ROLES.map((role) => {
            const active = selectedRoles.includes(role.key)
            return (
              <button
                key={role.key}
                onClick={() => toggleRole(role.key)}
                title={role.focus}
                className={`px-2 py-1 text-[10px] font-mono border ${
                  active
                    ? 'border-[#FFB633] text-[#FFB633] bg-[#FFB633]/10'
                    : 'border-zinc-700 text-zinc-500'
                } hover:border-zinc-500`}
              >
                {role.label} ({Math.round(role.weight * 100)}%)
              </button>
            )
          })}
        </div>
      </div>

      {/* Max rounds */}
      <div className="flex items-center gap-3">
        <label className="text-[10px] font-mono text-zinc-500">
          Max rounds
        </label>
        <select
          value={maxRounds}
          onChange={(e) => setMaxRounds(Number(e.target.value))}
          className="bg-zinc-900 border border-zinc-700 text-zinc-200 text-[11px] font-mono px-2 py-1"
        >
          {[1, 2, 3, 5].map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
      </div>

      {/* Submit */}
      <button
        onClick={handleSubmit}
        disabled={loading || !planText.trim() || selectedRoles.length === 0}
        className="px-4 py-2 text-[11px] font-mono uppercase tracking-wider border border-[#FFB633] text-[#FFB633] hover:bg-[#FFB633]/10 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {loading ? 'Deliberating...' : 'Start Deliberation'}
      </button>
    </div>
  )
}

// ── Session List ────────────────────────────────────────────────────────────

function SessionList({
  sessions,
  selectedId,
  onSelect,
  onRefresh,
  loading,
}: {
  sessions: DeliberationSession[]
  selectedId: string | null
  onSelect: (id: string) => void
  onRefresh: () => void
  loading: boolean
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <h3 className="text-[10px] uppercase tracking-widest text-zinc-500 font-mono">
          Sessions ({sessions.length})
        </h3>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="px-2 py-1 text-[10px] font-mono uppercase tracking-wider border border-zinc-700 text-zinc-400 hover:text-[#FFB633] hover:border-[#FFB633] disabled:opacity-40"
        >
          {loading ? '...' : 'Refresh'}
        </button>
      </div>

      <div className="border border-zinc-800 bg-zinc-900/40 max-h-96 overflow-y-auto">
        {sessions.length === 0 ? (
          <div className="px-3 py-4 text-xs text-zinc-500 font-mono text-center">
            No sessions yet.
          </div>
        ) : (
          <ul className="divide-y divide-zinc-800">
            {sessions.map((s) => {
              const isSelected = s.session_id === selectedId
              return (
                <li
                  key={s.session_id}
                  className={`px-3 py-2 cursor-pointer text-xs font-mono ${
                    isSelected ? 'bg-zinc-800/60' : 'hover:bg-zinc-900/60'
                  }`}
                  onClick={() => onSelect(s.session_id)}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-zinc-200">{s.session_id}</span>
                    <StatusBadge status={s.status} />
                    <span className="text-zinc-600 ml-auto text-[10px]">
                      {shortTimestamp(s.started_at)}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {s.roles.map((role) => (
                      <RoleTag key={role} role={role} />
                    ))}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}

// ── Log Viewer ──────────────────────────────────────────────────────────────

function LogViewer({ events }: { events: DeliberationLogEvent[] }) {
  return (
    <div>
      <h3 className="text-[10px] uppercase tracking-widest text-zinc-500 mb-2 font-mono">
        Event log ({events.length})
      </h3>
      <div className="border border-zinc-800 bg-zinc-900/40 max-h-80 overflow-y-auto">
        {events.length === 0 ? (
          <div className="px-3 py-4 text-xs text-zinc-500 font-mono text-center">
            No events yet.
          </div>
        ) : (
          <ul className="divide-y divide-zinc-800">
            {events.map((ev, i) => (
              <li key={`${ev.timestamp}-${i}`} className="px-3 py-1.5 text-[10px] font-mono">
                <span className="text-zinc-600">{shortTimestamp(ev.timestamp)}</span>{' '}
                <span className="text-zinc-400">[{ev.type}]</span>{' '}
                <span className="text-zinc-300">
                  {JSON.stringify(ev.data).slice(0, 200)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

// ── Main Component ──────────────────────────────────────────────────────────

export function ConciliumTab() {
  const [sessions, setSessions] = useState<DeliberationSession[]>([])
  const [selectedSession, setSelectedSession] = useState<string | null>(null)
  const [logs, setLogs] = useState<DeliberationLogEvent[]>([])
  const [result, setResult] = useState<DeliberationResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [deliberating, setDeliberating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showNewForm, setShowNewForm] = useState(true)

  // Load sessions
  const loadSessions = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/concilium/sessions')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const body = await res.json()
      setSessions(body.sessions ?? [])
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setLoading(false)
    }
  }, [])

  // Load logs for selected session
  const loadLogs = useCallback(async (sessionId: string) => {
    try {
      const res = await fetch(`/api/concilium/logs/${sessionId}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const body = await res.json()
      setLogs(body.events ?? [])
    } catch {
      // silent
    }
  }, [])

  // Load session status
  const loadStatus = useCallback(async (sessionId: string) => {
    try {
      const res = await fetch(`/api/concilium/status/${sessionId}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const body = await res.json()
      return body
    } catch {
      return null
    }
  }, [])

  // Initial load
  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  // Load logs when session changes
  useEffect(() => {
    if (selectedSession) {
      loadLogs(selectedSession)
      loadStatus(selectedSession).then((s) => {
        if (s) setResult(s as unknown as DeliberationResult)
      })
    }
  }, [selectedSession, loadLogs, loadStatus])

  // Start deliberation
  const handleStart = async (planText: string, roles: string[], maxRounds: number) => {
    setDeliberating(true)
    setError(null)
    setResult(null)
    try {
      const res = await fetch('/api/concilium/deliberate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan_text: planText,
          roles,
          max_rounds: maxRounds,
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const body = await res.json() as DeliberationResult
      setResult(body)
      setSelectedSession(body.session_id)
      setShowNewForm(false)
      // Refresh sessions
      loadSessions()
      // Load logs
      loadLogs(body.session_id)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setDeliberating(false)
    }
  }

  // Select session
  const handleSelectSession = (id: string) => {
    setSelectedSession(id)
    setShowNewForm(false)
    setResult(null)
  }

  return (
    <div className="flex flex-col h-full bg-zinc-950 text-zinc-100 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-zinc-800 flex-shrink-0">
        <h2 className="text-[10px] uppercase tracking-widest text-zinc-500 font-mono">Concilium</h2>
        <button
          onClick={() => setShowNewForm(!showNewForm)}
          className={`px-2 py-1 text-[11px] font-mono uppercase tracking-wider border ${
            showNewForm ? 'border-[#FFB633] text-[#FFB633]' : 'border-zinc-700 text-zinc-400'
          } hover:border-[#FFB633] hover:text-[#FFB633]`}
        >
          {showNewForm ? 'Hide form' : 'New deliberation'}
        </button>
        <button
          onClick={loadSessions}
          disabled={loading}
          className="px-2 py-1 text-[11px] font-mono uppercase tracking-wider border border-zinc-700 text-zinc-300 hover:text-[#FFB633] hover:border-[#FFB633] disabled:opacity-40"
        >
          {loading ? '...' : 'Refresh'}
        </button>
        {selectedSession && (
          <span className="text-[11px] text-zinc-500 font-mono ml-auto">
            Session: {selectedSession}
          </span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {error && (
          <div className="px-3 py-2 border border-red-700 bg-red-950/50 text-red-300 text-xs font-mono">
            {error}
          </div>
        )}

        {/* New deliberation form */}
        {showNewForm && (
          <NewDeliberationForm onStart={handleStart} loading={deliberating} />
        )}

        {/* Deliberation result */}
        {result && (
          <div className="border border-zinc-800 bg-zinc-900/40 p-4 space-y-3">
            <div className="flex items-center gap-3">
              <h3 className="text-[10px] uppercase tracking-widest text-zinc-500 font-mono">
                Result
              </h3>
              <StatusBadge status={result.status} />
              <span className="text-[10px] text-zinc-500 font-mono">
                {result.rounds_completed} round(s) · {fmtDuration(result.duration_s)}
              </span>
            </div>

            {result.approved_plan && (
              <div>
                <label className="text-[10px] font-mono text-zinc-500 block mb-1">
                  Approved Plan
                </label>
                <pre className="bg-zinc-950 border border-zinc-800 p-3 text-[11px] text-zinc-300 font-mono overflow-x-auto whitespace-pre-wrap max-h-60 overflow-y-auto">
                  {result.approved_plan}
                </pre>
              </div>
            )}

            {result.escalation_summary && (
              <div>
                <label className="text-[10px] font-mono text-zinc-500 block mb-1">
                  Escalation Summary
                </label>
                <pre className="bg-zinc-950 border border-zinc-800 p-3 text-[11px] text-yellow-300 font-mono overflow-x-auto whitespace-pre-wrap max-h-60 overflow-y-auto">
                  {JSON.stringify(result.escalation_summary, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}

        {/* Sessions + Logs side by side */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <SessionList
            sessions={sessions}
            selectedId={selectedSession}
            onSelect={handleSelectSession}
            onRefresh={loadSessions}
            loading={loading}
          />
          <LogViewer events={logs} />
        </div>

        {/* Counselor roles reference */}
        <div>
          <h3 className="text-[10px] uppercase tracking-widest text-zinc-500 mb-2 font-mono">
            Counselor Roles
          </h3>
          <div className="border border-zinc-800 bg-zinc-900/40">
            <table className="w-full text-xs font-mono">
              <thead className="bg-zinc-900 text-zinc-500">
                <tr className="text-left">
                  <th className="px-3 py-2 font-normal">Role</th>
                  <th className="px-3 py-2 font-normal">Focus</th>
                  <th className="px-3 py-2 font-normal text-right">Weight</th>
                </tr>
              </thead>
              <tbody>
                {COUNSELOR_ROLES.map((role) => (
                  <tr key={role.key} className="border-t border-zinc-800">
                    <td className={`px-3 py-2 ${roleColor(role.key)}`}>{role.label}</td>
                    <td className="px-3 py-2 text-zinc-400">{role.focus}</td>
                    <td className="px-3 py-2 text-right text-zinc-400">{Math.round(role.weight * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
