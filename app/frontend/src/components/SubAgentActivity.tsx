/**
 * Live sub-agent activity card.
 *
 * A delegation used to be a single collapsed row that said nothing until the
 * child finished. This shows what the child is doing while it does it, shaped
 * to the agent: planning renders its decomposition as a checklist, builder
 * renders the files it is touching with +/- line counts, everything else gets a
 * tool ticker. Modelled on the compaction marker — a tinted card with a sweep,
 * a running pulse, and real numbers rather than a spinner.
 */
import { useMemo } from 'react'
import { useAgentActivity } from '../hooks/useAgentActivity'
import type { AgentActivityLog } from '../types/agentActivity'
import { AgentAvatar, getAgentColor, getAgentDisplayName, withAlpha } from '../lib/agentIdentity'

// ── Derived shapes ──────────────────────────────────────────────────────────

export interface FileChange {
  path: string
  kind: 'create' | 'edit' | 'delete'
  added: number
  removed: number
}

export interface PlanStep {
  text: string
  done: boolean
}

const FILE_TOOLS = new Set(['file_write', 'file_edit', 'file_delete'])

function countLines(s: unknown): number {
  if (typeof s !== 'string' || s === '') return 0
  return s.split('\n').length
}

function basename(p: string): string {
  const parts = p.split('/')
  return parts[parts.length - 1] || p
}

/** File mutations the agent has performed, newest last, de-duplicated by path. */
function deriveFileChanges(events: AgentActivityLog[]): FileChange[] {
  const byPath = new Map<string, FileChange>()
  for (const e of events) {
    if (e.type !== 'tool_call') continue
    const meta = (e.metadata ?? {}) as Record<string, unknown>
    const name = String(meta.name ?? '')
    if (!FILE_TOOLS.has(name)) continue
    const input = (meta.input ?? {}) as Record<string, unknown>
    const path = String(input.path ?? '')
    if (!path) continue

    let change: FileChange
    if (name === 'file_write') {
      change = { path, kind: 'create', added: countLines(input.content), removed: 0 }
    } else if (name === 'file_edit') {
      change = {
        path,
        kind: 'edit',
        added: countLines(input.new_string),
        removed: countLines(input.old_string),
      }
    } else {
      change = { path, kind: 'delete', added: 0, removed: 0 }
    }

    // Repeated edits to one file accumulate rather than replacing each other.
    const prev = byPath.get(path)
    if (prev && prev.kind !== 'delete' && change.kind === 'edit') {
      prev.added += change.added
      prev.removed += change.removed
    } else {
      byPath.set(path, change)
    }
  }
  return [...byPath.values()]
}

/**
 * Planning emits its decomposition as prose. Pull out the list items — numbered
 * steps or bullets — and mark the ones it has reported complete.
 */
function derivePlanSteps(events: AgentActivityLog[]): PlanStep[] {
  const out: PlanStep[] = []
  const seen = new Set<string>()

  // Structured first. A planner's own delegations ARE its plan, one step per
  // spawn, and they are reliable — unlike the prose stream, which arrives
  // interleaved and unusable often enough that it can't be the only source.
  for (const e of events) {
    if (e.type !== 'tool_call') continue
    const meta = (e.metadata ?? {}) as Record<string, unknown>
    if (String(meta.name ?? '') !== 'spawn_agent') continue
    const input = (meta.input ?? {}) as Record<string, unknown>
    const target = String(input.agent_name ?? input.name ?? '')
    const task = String(input.task ?? input.prompt ?? '').replace(/\s+/g, ' ').trim()
    if (!task) continue
    const label = `${target ? `${target}: ` : ''}${task.slice(0, 140)}`
    if (seen.has(label)) continue
    seen.add(label)
    out.push({ text: label, done: true })
  }

  const text = events
    .filter((e) => e.type === 'llm_output')
    .map((e) => e.content)
    .join('\n')

  for (const raw of text.split('\n')) {
    const line = raw.trim()
    const m = /^(?:[-*•]|\d+[.)])\s+(.{3,160})$/.exec(line)
    if (!m) continue
    let body = m[1].trim()
    // `- [done] Do the thing` / `- [x] Do the thing`
    const doneMark = /^\[(done|x|✓)\]\s*/i.exec(body)
    const done = Boolean(doneMark)
    if (doneMark) body = body.slice(doneMark[0].length)
    if (!body || seen.has(body)) continue
    // Guard against the garbled-delta stream: real plan lines have spaces and
    // ordinary word shapes. "I'llposingThe asks **plan meI" must not render.
    const words = body.split(/\s+/)
    const longRun = /[A-Za-z]{22,}/.test(body)
    if (words.length < 3 || longRun) continue
    seen.add(body)
    out.push({ text: body, done })
  }
  return out.slice(0, 12)
}

/** Most recent tool names, for the generic ticker. */
function deriveTools(events: AgentActivityLog[]): Array<{ name: string; arg: string }> {
  const out: Array<{ name: string; arg: string }> = []
  for (const e of events) {
    if (e.type !== 'tool_call') continue
    const meta = (e.metadata ?? {}) as Record<string, unknown>
    const input = (meta.input ?? {}) as Record<string, unknown>
    const arg = String(input.path ?? input.agent_name ?? input.query ?? input.command ?? '')
    out.push({ name: String(meta.name ?? 'tool'), arg: arg.slice(0, 48) })
  }
  return out.slice(-6)
}

// ── Presentation ────────────────────────────────────────────────────────────

