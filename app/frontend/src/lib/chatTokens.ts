import { isKnownCommand } from './chatCommands'
import { subsystemForKind, subsystemForPlural, type MentionSubsystem } from './mentions'

/**
 * Splits chat text into the runs the UI wants to colour: slash commands and
 * `@` mentions, with inline code spans carved out first so a backticked
 * `/example` stays literal.
 *
 * One tokenizer serves both the composer's highlight overlay and the user
 * message bubbles, so a command looks the same while you type it and after you
 * send it. The overlay depends on the token text concatenating back to exactly
 * the input — every character lands in some token, in order.
 */
export type ChatToken =
  | { kind: 'text'; text: string }
  | { kind: 'code'; text: string }
  | { kind: 'command'; text: string; name: string; known: boolean }
  | { kind: 'mention'; text: string; subsystem: MentionSubsystem; target?: string }

const CODE_RE = /`[^`\n]*`/g
// A `/command`, or an `@mention` as `@kind`, `@kind:target`, `@kind:"target"`,
// or `@kind "target"` — the last being what resolveMentions rewrites a note
// into. Targets are quotable because note titles and file names contain spaces.
const TOKEN_RE = /(\/[A-Za-z][\w-]*)|@([A-Za-z_]+)(?::(?:"([^"\n]*)"|([^\s@"]+))|[ \t]*"([^"\n]*)")?/g

function pushText(out: ChatToken[], text: string) {
  if (!text) return
  const last = out[out.length - 1]
  if (last?.kind === 'text') last.text += text
  else out.push({ kind: 'text', text })
}

/**
 * Tokenize one code-free run. `base` is the run's offset in the full string, so
 * "is this at the very start of the message" stays answerable.
 */
function tokenizeRun(run: string, base: number, out: ChatToken[]) {
  let last = 0
  TOKEN_RE.lastIndex = 0
  for (let m = TOKEN_RE.exec(run); m; m = TOKEN_RE.exec(run)) {
    const [matched, command, mentionName, colonQuoted, colonBare, spaceQuoted] = m
    const target = colonQuoted ?? colonBare ?? spaceQuoted
    const abs = base + m.index
    const before = m.index === 0 ? (base === 0 ? '' : ' ') : run[m.index - 1]
    const after = run[m.index + matched.length] ?? ''
    let token: ChatToken | null = null

    if (command) {
      // Only after whitespace, and never when a `/` follows — that is a path
      // (`/home/kuweg/...`), not a command. A known command highlights
      // anywhere it is mentioned; an unknown one only in the position where it
      // would actually run, so a typo there reads as a typo.
      const standalone = /\s/.test(before) || before === ''
      const known = isKnownCommand(command)
      if (standalone && after !== '/' && (known || abs === 0)) {
        token = { kind: 'command', text: matched, name: command, known }
      }
    } else if (mentionName) {
      // An unrecognised `@word` is left alone: it is far more likely a handle
      // or an email than a mention of something YAPOC has. With a target the
      // singular kind is the better reading of the token, without one the
      // subsystem is.
      const subsystem = target !== undefined
        ? subsystemForKind(mentionName) ?? subsystemForPlural(mentionName)
        : subsystemForPlural(mentionName) ?? subsystemForKind(mentionName)
      if (subsystem) token = { kind: 'mention', text: matched, subsystem, target }
    }

    if (token) {
      pushText(out, run.slice(last, m.index))
      out.push(token)
      last = m.index + matched.length
    }
  }
  pushText(out, run.slice(last))
}

export function tokenizeChatText(text: string): ChatToken[] {
  const out: ChatToken[] = []
  let last = 0
  CODE_RE.lastIndex = 0
  for (let m = CODE_RE.exec(text); m; m = CODE_RE.exec(text)) {
    tokenizeRun(text.slice(last, m.index), last, out)
    out.push({ kind: 'code', text: m[0] })
    last = m.index + m[0].length
  }
  tokenizeRun(text.slice(last), last, out)
  return out
}

/** True when the text carries anything worth colouring. */
export function hasHighlights(tokens: ChatToken[]): boolean {
  return tokens.some((t) => t.kind === 'command' || t.kind === 'mention')
}
