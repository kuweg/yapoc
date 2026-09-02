import { memo, useState, useMemo } from 'react'

interface GroupedCall {
  id: string
  input: Record<string, unknown>
  result?: string
  isError?: boolean
  done: boolean
}

interface GroupedToolCallBlockProps {
  name: string
  calls: GroupedCall[]
}

const TOOL_COLORS: Record<string, { hex: string; rgb: string }> = {
  file_read:    { hex: '#60a5fa', rgb: '96,165,250' },
  file_list:    { hex: '#60a5fa', rgb: '96,165,250' },
  file_write:   { hex: '#4ade80', rgb: '74,222,128' },
  file_edit:    { hex: '#4ade80', rgb: '74,222,128' },
  file_delete:  { hex: '#4ade80', rgb: '74,222,128' },
  spawn_agent:  { hex: '#c084fc', rgb: '192,132,252' },
  wait_for_agent: { hex: '#c084fc', rgb: '192,132,252' },
  web_search:   { hex: '#22d3ee', rgb: '34,211,238' },
  fetch_page:   { hex: '#22d3ee', rgb: '34,211,238' },
  memory_append: { hex: '#fbbf24', rgb: '251,191,36' },
  search_memory: { hex: '#fbbf24', rgb: '251,191,36' },
  shell_exec:   { hex: '#f87171', rgb: '248,113,113' },
}

const DEFAULT_COLOR = { hex: '#a1a1aa', rgb: '161,161,170' }

function getToolColor(name: string) {
  return TOOL_COLORS[name] ?? DEFAULT_COLOR
}

function GroupedToolCallBlockImpl({ name, calls }: GroupedToolCallBlockProps) {
  const [open, setOpen] = useState(false)
  const color = useMemo(() => getToolColor(name), [name])

  const totalCount = calls.length
  const doneCount = calls.filter((c) => c.done).length
  const errorCount = calls.filter((c) => c.done && c.isError).length
  const okCount = doneCount - errorCount
  const allDone = totalCount === doneCount

  return (
    <div className="relative flex items-start gap-2 py-0.5">
      {/* Left column: small pulsing dot */}
      <div className="relative flex items-center justify-center pt-1" style={{ width: 20, height: 20 }}>
        <div
          className={`rounded-full ${
            !allDone ? 'animate-dot-pulse' : ''
          }`}
          style={{
            width: 8,
            height: 8,
            backgroundColor: color.hex,
            '--dot-color-rgb': color.rgb,
          } as React.CSSProperties}
        />
      </div>

      {/* Right column: grouped label + expandable list */}
      <div className="flex-1 min-w-0">
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center gap-1.5 px-1 py-0.5 text-left rounded hover:bg-zinc-800/50 transition-colors group"
        >
          {/* tool name + count badge */}
          <span className="text-xs font-mono font-medium" style={{ color: color.hex }}>
            {name}
          </span>
          <span className="text-[13px] text-zinc-500 font-mono">(×{totalCount})</span>

          {/* expand indicator */}
          <span
            className="text-zinc-600 text-[12px] transition-transform duration-150"
            style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)' }}
          >
            ▸
          </span>

          {/* aggregate status */}
          <span className="ml-auto text-[13px] font-mono">
            {allDone ? (
              errorCount > 0 ? (
                <span>
                  <span className="text-emerald-400">{okCount}/{totalCount} ✓</span>
                  {errorCount > 0 && (
                    <span className="text-red-400 ml-1">{errorCount}/{totalCount} ✗</span>
                  )}
                </span>
              ) : (
                <span className="text-emerald-400">{doneCount}/{totalCount} ✓</span>
              )
            ) : (
              <span className="text-zinc-500">{doneCount}/{totalCount} …</span>
            )}
          </span>
        </button>

        {/* Expandable: compact list of each call */}
        {open && (
          <div className="border-l border-zinc-700 ml-1 pl-3 py-1 space-y-2">
            {calls.map((call, i) => (
              <div key={call.id} className="space-y-0.5">
                <div className="flex items-center gap-1.5">
                  <span className="text-[12px] text-zinc-500 font-mono w-5 flex-shrink-0">[{i + 1}]</span>
                  <span className="text-[12px] text-zinc-500 uppercase tracking-wide">input</span>
                  {call.done && (
                    <span className="ml-auto text-[12px] font-mono">
                      {call.isError ? (
                        <span className="text-red-400">✗</span>
                      ) : (
                        <span className="text-emerald-400">✓</span>
                      )}
                    </span>
                  )}
                  {!call.done && (
                    <span className="ml-auto text-[12px] text-zinc-500">…</span>
                  )}
                </div>
                <pre className="overflow-x-auto text-zinc-300 whitespace-pre-wrap break-words text-[13px] leading-relaxed ml-6">
                  {JSON.stringify(call.input, null, 2)}
                </pre>
                {call.done && call.result && (
                  <>
                    <div className="flex items-center gap-1.5 ml-6 mt-1">
                      <span className="text-[12px] text-zinc-500 uppercase tracking-wide">result</span>
                    </div>
                    <pre
                      className={`overflow-x-auto whitespace-pre-wrap break-words text-[13px] leading-relaxed ml-6 ${
                        call.isError ? 'text-red-400' : 'text-zinc-300'
                      }`}
                    >
                      {call.result}
                    </pre>
                  </>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export const GroupedToolCallBlock = memo(GroupedToolCallBlockImpl)
