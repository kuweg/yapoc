import { getAgents, getTasks, listUploads } from '../api/client'
import { getPlugins } from '../api/pluginsClient'
import { getSkills } from '../api/skillsClient'
import { listArtifacts } from '../artifacts/api'
import { listNotes } from '../notes/api'
import { listBoards } from '../whiteboard/api'
import { request as bookRequest, type Book } from '../books/api'
import { MENTION_SUBSYSTEMS, type MentionKind, type MentionSources } from './mentions'

/**
 * The entity lists behind `@` mentions, fetched on demand and shared by the
 * composer's palette and the submit-time resolver.
 *
 * One module-level cache rather than per-component state: the palette asks for
 * a list the moment `@note:` is typed, and submit asks again for whatever kinds
 * survived into the text — both want the same answer, and a note that was just
 * created should show up, hence the short TTL rather than a load-once cache.
 */
const TTL_MS = 20_000

const sources: MentionSources = {}
const fetchedAt = new Map<MentionKind, number>()
const inflight = new Map<MentionKind, Promise<boolean>>()

/** One palette row: `value` is inserted after `@kind:`, never displayed raw. */
export interface MentionEntity {
  value: string
  label: string
  desc: string
}

interface Source {
  load: () => Promise<void>
  rows: () => MentionEntity[]
}

const SOURCES: Partial<Record<MentionKind, Source>> = {
  book: {
    load: async () => {
      const books = await bookRequest<Book[]>()
      // Validate before replacing the cache: a failed or malformed response
      // must not turn the next autocomplete render into an application crash.
      if (!Array.isArray(books)) throw new Error('Invalid book list')
      sources.books = books.filter(b => b && typeof b.id === 'string' && typeof b.title === 'string')
    },
    rows: () => (sources.books ?? []).map(b => ({
      value: b.title.includes('"') ? b.id : b.title,
      label: b.title,
      desc: `${b.author || 'Book'} · ${b.position}/${b.total}`,
    })),
  },
  note: {
    load: async () => {
      const { notes } = await listNotes()
      sources.notes = notes.map((n) => ({ id: n.id, title: n.title, excerpt: n.excerpt }))
    },
    rows: () =>
      (sources.notes ?? []).map((n) => ({
        value: n.title,
        label: n.title,
        desc: n.excerpt?.slice(0, 70) || 'Note',
      })),
  },
  agent: {
    load: async () => {
      const agents = await getAgents()
      sources.agents = agents.map((a) => ({ name: a.name, model: a.model, status: a.status }))
    },
    rows: () =>
      (sources.agents ?? []).map((a) => ({
        value: a.name,
        label: a.name,
        desc: [a.status, a.model].filter(Boolean).join(' · ') || 'Agent',
      })),
  },
  file: {
    load: async () => {
      const { files } = await listUploads()
      sources.uploads = files
    },
    rows: () =>
      (sources.uploads ?? []).map((f) => ({ value: f.name, label: f.name, desc: f.mime || 'Uploaded file' })),
  },
  artifact: {
    load: async () => {
      sources.artifacts = await listArtifacts()
    },
    rows: () =>
      (sources.artifacts ?? []).map((a) => ({ value: a.name, label: a.name, desc: a.path })),
  },
  skill: {
    load: async () => {
      const skills = await getSkills()
      sources.skills = skills.map((s) => ({ name: s.name, summary: s.summary ?? undefined }))
    },
    rows: () =>
      (sources.skills ?? []).map((s) => ({ value: s.name, label: s.name, desc: s.summary || 'Skill' })),
  },
  plugin: {
    load: async () => {
      const plugins = await getPlugins()
      sources.plugins = plugins.map((p) => ({
        name: p.name,
        display_name: p.display_name,
        description: p.description,
        enabled: p.enabled,
      }))
    },
    rows: () =>
      (sources.plugins ?? []).map((p) => ({
        value: p.name,
        label: p.display_name || p.name,
        desc: p.enabled === false ? 'Disabled' : p.description?.slice(0, 70) || 'Plugin',
      })),
  },
  task: {
    load: async () => {
      const tasks = await getTasks(30)
      sources.tasks = tasks.map((t) => ({ id: t.id, prompt: t.prompt, status: t.status }))
    },
    rows: () =>
      (sources.tasks ?? []).map((t) => ({
        value: t.id,
        label: t.id.slice(0, 8),
        desc: [t.status, t.prompt?.slice(0, 60)].filter(Boolean).join(' · ') || 'Task',
      })),
  },
  whiteboard: {
    load: async () => {
      const boards = await listBoards()
      sources.whiteboards = boards.map((b) => ({ id: b.id, name: b.name, description: b.description }))
    },
    rows: () =>
      (sources.whiteboards ?? []).map((b) => ({
        value: b.name,
        label: b.name,
        desc: b.description?.slice(0, 70) || `Canvas ${b.id}`,
      })),
  },
}

/** Kinds the palette can list entities for. */
export const ADDRESSABLE_KINDS: MentionKind[] = MENTION_SUBSYSTEMS.filter(
  (s) => s.addressable && SOURCES[s.kind],
).map((s) => s.kind)

/**
 * Fetch one kind's entities unless a fresh copy is already cached. Resolves to
 * true only when a fetch actually ran, which is what lets a caller re-render on
 * new rows without looping: once the cache is warm the answer is false.
 *
 * Failures are swallowed on purpose — an unreachable backend should leave the
 * palette empty, not break typing — and still stamp the clock, so a down
 * backend is retried on the TTL rather than on every keystroke.
 */
export function ensureMentionSource(kind: MentionKind): Promise<boolean> {
  const source = SOURCES[kind]
  if (!source) return Promise.resolve(false)
  const age = Date.now() - (fetchedAt.get(kind) ?? 0)
  if (age < TTL_MS) return Promise.resolve(false)
  const existing = inflight.get(kind)
  if (existing) return existing
  const promise = source
    .load()
    .catch(() => {})
    .then(() => {
      fetchedAt.set(kind, Date.now())
      inflight.delete(kind)
      return true
    })
  inflight.set(kind, promise)
  return promise
}

/** Load every kind a piece of text actually mentions, before resolving it. */
export function ensureMentionSourcesFor(text: string): Promise<void> {
  const needed = MENTION_SUBSYSTEMS.filter(
    (s) =>
      s.addressable &&
      SOURCES[s.kind] &&
      new RegExp(`@(?:${s.kind}|${s.plural})\\b`, 'i').test(text),
  ).map((s) => s.kind)
  return Promise.all(needed.map(ensureMentionSource)).then(() => {})
}

/** Palette rows for a kind, filtered by what the user has typed after the colon. */
export function mentionEntities(kind: MentionKind, query: string): MentionEntity[] {
  const rows = SOURCES[kind]?.rows() ?? []
  const needle = query.trim().toLowerCase()
  if (!needle) return rows.slice(0, 8)
  const norm = (value: string) => value.toLowerCase().replace(/[\s_-]+/g, ' ')
  const target = norm(needle)
  return rows
    .filter((row) => norm(row.label).includes(target) || norm(row.value).includes(target))
    .slice(0, 8)
}

/** The live lists, for `resolveMentions`. */
export function mentionSources(): MentionSources {
  return sources
}
