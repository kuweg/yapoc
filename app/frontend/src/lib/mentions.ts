import type { Attachment } from '../api/types'
import type { Artifact } from '../artifacts/types'

/**
 * `@` mentions let a message point at a part of YAPOC. Two shapes are
 * supported, and both are offered by the composer's palette:
 *
 *   @notes                 the subsystem as a whole ("go look in Notes")
 *   @note:my_first_note    one specific entity inside it
 *
 * A subsystem mention is rewritten into a short bracketed hint so master reads
 * an instruction rather than a bare token. A specific mention is resolved
 * against the live list for that subsystem, so a typo degrades to plain prose
 * instead of silently meaning nothing.
 */
export type MentionKind =
  | 'file'
  | 'artifact'
  | 'note'
  | 'agent'
  | 'skill'
  | 'plugin'
  | 'task'
  | 'cron'
  | 'memory'
  | 'whiteboard'
  | 'book'
  | 'repo'

export interface MentionSubsystem {
  kind: MentionKind
  /** Token naming the whole subsystem, e.g. `notes` in `@notes`. */
  plural: string
  label: string
  icon: string
  /** Palette description for the subsystem row. */
  desc: string
  /** Substituted for a bare subsystem mention, inside `[system: … ]`. */
  hint: string
  /** False when the subsystem has no individually addressable entity. */
  addressable: boolean
}

export const MENTION_SUBSYSTEMS: MentionSubsystem[] = [
  {kind:'book',plural:'books',label:'Books',icon:'📚',desc:'Your reading library',hint:'the Books library. Use book_list to discover books and book_read for source passages. Retain source locations in your answer.',addressable:true},
  {
    kind: 'note',
    plural: 'notes',
    label: 'Notes',
    icon: '📝',
    desc: 'The Notes system — user-owned markdown notes',
    hint: 'Notes, the user-owned markdown note system under app/projects/notes. Read or write notes there rather than agent memory.',
    addressable: true,
  },
  {
    kind: 'agent',
    plural: 'agents',
    label: 'Agents',
    icon: '🤖',
    desc: 'The agent roster — delegate or inspect an agent',
    hint: 'the agent roster. Inspect an agent\'s files or delegate work to it.',
    addressable: true,
  },
  {
    kind: 'file',
    plural: 'files',
    label: 'Files',
    icon: '📎',
    desc: 'Uploaded files in this workspace',
    hint: 'the uploaded files in this workspace.',
    addressable: true,
  },
  {
    kind: 'artifact',
    plural: 'artifacts',
    label: 'Artifacts',
    icon: '📦',
    desc: 'The artifact registry — files agents produced',
    hint: 'the artifact registry, which holds the files agents have produced.',
    addressable: true,
  },
  {
    kind: 'skill',
    plural: 'skills',
    label: 'Skills',
    icon: '🎯',
    desc: 'The skills library',
    hint: 'the skills library.',
    addressable: true,
  },
  {
    kind: 'plugin',
    plural: 'plugins',
    label: 'Plugins',
    icon: '🔌',
    desc: 'Installed plugins and the tools they register',
    hint: 'the installed plugins and the tools they register.',
    addressable: true,
  },
  {
    kind: 'task',
    plural: 'tasks',
    label: 'Tasks',
    icon: '📋',
    desc: 'The task queue',
    hint: 'the task queue.',
    addressable: true,
  },
  {
    kind: 'cron',
    plural: 'cron',
    label: 'Cron',
    icon: '⏱️',
    desc: 'Scheduled and recurring tasks',
    hint: 'the cron system, which owns scheduled and recurring tasks.',
    addressable: false,
  },
  {
    kind: 'memory',
    plural: 'memory',
    label: 'Memory',
    icon: '🧠',
    desc: 'Agent memory and shared knowledge',
    hint: 'agent memory (MEMORY.MD) and the shared knowledge store.',
    addressable: false,
  },
  {
    kind: 'whiteboard',
    plural: 'whiteboard',
    label: 'Whiteboard',
    icon: '▦',
    desc: 'The shared collaborative whiteboard',
    hint: 'the shared architecture canvases. Use whiteboard_list to find the relevant canvas, then read its typed nodes, structured details, and relationships before answering or acting. Prefer @whiteboard:<canvas_name> when the intended canvas is known.',
    addressable: true,
  },
  {
    kind: 'repo',
    plural: 'repo',
    label: 'Repository',
    icon: '📁',
    desc: 'The project repository',
    hint: 'the project repository at its root.',
    addressable: false,
  },
]

const BY_PLURAL = new Map(MENTION_SUBSYSTEMS.map((s) => [s.plural, s]))
const BY_KIND = new Map(MENTION_SUBSYSTEMS.map((s) => [s.kind as string, s]))

/**
 * Every token that names a subsystem, as a regex alternation. Plurals come
 * first so `notes` wins over `note`, and longest-first within each group so an
 * alternation never matches a shorter prefix of a longer token.
 */
