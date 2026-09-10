/**
 * The slash commands the chat composer understands.
 *
 * Single source of truth: the composer's autocomplete, the highlighter (which
 * only lights up a `/token` it can recognise), and `/help`'s own output all
 * read this list. It previously lived twice — once as a const in ChatInput and
 * once hand-written as a markdown table in ChatPanel's `_helpText()` — and the
 * two had already drifted.
 */
export interface SlashCommand {
  cmd: string
  desc: string
  /** Argument hint shown after the command in the palette, e.g. `<id>`. */
  args?: string
  /** Handled in the browser with no backend round trip. */
  client?: boolean
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { cmd: '/help', desc: 'Show available commands', client: true },
  { cmd: '/clear', desc: 'Clear conversation and start a new session', client: true },
  { cmd: '/ping', desc: 'Ping the server and show response time' },
  { cmd: '/status', desc: 'Show server & agent status' },
  { cmd: '/agents', desc: 'List all agents' },
  { cmd: '/model', desc: 'Show current adapter/model' },
  { cmd: '/cost', desc: 'Show session cost breakdown' },
  { cmd: '/sessions', desc: 'List recent sessions' },
  { cmd: '/continue', desc: 'Resume the latest session' },
  { cmd: '/resume', desc: 'Resume a specific session', args: '<id>' },
  { cmd: '/export', desc: 'Export conversation to file', args: '<filename>' },
  { cmd: '/doctor', desc: 'Run doctor health check' },
  { cmd: '/start', desc: 'Start the backend server' },
  { cmd: '/stop', desc: 'Stop the backend server' },
  { cmd: '/restart', desc: 'Restart the backend server' },
  { cmd: '/exit', desc: 'No-op in the web UI', client: true },
]

const BY_NAME = new Map(SLASH_COMMANDS.map((c) => [c.cmd, c]))

/** Look up a command by its exact `/name` (case-insensitive). */
export function findCommand(token: string): SlashCommand | undefined {
  return BY_NAME.get(token.toLowerCase())
}

/** True when `/token` names a real command — the highlighter's gate. */
export function isKnownCommand(token: string): boolean {
  return BY_NAME.has(token.toLowerCase())
}

/**
 * Commands whose name starts with what the user has typed so far. `typed` may
 * carry arguments (`/resume abc`); once a full command plus a space is present
 * there is nothing left to complete, so the list is empty.
 */
export function filterCommands(typed: string): SlashCommand[] {
  if (!typed.startsWith('/')) return []
  const head = typed.split(/\s/)[0].toLowerCase()
  if (head !== typed.toLowerCase()) return []
  return SLASH_COMMANDS.filter((c) => c.cmd.startsWith(head))
}

/** The `/help` response, rendered from the same list the palette uses. */
export function commandHelpTable(): string {
  const rows = SLASH_COMMANDS.map(
    ({ cmd, args, desc }) => `| \`${args ? `${cmd} ${args}` : cmd}\` | ${desc} |`,
  )
  return ['**Available commands:**', '', '| Command | Description |', '|---------|-------------|', ...rows].join('\n')
}
