import { memo, useState, useEffect, useRef } from 'react'

interface ThinkingBlockProps {
  text: string
  done: boolean
}

function ThinkingBlockImpl({ text, done }: ThinkingBlockProps) {
  const [expanded, setExpanded] = useState(true)
  const [displayedText, setDisplayedText] = useState('')
  const posRef = useRef(0)

  // Auto-expand while streaming
  useEffect(() => {
    if (!done) setExpanded(true)
  }, [done])

  // Robust typewriter: uses a ref for position so rapid text updates
  // don't cause stale-closure jumps or duplicate intervals.
  useEffect(() => {
    if (done) {
      setDisplayedText(text)
      posRef.current = text.length
      return
    }

    // If text shrank, clamp position and show what's available
    if (posRef.current > text.length) {
      posRef.current = text.length
      setDisplayedText(text)
      return
    }

    // Nothing new to reveal
    if (posRef.current >= text.length) return

    const interval = setInterval(() => {
      posRef.current++
      setDisplayedText(text.slice(0, posRef.current))
      if (posRef.current >= text.length) {
        clearInterval(interval)
      }
    }, 8) // ~120 chars/sec

    return () => clearInterval(interval)
  }, [text, done])

  return (
    <div className="rounded-lg border border-indigo-800/50 bg-indigo-950/40 text-indigo-300 text-xs my-1">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-2 w-full px-3 py-2 text-left hover:bg-indigo-900/20 rounded-lg"
      >
        {done ? (
          <span className="text-indigo-400">🔒</span>
        ) : (
          <span className="animate-pulse text-indigo-400">●</span>
        )}
        <span className="font-medium">{done ? 'Thinking' : 'Thinking…'}</span>
        <span className="ml-auto text-indigo-500">{expanded ? '▲' : '▼'}</span>
      </button>
      {expanded && (
        <pre className="px-3 pb-3 font-mono text-[13px] text-indigo-200/80 whitespace-pre-wrap break-words overflow-x-auto border-t border-indigo-800/30 pt-2">
          {displayedText}
          {!done && (
            <span className="inline-block w-1.5 h-3.5 bg-indigo-400/60 ml-0.5 animate-pulse align-middle" />
          )}
        </pre>
      )}
    </div>
  )
}

export const ThinkingBlock = memo(ThinkingBlockImpl)