const SUBSYSTEM_TOKENS = [
  ...MENTION_SUBSYSTEMS.map((s) => s.plural),
  ...MENTION_SUBSYSTEMS.filter((s) => s.addressable && s.kind !== s.plural).map((s) => s.kind),
]
  .sort((a, b) => b.length - a.length)
  .join('|')

/** The subsystem a bare `@token` names, if any (`@notes`, `@repo`, …). */
export function subsystemForPlural(token: string): MentionSubsystem | undefined {
  return BY_PLURAL.get(token.toLowerCase())
}

/** The subsystem a specific `@token:target` names, if any (`@note:x`). */
export function subsystemForKind(token: string): MentionSubsystem | undefined {
  const found = BY_KIND.get(token.toLowerCase())
  return found?.addressable ? found : undefined
}

/** Entities the resolver matches specific mentions against. */
export interface MentionSources {
  uploads?: Attachment[]
  artifacts?: Artifact[]
  notes?: Array<{ id: string; title: string; excerpt?: string }>
  agents?: Array<{ name: string; model?: string; status?: string }>
  skills?: Array<{ name: string; summary?: string }>
  plugins?: Array<{ name: string; display_name?: string; description?: string; enabled?: boolean }>
  tasks?: Array<{ id: string; prompt?: string; status?: string }>
  whiteboards?: Array<{ id: string; name: string; description?: string }>
}

export interface ResolvedMentions {
  /** What master receives: subsystem mentions expanded into instructions. */
  cleanedText: string
  /**
   * What the user sees in their own bubble: the same text with `@notes` left as
   * `@notes`. Expanding a subsystem in the transcript replaced a two-word
   * question with a paragraph the user never wrote.
   */
  displayText: string
  attachmentIds: string[]
  repoRef: boolean
  artifactRefs: string[]
  /** Note ids to send as `note_ids` — the backend inlines their content. */
  noteIds: string[]
  agentRefs: string[]
  skillRefs: string[]
  pluginRefs: string[]
  taskRefs: string[]
  whiteboardRefs: string[]
  /** Subsystems mentioned as a whole. */
  subsystems: MentionKind[]
  /** Specific mentions that matched nothing, for a composer warning. */
  unresolved: Array<{ kind: MentionKind; query: string }>
}

function findByName<T extends { name: string }>(items: T[], name: string): T | undefined {
  const query = name.trim().toLowerCase()
  if (!query) return undefined
  return items.find((item) => item.name.toLowerCase() === query)
    ?? items.find((item) => item.name.toLowerCase().startsWith(query))
}

/**
 * A mention target: `"quoted, with spaces"` or a bare run. Contributes two
 * capture groups, only one of which is ever set.
 */
const TARGET = '(?:"([^"\\n]+)"|([^\\s@"][^\\s@]*))'

