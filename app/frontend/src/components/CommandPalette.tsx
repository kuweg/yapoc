/**
 * Command Palette (⌘K / Ctrl-K).
 *
 * The app has ten top-level tabs and a per-agent action set, and the only way
 * to reach any of it was to click. The CLI REPL has had tab-completion for a
 * long time; this is the same affordance for the web UI — jump to a tab, jump
 * to an agent, or run an agent action without leaving the keyboard.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAppStore, type AppTab } from '../store/appStore'
import { useThemeStore } from '../store/themeStore'
import { useAgentChatStore } from '../store/agentChatStore'
import { useAgents } from '../hooks/useAgents'
import { killAgent, spawnAgent } from '../api/client'

interface Command {
  id: string
  label: string
  hint?: string
  group: string
  run: () => void | Promise<void>
}

const TABS: Array<{ id: AppTab; label: string }> = [
  { id: 'chat', label: 'Chat' },
  { id: 'agents', label: 'Agents' },
  { id: 'tasks', label: 'Tasks' },
  { id: 'insights', label: 'Insights' },
  { id: 'observability', label: 'Observability' },
  { id: 'concilium', label: 'Concilium' },
  { id: 'graph', label: 'Memory' },
  { id: 'vault', label: 'Vault' },
  { id: 'sessions', label: 'Sessions' },
  { id: 'channels', label: 'Channels' },
]

/** Render order for command groups; also keeps each group's rows contiguous. */
const GROUP_ORDER = ['Navigate', 'Agents', 'Agent actions', 'View']

/** Subsequence match — "cse" finds "Cost Explorer". Returns null when it misses. */
function fuzzyScore(needle: string, haystack: string): number | null {
  if (!needle) return 0
  const n = needle.toLowerCase()
  const h = haystack.toLowerCase()
  let score = 0
  let hi = 0
  let streak = 0
  for (const ch of n) {
    const found = h.indexOf(ch, hi)
    if (found === -1) return null
    // Reward consecutive matches and matches at word boundaries.
    streak = found === hi ? streak + 1 : 0
    score += streak * 2 + (found === 0 || h[found - 1] === ' ' || h[found - 1] === '_' ? 3 : 1)
    hi = found + 1
  }
  return score - h.length * 0.01
}

