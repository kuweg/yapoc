import { useEffect, useRef } from 'react'
import type { Suggestion } from '../lib/composerSuggest'

/**
 * The composer's autocomplete list — one palette for slash commands and every
 * `@` mention kind, so there is a single set of keys to learn. Rows are grouped
 * by source but navigated as one flat list, which is what `activeIndex` indexes.
 */
export function ComposerSuggestions({
  suggestions,
  activeIndex,
  onPick,
  onHover,
  emptyLabel,
}: {
  suggestions: Suggestion[]
  activeIndex: number
  onPick: (suggestion: Suggestion) => void
  onHover: (index: number) => void
  emptyLabel?: string
}) {
  const activeRef = useRef<HTMLButtonElement>(null)

  // Keep the keyboard selection in view when the list is longer than the panel.
  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex])

  if (suggestions.length === 0) {
    return (
      <div className="composer-menu" role="listbox" aria-label="Suggestions">
        <div className="composer-menu-empty">{emptyLabel ?? 'No matches'}</div>
      </div>
    )
  }

  let lastGroup = ''
  return (
    <div className="composer-menu" role="listbox" aria-label="Suggestions">
      {suggestions.map((suggestion, i) => {
        const heading = suggestion.group !== lastGroup ? suggestion.group : null
        lastGroup = suggestion.group
        const selected = i === activeIndex
        return (
          <div key={suggestion.id}>
            {heading && <div className="composer-menu-group">{heading}</div>}
            <button
              ref={selected ? activeRef : undefined}
              type="button"
              role="option"
              aria-selected={selected}
              className="composer-menu-item"
              // Mousedown, not click: the textarea must not lose focus first, or
              // the caret position the insertion is relative to is already gone.
              onMouseDown={(e) => {
                e.preventDefault()
                onPick(suggestion)
              }}
              onMouseEnter={() => onHover(i)}
            >
              {suggestion.icon && <span aria-hidden="true">{suggestion.icon}</span>}
              <span className="composer-menu-name">{suggestion.name}</span>
              {suggestion.args && <span className="composer-menu-args">{suggestion.args}</span>}
              <span className="composer-menu-desc">{suggestion.desc}</span>
            </button>
          </div>
        )
      })}
      <div className="composer-menu-foot">
        <span>↑↓ move</span>
        <span>Tab / Enter insert</span>
        <span>Esc dismiss</span>
      </div>
    </div>
  )
}
