import { useState } from 'react'

interface ThinkingBlockProps {
  text: string
  done: boolean
}

export function ThinkingBlock({ text, done }: ThinkingBlockProps) {
  const [expanded, setExpanded] = useState(false)

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
        <pre className="px-3 pb-3 font-mono text-[11px] text-indigo-200/80 whitespace-pre-wrap break-words overflow-x-auto border-t border-indigo-800/30 pt-2">
          {text}
        </pre>
      )}
    </div>
  )
}