export function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const [busy, setBusy] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const setTab = useAppStore((s) => s.setActiveTab)
  const toggleTheme = useThemeStore((s) => s.toggleTheme)
  const setSelectedLogAgent = useAgentChatStore((s) => s.setSelectedLogAgent)
  const { agents } = useAgents()

  // Global hotkey. Also closes on a second press so the same chord toggles.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((v) => !v)
      } else if (e.key === 'Escape') {
        setOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (open) {
      setQuery('')
      setCursor(0)
      // Focus after paint so the input exists.
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  const close = useCallback(() => setOpen(false), [])

  const commands = useMemo<Command[]>(() => {
    const out: Command[] = []

    for (const t of TABS) {
      out.push({
        id: `tab:${t.id}`,
        label: `Go to ${t.label}`,
        group: 'Navigate',
        run: () => setTab(t.id),
      })
    }

    for (const a of agents) {
      out.push({
        id: `agent:${a.name}`,
        label: `Open ${a.name} logs`,
        hint: a.status,
        group: 'Agents',
        run: () => { setSelectedLogAgent(a.name); setTab('chat') },
      })
      out.push({
        id: `spawn:${a.name}`,
        label: `Spawn ${a.name}`,
        group: 'Agent actions',
        run: async () => { setBusy(a.name); try { await spawnAgent(a.name) } finally { setBusy(null) } },
      })
      out.push({
        id: `kill:${a.name}`,
        label: `Kill ${a.name}`,
        hint: a.pid ? `pid ${a.pid}` : undefined,
        group: 'Agent actions',
        run: async () => { setBusy(a.name); try { await killAgent(a.name) } finally { setBusy(null) } },
      })
    }

    out.push({ id: 'theme', label: 'Cycle theme', group: 'View', run: toggleTheme })

    return out
  }, [agents, setTab, setSelectedLogAgent, toggleTheme])

  const results = useMemo(() => {
    const scored = !query.trim()
      ? commands.map((c) => ({ c, s: 0 }))
      : commands
          .map((c) => ({ c, s: fuzzyScore(query.trim(), `${c.label} ${c.group}`) }))
          .filter((r): r is { c: Command; s: number } => r.s !== null)

    // Sort by group first so each group forms one contiguous run — the render
    // below does run-length grouping, and a group split across two runs would
    // emit duplicate React keys. Within a group, best match wins.
    return scored
      .sort((a, b) => {
        const ga = GROUP_ORDER.indexOf(a.c.group)
        const gb = GROUP_ORDER.indexOf(b.c.group)
        if (ga !== gb) return ga - gb
        return b.s - a.s
      })
      .slice(0, 40)
      .map((r) => r.c)
  }, [commands, query])

  useEffect(() => { setCursor(0) }, [query])

  // Keep the highlighted row in view when arrowing past the fold.
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-idx="${cursor}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  }, [cursor])

  const runAt = useCallback(
    async (idx: number) => {
      const cmd = results[idx]
      if (!cmd) return
      close()
      await cmd.run()
    },
    [results, close],
  )

  if (!open) return null

  const grouped: Array<[string, Array<{ cmd: Command; idx: number }>]> = []
  results.forEach((cmd, idx) => {
    const last = grouped[grouped.length - 1]
    if (last && last[0] === cmd.group) last[1].push({ cmd, idx })
    else grouped.push([cmd.group, [{ cmd, idx }]])
  })

  return (
    <>
      <div className="fixed inset-0 z-[60] bg-black/50" onClick={close} aria-hidden="true" />
      <div
        className="fixed z-[61] left-1/2 top-[15vh] -translate-x-1/2 w-[560px] max-w-[92vw] rounded border shadow-2xl overflow-hidden"
        style={{ background: 'var(--color-bg-panel)', borderColor: 'var(--color-border)' }}
        role="dialog"
        aria-label="Command palette"
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setCursor((c) => Math.min(c + 1, results.length - 1)) }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)) }
            else if (e.key === 'Enter') { e.preventDefault(); void runAt(cursor) }
          }}
          placeholder="Jump to a tab, an agent, or an action…"
          aria-label="Command search"
          className="w-full px-4 py-3 bg-transparent outline-none text-sm font-mono border-b"
          style={{ color: 'var(--color-text-primary)', borderColor: 'var(--color-border)' }}
        />
        <div ref={listRef} className="max-h-[52vh] overflow-auto py-1">
          {results.length === 0 ? (
            <p className="px-4 py-6 text-center text-xs font-mono" style={{ color: 'var(--color-text-muted)' }}>
              No command matches “{query}”.
            </p>
          ) : (
            grouped.map(([group, rows]) => (
              <div key={group}>
                <div className="px-4 pt-2 pb-1 text-[12px] font-mono uppercase tracking-[0.14em]" style={{ color: 'var(--color-text-muted)' }}>
                  {group}
                </div>
                {rows.map(({ cmd, idx }) => (
                  <button
                    key={cmd.id}
                    data-idx={idx}
                    onMouseEnter={() => setCursor(idx)}
                    onClick={() => void runAt(idx)}
                    className="w-full flex items-center gap-2 px-4 py-1.5 text-left"
                    style={{ background: idx === cursor ? 'var(--color-bg-tertiary)' : 'transparent' }}
                  >
                    <span className="text-[12px] font-mono truncate" style={{ color: 'var(--color-text-primary)' }}>
                      {cmd.label}
                    </span>
                    {cmd.hint && (
                      <span className="ml-auto text-[12px] font-mono flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>
                        {busy && cmd.label.includes(busy) ? 'working…' : cmd.hint}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            ))
          )}
        </div>
        <footer
          className="flex items-center gap-3 px-4 py-2 border-t text-[12px] font-mono"
          style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
        >
          <span>↑↓ move</span>
          <span>⏎ run</span>
          <span>esc close</span>
          <span className="ml-auto">{results.length} commands</span>
        </footer>
      </div>
    </>
  )
}
