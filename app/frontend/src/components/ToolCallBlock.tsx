import { useState } from 'react'

interface ToolCallBlockProps {
  id: string
  name: string
  input: Record<string, unknown>
  result?: string
  isError?: boolean
  done: boolean
}

export function ToolCallBlock({ id: _id, name, input, result, isError, done }: ToolCallBlockProps) {
  const [open, setOpen] = useState(false)

  return (
    <div className="my-1 rounded border border-zinc-700 text-xs font-mono bg-zinc-900/50">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-zinc-800 rounded"
      >
        <span className="text-zinc-500">{open ? '▼' : '▶'}</span>
        <span className="text-amber-400">{name}</span>
        {!done && (
          <span className="ml-auto text-zinc-500 animate-pulse">running…</span>
        )}
        {done && !isError && (
          <span className="ml-auto text-emerald-400">✓ done</span>
        )}
        {done && isError && (
          <span className="ml-auto text-red-400">✗ error</span>
        )}
      </button>

      {open && (
        <div className="border-t border-zinc-700 px-3 py-2 space-y-2">
          <div>
            <div className="text-zinc-500 mb-1">input:</div>
            <pre className="overflow-x-auto text-zinc-300 whitespace-pre-wrap break-words text-xs">
              {JSON.stringify(input, null, 2)}
            </pre>
          </div>
          {done && result && (
            <div>
              <div className="text-zinc-500 mb-1">result:</div>
              <pre
                className={`overflow-x-auto whitespace-pre-wrap break-words text-xs ${
                  isError ? 'text-red-400' : 'text-zinc-300'
                }`}
              >
                {result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
