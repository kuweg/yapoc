import { filterCommands } from './chatCommands'
import { mentionEntities } from './mentionSources'
import {
  MENTION_SUBSYSTEMS,
  subsystemForKind,
  type MentionKind,
  type MentionSubsystem,
} from './mentions'

/**
 * What the composer palette should offer for the text around the caret.
 *
 * Mentions are two-level on purpose, mirroring how people talk about the
 * system: `@notes` means "the Notes system, go look there", and `@note:x` means
 * one specific note. Picking an addressable subsystem therefore does not finish
 * the mention — it drills in, inserting `@note:` and leaving the palette open on
 * that subsystem's entities, with a row to fall back to the whole system.
 */
export interface Suggestion {
  id: string
  group: string
  icon?: string
  name: string
  args?: string
  desc: string
  /** Replaces the trigger span in the text. */
  insert: string
  /** Keep the palette open after inserting (the mention is not finished yet). */
  keepOpen?: boolean
}

export interface TriggerMatch {
  /** Span of the full text this suggestion replaces. */
  start: number
  end: number
  suggestions: Suggestion[]
  /** Entity list to warm before the palette can show anything useful. */
  needsSource?: MentionKind
}

// A mention target may be quoted, because plenty of note titles and file names
// contain spaces and a bare target ends at the first one.
const MENTION_RE = /(?:^|\s)@([A-Za-z_]*)(?::(?:"([^"\n]*)"?|([^\s@"]*)))?$/

function subsystemRow(subsystem: MentionSubsystem): Suggestion {
  return {
    id: `system:${subsystem.plural}`,
    group: 'Systems',
    icon: subsystem.icon,
    name: `@${subsystem.plural}`,
    desc: subsystem.desc,
    insert: subsystem.addressable ? `@${subsystem.kind}:` : `@${subsystem.plural} `,
    keepOpen: subsystem.addressable,
  }
}

function wholeSystemRow(subsystem: MentionSubsystem): Suggestion {
  return {
    id: `whole:${subsystem.plural}`,
    group: subsystem.label,
    icon: subsystem.icon,
    name: `@${subsystem.plural}`,
    desc: `The whole ${subsystem.label} system, not one entry`,
    insert: `@${subsystem.plural} `,
  }
}

function entityRows(subsystem: MentionSubsystem, query: string): Suggestion[] {
  return mentionEntities(subsystem.kind, query).map((entity) => ({
    id: `${subsystem.kind}:${entity.value}`,
    group: subsystem.label,
    icon: subsystem.icon,
    // Values with spaces have to be quoted, or the mention would end at the
    // first space and swallow the rest as prose.
    name: `@${subsystem.kind}:${/\s/.test(entity.value) ? `"${entity.value}"` : entity.value}`,
    desc: entity.desc,
    insert: `@${subsystem.kind}:${/\s/.test(entity.value) ? `"${entity.value}"` : entity.value} `,
  }))
}

/**
 * Inspect the text before the caret and decide what to offer. Returns null when
 * the caret is not sitting in a command or mention.
 */
export function detectTrigger(text: string, caret: number): TriggerMatch | null {
  const before = text.slice(0, caret)

  // Slash commands only run as the very first thing in a message, so the
  // palette only offers them there — and only until the name is complete.
  if (before.startsWith('/') && !/\s/.test(before)) {
    const commands = filterCommands(before)
    if (commands.length > 0) {
      return {
        start: 0,
        end: caret,
        suggestions: commands.map((c) => ({
          id: `cmd:${c.cmd}`,
          group: 'Commands',
          name: c.cmd,
          args: c.args,
          desc: c.client ? `${c.desc} (in-browser)` : c.desc,
          insert: `${c.cmd} `,
        })),
      }
    }
  }

  const mention = MENTION_RE.exec(before)
  if (!mention) return null
  const [matched, rawName, quotedTarget, bareTarget] = mention
  const target = quotedTarget ?? bareTarget
  const start = mention.index + (matched.startsWith('@') ? 0 : 1)

  if (target !== undefined) {
    // `@kind:` — list that subsystem's entities.
    const subsystem = subsystemForKind(rawName)
    if (!subsystem) return null
    return {
      start,
      end: caret,
      needsSource: subsystem.kind,
      suggestions: [wholeSystemRow(subsystem), ...entityRows(subsystem, target)],
    }
  }

  // `@` or a partial name — list matching subsystems. When the partial already
  // names an addressable subsystem exactly, show its entities too so `@note`
  // does not dead-end before the colon is typed.
  const needle = rawName.toLowerCase()
  const matches = MENTION_SUBSYSTEMS.filter(
    (s) => s.plural.startsWith(needle) || s.kind.startsWith(needle),
  )
  const exact = MENTION_SUBSYSTEMS.find(
    (s) => s.addressable && (s.kind === needle || s.plural === needle),
  )
  const suggestions = [...matches.map(subsystemRow), ...(exact ? entityRows(exact, '') : [])]
  if (suggestions.length === 0) return null
  return { start, end: caret, suggestions, needsSource: exact?.kind }
}