/** Wrap a resolved target in quotes when it would otherwise end at a space. */
function quoteIfNeeded(value: string): string {
  return /[\s"]/.test(value) ? `"${value.replace(/"/g, '')}"` : value
}

/** Notes match on id, title, or title with `_` and `-` treated as spaces. */
function normalizeNoteKey(value: string): string {
  return value.trim().toLowerCase().replace(/\.md$/, '').replace(/[\s_-]+/g, ' ')
}

function findNote(
  notes: Array<{ id: string; title: string }>,
  query: string,
): { id: string; title: string } | undefined {
  const key = normalizeNoteKey(decodeURIComponent(query))
  if (!key) return undefined
  return notes.find((n) => normalizeNoteKey(n.id) === key || normalizeNoteKey(n.title) === key)
    ?? notes.find((n) => normalizeNoteKey(n.title).startsWith(key))
}

export function resolveMentions(
  rawText: string,
  uploads: Attachment[],
  artifacts: Artifact[],
  extra: MentionSources = {},
): ResolvedMentions {
  const attachmentIds: string[] = []
  const artifactRefs: string[] = []
  const noteIds: string[] = []
  const agentRefs: string[] = []
  const skillRefs: string[] = []
  const pluginRefs: string[] = []
  const taskRefs: string[] = []
  const whiteboardRefs: string[] = []
  const subsystems: MentionKind[] = []
  const unresolved: Array<{ kind: MentionKind; query: string }> = []

  // Match `@file:<id>` (32-hex) or `@file <name>` / `@file:<name>` anywhere in
  // the text — NOT only at line-end/mention boundaries. The previous lookahead
  // required the token to be followed by end-of-string/newline/another mention,
  // so a mid-sentence reference like "review @file:abc123 thanks" was silently
  // left unresolved. The id/name capture is bounded by whitespace or a following
  // @mention so it can't swallow trailing prose.
  let cleanedText = rawText.replace(new RegExp(`@file(?::([a-f0-9]{32})|(?::|\\s+)${TARGET})`, 'gi'), (token, id: string | undefined, quoted: string | undefined, bare: string | undefined) => {
    const name = quoted ?? bare
    const upload = id
      ? uploads.find((item) => item.id === id)
      : findByName(uploads, name ?? '')
    if (!upload?.id) {
      unresolved.push({ kind: 'file', query: id ?? name ?? '' })
      return token
    }
    if (!attachmentIds.includes(upload.id)) attachmentIds.push(upload.id)
    return ''
  })

  cleanedText = cleanedText.replace(new RegExp(`@artifact(?::|\\s+)${TARGET}`, 'gi'), (token, quoted: string | undefined, bare: string | undefined) => {
    const name = quoted ?? bare ?? ''
    const artifact = findByName(artifacts, name)
    if (!artifact) {
      unresolved.push({ kind: 'artifact', query: name })
      return token
    }
    if (!artifactRefs.includes(artifact.path)) artifactRefs.push(artifact.path)
    return `@artifact:${quoteIfNeeded(artifact.path)}`
  })

  // A note is delivered through `note_ids`, never through the text token: the
  // backend's own `@note:(\S+)` scan feeds straight into read_note, which 400s
  // on an id without a `.md` suffix and 404s on one that doesn't exist — either
  // of which rejects the WHOLE message. So a resolved note becomes the readable
  // `@note "Title"` (no colon, so that scan can't see it) and an unresolved one
  // is neutered the same way instead of being left to fail the request.
  cleanedText = cleanedText.replace(new RegExp(`@note:${TARGET}`, 'gi'), (_token, quoted: string | undefined, bare: string | undefined) => {
    const query = quoted ?? bare ?? ''
    const note = findNote(extra.notes ?? [], query)
    if (!note) {
      unresolved.push({ kind: 'note', query })
      return `@note "${decodeURIComponent(query).replace(/\.md$/i, '')}"`
    }
    if (!noteIds.includes(note.id)) noteIds.push(note.id)
    return `@note "${note.title}"`
  })

  // Most readable `@kind:name` tokens stay in the text for master to act on.
  // `@whiteboard:name` is also resolved and snapshotted by the task API.
  const simpleKinds: Array<{
    kind: MentionKind
    names: () => string[]
    collect: string[]
  }> = [
    { kind: 'agent', names: () => (extra.agents ?? []).map((a) => a.name), collect: agentRefs },
    { kind: 'skill', names: () => (extra.skills ?? []).map((s) => s.name), collect: skillRefs },
    { kind: 'plugin', names: () => (extra.plugins ?? []).map((p) => p.name), collect: pluginRefs },
    { kind: 'task', names: () => (extra.tasks ?? []).map((t) => t.id), collect: taskRefs },
    { kind: 'whiteboard', names: () => (extra.whiteboards ?? []).map((b) => b.name), collect: whiteboardRefs },
  ]
  for (const { kind, names, collect } of simpleKinds) {
    cleanedText = cleanedText.replace(new RegExp(`@${kind}:${TARGET}`, 'gi'), (token, quoted: string | undefined, bare: string | undefined) => {
      const query = quoted ?? bare ?? ''
      const candidates = names().map((name) => ({ name }))
      const normalizedQuery = query.trim().toLowerCase().replace(/[\s_-]+/g, ' ')
      const match = kind === 'whiteboard'
        ? candidates.find((item) => item.name.toLowerCase().replace(/[\s_-]+/g, ' ') === normalizedQuery)?.name
        : findByName(candidates, query)?.name
      if (!match) {
        // Left literal: harmless in the prompt, and the list may simply not
        // have loaded. Recorded so the composer can flag it.
        unresolved.push({ kind, query })
        return token
      }
      if (!collect.includes(match)) collect.push(match)
      return `@${kind}:${quoteIfNeeded(match)}`
    })
  }

  // Bare subsystem mentions, last: every specific form above has already been
  // consumed, so `@notes` can no longer be confused with `@note:x`. The bare
  // singular counts as a subsystem mention too — "@note" plainly means Notes.
  // Plurals lead the alternation so `@notes` never matches as `@note` + "s",
  // and the two lookaheads skip what the passes above deliberately left
  // behind: an unresolved `@agent:typo` and a rewritten `@note "Title"`.
  const displayText = cleanedText
  cleanedText = cleanedText.replace(new RegExp(`@(${SUBSYSTEM_TOKENS})\\b(?!:)(?!\\s*")`, 'gi'), (_token, name: string) => {
    const subsystem = subsystemForPlural(name) ?? subsystemForKind(name)!
    if (!subsystems.includes(subsystem.kind)) subsystems.push(subsystem.kind)
    return `[system: ${subsystem.label} — ${subsystem.hint}]`
  })

  const repoRef = subsystems.includes('repo')
  const tidy = (value: string) => value.replace(/[ \t]{2,}/g, ' ').replace(/ *\n */g, '\n').trim()

  return {
    cleanedText: tidy(cleanedText),
    displayText: tidy(displayText),
    attachmentIds,
    repoRef,
    artifactRefs,
    noteIds,
    agentRefs,
    skillRefs,
    pluginRefs,
    taskRefs,
    whiteboardRefs,
    subsystems,
    unresolved,
  }
}
