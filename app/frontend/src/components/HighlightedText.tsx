import { memo } from 'react'
import { tokenizeChatText, type ChatToken } from '../lib/chatTokens'
import { findCommand } from '../lib/chatCommands'
import { useAppStore } from '../store/appStore'

/**
 * Renders chat text with slash commands and `@` mentions coloured.
 *
 * `overlay` backs the composer's textarea and must not disturb a single glyph
 * position, or the caret drifts away from the text under it — so it styles
 * colour and background only, never padding, weight, or font. `inline` is used
 * in the transcript, where real chips are free to take up space.
 */
export type HighlightVariant = 'overlay' | 'inline'

function commandTitle(name: string, known: boolean): string {
  const found = findCommand(name)
  if (found) return `${found.cmd} — ${found.desc}`
  return known ? name : `${name} — not a known command`
}

function TokenSpan({ token, variant }: { token: ChatToken; variant: HighlightVariant }) {
  if (token.kind === 'text') return <>{token.text}</>
  if (token.kind === 'code') {
    return <span className={variant === 'overlay' ? 'chat-hl-code' : 'chat-hl-code chat-hl-chip'}>{token.text}</span>
  }
  if (token.kind === 'command') {
    return (
      <span
        className={`chat-hl-cmd ${token.known ? '' : 'chat-hl-unknown'} ${variant === 'inline' ? 'chat-hl-chip' : ''}`}
        title={variant === 'inline' ? commandTitle(token.name, token.known) : undefined}
      >
        {token.text}
      </span>
    )
  }
  const { subsystem, target } = token
  if (variant === 'overlay') {
    return <span className="chat-hl-mention">{token.text}</span>
  }
  if (subsystem.kind === 'whiteboard') {
    return (
      <button
        type="button"
        className="chat-hl-mention chat-hl-chip chat-hl-link"
        title={target ? `Open Whiteboard canvas: ${target}` : 'Open the collaborative whiteboard'}
        onClick={() => {
          if (target) localStorage.setItem('yapoc-whiteboard-target', target)
          useAppStore.getState().setActiveTab('whiteboard')
        }}
      >
        <span aria-hidden="true">{subsystem.icon}</span>
        {target ? `${subsystem.label}: ${target}` : subsystem.label}
      </button>
    )
  }
  return (
    <span
      className="chat-hl-mention chat-hl-chip"
      title={target ? `${subsystem.label}: ${target}` : `${subsystem.label} — ${subsystem.desc}`}
    >
      <span aria-hidden="true">{subsystem.icon}</span>
      {target ? `${subsystem.label}: ${target}` : subsystem.label}
    </span>
  )
}

function HighlightedTextImpl({
  text,
  variant = 'inline',
  className = '',
}: {
  text: string
  variant?: HighlightVariant
  className?: string
}) {
  const tokens = tokenizeChatText(text)
  return (
    <span className={`chat-hl ${className}`}>
      {tokens.map((token, i) => (
        <TokenSpan key={i} token={token} variant={variant} />
      ))}
      {/* A trailing newline is not rendered by the browser on its own; the
          overlay needs the extra line to stay the same height as the textarea. */}
      {variant === 'overlay' && text.endsWith('\n') ? '​' : null}
    </span>
  )
}

export const HighlightedText = memo(HighlightedTextImpl)
