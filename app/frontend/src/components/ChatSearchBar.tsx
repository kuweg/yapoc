import { useEffect, useRef } from 'react'

/**
 * Find-in-conversation. Matching messages are outlined where they sit rather
 * than filtered into a list, so a hit keeps the surrounding turns that give it
 * meaning — and prev/next walks them in order.
 */
export function ChatSearchBar({
  query,
  onQuery,
  matchCount,
  activeIndex,
  onPrev,
  onNext,
  onClose,
}: {
  query: string
  onQuery: (value: string) => void
  matchCount: number
  activeIndex: number
  onPrev: () => void
  onNext: () => void
  onClose: () => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [])

  return (
    <div className="chat-search" role="search">
      <input
        ref={inputRef}
        value={query}
        onChange={(e) => onQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            if (e.shiftKey) onPrev()
            else onNext()
          }
          if (e.key === 'Escape') {
            e.preventDefault()
            onClose()
          }
        }}
        placeholder="Find in conversation"
        aria-label="Find in conversation"
      />
      <span className="chat-search-count">
        {query ? (matchCount > 0 ? `${activeIndex + 1} / ${matchCount}` : 'No matches') : ''}
      </span>
      <button type="button" onClick={onPrev} disabled={matchCount === 0} title="Previous match (Shift+Enter)">↑</button>
      <button type="button" onClick={onNext} disabled={matchCount === 0} title="Next match (Enter)">↓</button>
      <button type="button" onClick={onClose} title="Close search (Esc)">✕</button>
    </div>
  )
}
