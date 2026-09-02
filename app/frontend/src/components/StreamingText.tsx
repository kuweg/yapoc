import { useEffect, useState } from 'react'

/**
 * Per-token streaming fade (chat animation spec §3).
 *
 * Renders the already-settled prefix as plain text and wraps the newly-arrived
 * delta in `.token-new` so it fades in. On the fade's `animationend` the delta
 * is promoted into the settled prefix and the `.token-new` class is dropped —
 * so it never re-triggers on reflow (hard rule #5). The span is keyed by the
 * settled length so each fresh chunk gets its own animation instead of React
 * reusing the element (which would skip the restart).
 *
 * Streaming content is intentionally rendered as plain text; the final settled
 * message is re-rendered with markdown by MessageBubble once streaming ends.
 */
export function StreamingText({ text }: { text: string }) {
  const [settledLen, setSettledLen] = useState(0)

  // Resync if the text was reset/shrunk (new stream into the same element).
  useEffect(() => {
    if (text.length < settledLen) setSettledLen(0)
  }, [text, settledLen])

  const safeLen = Math.min(settledLen, text.length)
  const settled = text.slice(0, safeLen)
  const delta = text.slice(safeLen)

  return (
    <span className="whitespace-pre-wrap break-words">
      {settled}
      {delta && (
        <span
          key={safeLen}
          className="token-new"
          onAnimationEnd={() => setSettledLen(text.length)}
        >
          {delta}
        </span>
      )}
    </span>
  )
}
