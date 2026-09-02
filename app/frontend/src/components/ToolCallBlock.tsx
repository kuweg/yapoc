import { memo, useState, useMemo } from 'react'

interface ToolCallBlockProps {
  id: string
  name: string
  input: Record<string, unknown>
  result?: string
  isError?: boolean
  done: boolean
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

/* ---------- Dot ---------- */
function Dot({
  color,
  done,
  isError,
}: {
  color: { hex: string; rgb: string }
  done: boolean
  isError: boolean
}) {
  const isRunning = !done
  const isComplete = done && !isError
  const isFailed = done && isError

  return (
    <div className="relative flex items-center justify-center" style={{ width: 20, height: 20 }}>
      {/* glow ring */}
      <div
        className={`absolute inset-0 rounded-full ${
          isRunning ? 'animate-dot-pulse' : ''
        }`}
        style={{
          '--dot-color-rgb': color.rgb,
          animationName: isRunning ? 'dot-pulse' : undefined,
          animationDuration: '1.5s',
          animationIterationCount: 'infinite',
        } as React.CSSProperties}
      />
      {/* dot */}
      <div
        className={`rounded-full z-10 ${
          isComplete ? 'animate-dot-complete' : ''
        }`}
        style={{
          width: 12,
          height: 12,
          backgroundColor: isFailed ? '#f87171' : color.hex,
          transition: 'background-color 0.3s',
        }}
      />
    </div>
  )
}

/* ---------- Main Component ---------- */
function ToolCallBlockImpl({ id: _id, name, input, result, isError, done }: ToolCallBlockProps) {
  const [open, setOpen] = useState(false)
  const color = useMemo(() => getToolColor(name), [name])
  const isRunning = !done

  return (
    <>
      <style>{`
        @keyframes dot-pulse {
          0%, 100% { box-shadow: 0 0 0 0 rgba(var(--dot-color-rgb), 0.7); }
          50% { box-shadow: 0 0 8px 4px rgba(var(--dot-color-rgb), 0.2); }
        }
        @keyframes dot-complete {
          0% { box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.7); }
          50% { box-shadow: 0 0 6px 3px rgba(74, 222, 128, 0.3); }
          100% { box-shadow: 0 0 0 0 rgba(74, 222, 128, 0); }
        }
        @keyframes line-running {
          0% { background-position: 0 0; }
          100% { background-position: 20px 0; }
        }
        @keyframes line-complete {
          0% { background: #52525b; }
          30% { background: #4ade80; }
          70% { background: #4ade80; }
          100% { background: #52525b; opacity: 0.5; }
        }
        @keyframes slide-down {
          from { max-height: 0; opacity: 0; }
          to { max-height: 500px; opacity: 1; }
        }
        .animate-slide-down {
          animation: slide-down 0.25s ease-out forwards;
          overflow: hidden;
        }
      `}</style>

      <div className="relative flex items-start gap-2 py-0.5">
        {/* ---------- Left column: line + dot ---------- */}
        <div className="relative flex flex-col items-center" style={{ width: 20, minHeight: 36 }}>
          <Dot color={color} done={done} isError={isError ?? false} />
        </div>

        {/* ---------- Right column: label + details ---------- */}
        <div className="flex-1 min-w-0">
          <button
            onClick={() => setOpen((o) => !o)}
            className="flex w-full items-center gap-1.5 px-1 py-1 text-left rounded hover:bg-zinc-800 transition-colors group"
          >
            {/* label */}
            <span className="text-xs font-mono font-medium truncate max-w-[180px]" style={{ color: color.hex }}>
              {name}
            </span>

            {/* expand indicator */}
            <span className="text-zinc-600 text-[12px] transition-transform duration-150" style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)' }}>
              ▸
            </span>

            {/* status badge */}
            <span className="ml-auto text-xs font-mono">
              {isRunning && (
                <span className="text-zinc-500 animate-[dot-pulse_1.5s_ease-in-out_infinite]" style={{ '--dot-color-rgb': '161,161,170' } as React.CSSProperties}>
                  running…
                </span>
              )}
              {done && !isError && (
                <span className="text-emerald-400">✓</span>
              )}
              {done && isError && (
                <span className="text-red-400">✗</span>
              )}
            </span>
          </button>

          {/* ---------- Expandable details ---------- */}
          {open && (
            <div className="animate-slide-down border-l border-zinc-700 ml-1 pl-3 py-1 space-y-1.5">
              <div>
                <div className="text-[12px] text-zinc-500 uppercase tracking-wide mb-0.5">input</div>
                <pre className="overflow-x-auto text-zinc-300 whitespace-pre-wrap break-words text-[13px] leading-relaxed">
                  {JSON.stringify(input, null, 2)}
                </pre>
              </div>
              {done && result && (
                <div>
                  <div className="text-[12px] text-zinc-500 uppercase tracking-wide mb-0.5">result</div>
                  <pre
                    className={`overflow-x-auto whitespace-pre-wrap break-words text-[13px] leading-relaxed ${
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
      </div>
    </>
  )
}

// Memoize: input is a fresh object each delta but stable once tool completes;
// memo with default shallow equality avoids re-rendering finished tool calls
// on every parent re-render.
export const ToolCallBlock = memo(ToolCallBlockImpl)
