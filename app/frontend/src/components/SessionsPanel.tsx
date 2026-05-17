import { useMemo, useState } from 'react'
import { useSessionStore } from '../store/session'
import { useAppStore } from '../store/appStore'
import { summarizeSession } from '../api/client'
import type { Message } from '../api/types'

export function SessionsPanel() {
  const sessions = useSessionStore((s) => s.sessions)
  const activeId = useSessionStore((s) => s.activeId)
  const loadSession = useSessionStore((s) => s.loadSession)
  const deleteSession = useSessionStore((s) => s.deleteSession)
  const newSession = useSessionStore((s) => s.newSession)
  const appendMessage = useSessionStore((s) => s.appendMessage)
  const setActiveTab = useAppStore((s) => s.setActiveTab)

  const [busyId, setBusyId] = useState<string | null>(null)
  const [bulkBusy, setBulkBusy] = useState<null | 'summarize' | 'delete'>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)

  // Most-recent-first; sessions are already inserted in this order, but sort
  // defensively so the panel stays correct if the store ever changes shape.
  const sorted = useMemo(
    () => [...sessions].sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1)),
    [sessions],
  )

  const anyBusy = busyId !== null || bulkBusy !== null
  const selectedCount = selected.size
  const allSelected = sorted.length > 0 && selected.size === sorted.length

  function fmtDate(iso: string): string {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString()
  }

  function toggleSelected(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function clearSelection() {
    setSelected(new Set())
  }

  function selectAll() {
    setSelected(new Set(sorted.map((s) => s.id)))
  }

  function handleOpen(id: string) {
    loadSession(id)
    setActiveTab('chat')
  }

  function handleDelete(id: string, name: string) {
    if (!window.confirm(`Delete session "${name}"? This cannot be undone.`)) return
    deleteSession(id)
    setSelected((prev) => {
      if (!prev.has(id)) return prev
      const next = new Set(prev)
      next.delete(id)
      return next
    })
  }

  async function handleSummarize(id: string, name: string) {
    const target = sessions.find((s) => s.id === id)
    if (!target || target.history.length === 0) {
      setError('Cannot summarize an empty session.')
      return
    }
    setError(null)
    setBusyId(id)
    try {
      const { summary } = await summarizeSession(target.history)
      const seed = `[Imported summary from "${name}"]\n\n${summary.trim()}`
      newSession()
      appendMessage('user', seed)
      setActiveTab('chat')
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setBusyId(null)
    }
  }

  async function handleBulkSummarize() {
    // Walk sessions in chronological order (oldest first) so the resulting
    // summary reflects the timeline. Skip any session with no history; abort
    // if every selected session is empty.
    const targets = sorted
      .filter((s) => selected.has(s.id))
      .slice()
      .sort((a, b) => (a.createdAt < b.createdAt ? -1 : 1))
      .filter((s) => s.history.length > 0)

    if (targets.length === 0) {
      setError('Selected sessions are empty — nothing to summarize.')
      return
    }

    setError(null)
    setBulkBusy('summarize')
    try {
      // Build a single combined transcript with separator markers between
      // sessions so the summarizer can distinguish them.
      const combined: Message[] = []
      for (const sess of targets) {
        combined.push({
          role: 'user',
          content: `[--- session: ${sess.name} (${fmtDate(sess.createdAt)}) ---]`,
        })
        for (const msg of sess.history) combined.push(msg)
      }

      const { summary } = await summarizeSession(combined)
      const namesPreview = targets
        .slice(0, 3)
        .map((s) => `"${s.name}"`)
        .join(', ')
      const suffix = targets.length > 3 ? `, +${targets.length - 3} more` : ''
      const seed =
        `[Imported summary from ${targets.length} session${targets.length === 1 ? '' : 's'}: ${namesPreview}${suffix}]\n\n` +
        summary.trim()
      newSession()
      appendMessage('user', seed)
      clearSelection()
      setActiveTab('chat')
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setBulkBusy(null)
    }
  }

  function handleBulkDelete() {
    const ids = sorted.filter((s) => selected.has(s.id)).map((s) => s.id)
    if (ids.length === 0) return
    if (
      !window.confirm(
        `Delete ${ids.length} session${ids.length === 1 ? '' : 's'}? This cannot be undone.`,
      )
    ) {
      return
    }
    setBulkBusy('delete')
    try {
      for (const id of ids) deleteSession(id)
      clearSelection()
    } finally {
      setBulkBusy(null)
    }
  }

  if (sorted.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-zinc-500 text-sm font-mono">
        No sessions yet. Click + NEW in the Chat tab to start one.
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto bg-zinc-950 text-zinc-100 px-6 py-4">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center gap-3 mb-4">
          <h2 className="font-mono text-xs uppercase tracking-widest text-[#FFB633]">
            Sessions ({sorted.length})
          </h2>
          <button
            onClick={allSelected ? clearSelection : selectAll}
            disabled={anyBusy}
            className="px-2 py-1 text-[11px] font-mono uppercase tracking-wider border border-zinc-700 text-zinc-400 hover:text-[#FFB633] hover:border-[#FFB633] disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {allSelected ? 'Clear all' : 'Select all'}
          </button>
        </div>

        {error && (
          <div className="mb-4 px-3 py-2 border border-red-700 bg-red-950/50 text-red-300 text-xs font-mono">
            {error}
          </div>
        )}

        {selectedCount > 0 && (
          <div className="mb-4 flex items-center gap-2 px-3 py-2 border border-[#FFB633]/40 bg-[#1a1408]">
            <span className="text-xs font-mono text-[#FFB633]">
              {selectedCount} selected
            </span>
            <div className="flex-1" />
            <button
              onClick={handleBulkSummarize}
              disabled={anyBusy}
              className="px-2 py-1 text-[11px] font-mono uppercase tracking-wider border border-zinc-700 text-zinc-200 hover:text-[#FFB633] hover:border-[#FFB633] disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {bulkBusy === 'summarize' ? 'Summarizing…' : `Summarize (${selectedCount})`}
            </button>
            <button
              onClick={handleBulkDelete}
              disabled={anyBusy}
              className="px-2 py-1 text-[11px] font-mono uppercase tracking-wider border border-zinc-700 text-zinc-300 hover:text-red-400 hover:border-red-500 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {bulkBusy === 'delete' ? 'Deleting…' : `Delete (${selectedCount})`}
            </button>
            <button
              onClick={clearSelection}
              disabled={anyBusy}
              className="px-2 py-1 text-[11px] font-mono uppercase tracking-wider border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Clear
            </button>
          </div>
        )}

        <ul className="space-y-2">
          {sorted.map((s) => {
            const isActive = s.id === activeId
            const isBusy = busyId === s.id
            const isSelected = selected.has(s.id)
            return (
              <li
                key={s.id}
                className={[
                  'flex items-center gap-3 px-3 py-2 border bg-zinc-900',
                  isSelected
                    ? 'border-[#FFB633]/60'
                    : isActive
                    ? 'border-[#FFB633]/40'
                    : 'border-zinc-800',
                ].join(' ')}
              >
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => toggleSelected(s.id)}
                  disabled={anyBusy}
                  aria-label={`Select session "${s.name}"`}
                  className="h-4 w-4 accent-[#FFB633] cursor-pointer disabled:cursor-not-allowed"
                />

                <div className="flex-1 min-w-0">
                  <div
                    className={[
                      'text-sm font-mono truncate',
                      isActive ? 'text-[#FFB633]' : 'text-zinc-200',
                    ].join(' ')}
                  >
                    {s.name}
                  </div>
                  <div className="text-[11px] text-zinc-500 font-mono">
                    {s.history.length} msg{s.history.length === 1 ? '' : 's'} ·{' '}
                    {fmtDate(s.createdAt)}
                  </div>
                </div>

                <button
                  onClick={() => handleOpen(s.id)}
                  disabled={anyBusy}
                  className="px-2 py-1 text-[11px] font-mono uppercase tracking-wider border border-zinc-700 text-zinc-300 hover:text-[#FFB633] hover:border-[#FFB633] disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Open
                </button>
                <button
                  onClick={() => handleSummarize(s.id, s.name)}
                  disabled={anyBusy || s.history.length === 0}
                  className="px-2 py-1 text-[11px] font-mono uppercase tracking-wider border border-zinc-700 text-zinc-300 hover:text-[#FFB633] hover:border-[#FFB633] disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {isBusy ? 'Summarizing…' : 'Summarize'}
                </button>
                <button
                  onClick={() => handleDelete(s.id, s.name)}
                  disabled={anyBusy}
                  className="px-2 py-1 text-[11px] font-mono uppercase tracking-wider border border-zinc-700 text-zinc-400 hover:text-red-400 hover:border-red-500 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Delete
                </button>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