function DiffBar({ added, removed }: { added: number; removed: number }) {
  const total = added + removed
  if (total === 0) return null
  const segs = Math.min(5, Math.max(1, Math.round(total / 4)))
  const addSegs = total === 0 ? 0 : Math.round((added / total) * segs)
  return (
    <span className="inline-flex gap-[2px] ml-1" aria-hidden>
      {Array.from({ length: segs }, (_, i) => (
        <span
          key={i}
          className="w-[5px] h-[9px] rounded-[1px]"
          style={{ background: i < addSegs ? '#3fb950' : '#f85149', opacity: 0.85 }}
        />
      ))}
    </span>
  )
}

const KIND_GLYPH: Record<FileChange['kind'], string> = { create: '+', edit: '~', delete: '−' }
const KIND_TONE: Record<FileChange['kind'], string> = {
  create: '#3fb950',
  edit: '#d29922',
  delete: '#f85149',
}

export function SubAgentActivity({
  agentName,
  running,
  compact = false,
}: {
  agentName: string
  running: boolean
  compact?: boolean
}) {
  // Hydrates from the HTTP snapshot then merges live WS events, so a child that
  // began before this card mounted still shows its work.
  const list = useAgentActivity(agentName)
  const files = useMemo(() => deriveFileChanges(list), [list])
  const steps = useMemo(() => derivePlanSteps(list), [list])
  const tools = useMemo(() => deriveTools(list), [list])

  const color = getAgentColor(agentName)
  const isBuilder = files.length > 0
  const isPlanner = !isBuilder && steps.length > 0
  const hasAnything = isBuilder || isPlanner || tools.length > 0
  if (!hasAnything) return null

  const totalAdded = files.reduce((s, f) => s + f.added, 0)
  const totalRemoved = files.reduce((s, f) => s + f.removed, 0)

  return (
    <div
      className="subagent-card my-1 rounded-md border overflow-hidden"
      style={{ borderColor: withAlpha(color, 0.35), background: withAlpha(color, 0.05) }}
      data-testid="subagent-activity"
      data-agent={agentName}
    >
      <div className="flex items-center gap-2 px-2.5 py-1.5">
        <AgentAvatar name={agentName} size={14} />
        <span className="text-[13px] font-mono font-semibold" style={{ color }}>
          {getAgentDisplayName(agentName)}
        </span>
        <span className="text-[12px] font-mono uppercase tracking-wider text-zinc-500">
          {isBuilder ? 'editing files' : isPlanner ? 'planning' : 'working'}
        </span>
        {running && (
          <span
            className="subagent-pulse w-1.5 h-1.5 rounded-full"
            style={{ background: color }}
            aria-label="running"
          />
        )}
        {isBuilder && (
          <span className="ml-auto text-[12px] font-mono tabular-nums">
            <span style={{ color: '#3fb950' }}>+{totalAdded}</span>{' '}
            <span style={{ color: '#f85149' }}>−{totalRemoved}</span>
            <span className="text-zinc-500"> · {files.length} file{files.length === 1 ? '' : 's'}</span>
          </span>
        )}
        {isPlanner && (
          <span className="ml-auto text-[12px] font-mono tabular-nums text-zinc-500">
            {steps.filter((s) => s.done).length}/{steps.length} steps
          </span>
        )}
      </div>

      {/* Builder — file changes with a diff stat */}
      {isBuilder && (
        <ul className="px-2.5 pb-2 space-y-0.5">
          {files.slice(compact ? -4 : -10).map((f, i) => (
            <li
              key={f.path}
              className="subagent-row flex items-center gap-2 text-[13px] font-mono"
              style={{ animationDelay: `${i * 55}ms` }}
            >
              <span style={{ color: KIND_TONE[f.kind], width: '0.8em' }}>{KIND_GLYPH[f.kind]}</span>
              <span className="text-zinc-300 truncate" title={f.path}>{basename(f.path)}</span>
              <span className="text-zinc-600 truncate hidden sm:inline text-[12px]">
                {f.path.includes('/') ? f.path.slice(0, f.path.lastIndexOf('/')) : ''}
              </span>
              <span className="ml-auto flex items-center tabular-nums whitespace-nowrap">
                {f.added > 0 && <span style={{ color: '#3fb950' }}>+{f.added}</span>}
                {f.removed > 0 && <span style={{ color: '#f85149' }} className="ml-1">−{f.removed}</span>}
                <DiffBar added={f.added} removed={f.removed} />
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* Planner — decomposition as a checklist */}
      {isPlanner && (
        <ul className="px-2.5 pb-2 space-y-0.5">
          {steps.slice(compact ? -4 : -10).map((s, i) => (
            <li
              key={s.text}
              className="subagent-row flex items-start gap-2 text-[13px] font-mono"
              style={{ animationDelay: `${i * 55}ms` }}
            >
              <span style={{ color: s.done ? '#3fb950' : withAlpha(color, 0.7) }}>
                {s.done ? '✓' : '▸'}
              </span>
              <span className={s.done ? 'text-zinc-500 line-through' : 'text-zinc-300'}>{s.text}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Anything else — a ticker of what it just called */}
      {!isBuilder && !isPlanner && tools.length > 0 && (
        <div className="px-2.5 pb-2 flex flex-wrap gap-1">
          {tools.map((t, i) => (
            <span
              key={`${t.name}-${i}`}
              className="subagent-row text-[12px] font-mono px-1.5 py-0.5 rounded"
              style={{ animationDelay: `${i * 55}ms`, background: withAlpha(color, 0.12), color: withAlpha(color, 0.95) }}
              title={t.arg}
            >
              {t.name}{t.arg ? ` ${basename(t.arg)}` : ''}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
