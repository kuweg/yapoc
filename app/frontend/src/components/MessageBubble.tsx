import { memo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface MessageBubbleProps {
  role: 'user' | 'assistant'
  content: string
  agentName?: string
  agentModel?: string
  onDelete?: () => void
}

// Per-agent accent colors (Tailwind classes)
const AGENT_COLORS: Record<string, { label: string; dot: string }> = {
  master:        { label: 'text-purple-400',  dot: 'bg-purple-400' },
  planning:      { label: 'text-blue-400',    dot: 'bg-blue-400' },
  builder:       { label: 'text-green-400',   dot: 'bg-green-400' },
  keeper:        { label: 'text-yellow-400',  dot: 'bg-yellow-400' },
  cron:          { label: 'text-orange-400',  dot: 'bg-orange-400' },
  doctor:        { label: 'text-red-400',     dot: 'bg-red-400' },
  model_manager: { label: 'text-cyan-400',    dot: 'bg-cyan-400' },
}

const DEFAULT_AGENT_COLORS = { label: 'text-zinc-400', dot: 'bg-zinc-400' }

function AgentLabel({ name, model }: { name: string; model?: string }) {
  const colors = AGENT_COLORS[name] ?? DEFAULT_AGENT_COLORS
  const displayName = name.replace(/_/g, ' ')
  return (
    <div className="flex items-center gap-1.5 mb-1 pl-1">
      <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${colors.dot}`} />
      <span className={`text-xs font-semibold uppercase tracking-wide ${colors.label}`}>
        {displayName}
        {model && <span className="text-[10px] font-normal text-zinc-500 lowercase ml-1.5">[{model}]</span>}
      </span>
    </div>
  )
}

function MessageBubbleImpl({ role, content, agentName, agentModel, onDelete }: MessageBubbleProps) {
  if (role === 'user') {
    // Check for photo attachment marker
    const photoMatch = content.match(/\[📎 photo attached: ([^\]]+)\]/)
    const photoPath = photoMatch?.[1] ?? null
    // Strip the attachment marker and any stale blob-URL markdown (![image](blob:...))
    let displayContent = photoPath ? content.replace(photoMatch![0], '').trim() : content
    displayContent = displayContent.replace(/!\[image\]\(blob:[^)]+\)/g, '').trim()

    return (
      <div className="flex flex-col items-end gap-0.5 group">
        <div
          className="max-w-[80%] rounded-2xl rounded-tr-sm px-4 py-2 text-sm whitespace-pre-wrap"
          style={{
            backgroundColor: 'var(--color-bg-raised)',
            color: 'var(--color-text-primary)',
            border: '1px solid var(--color-border)',
          }}
        >
          {photoPath && (
            <div className="mb-2">
              <img
                src={`/api/files/image?path=${encodeURIComponent(photoPath)}`}
                alt="attached"
                className="max-w-[300px] rounded-lg"
              />
            </div>
          )}
          {displayContent}
        </div>
        {onDelete && (
          <div className="flex items-center justify-end gap-1 mr-1 mt-0.5 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
            <button
              onClick={onDelete}
              className="p-0.5 rounded text-red-400/60 hover:text-red-400 hover:bg-red-400/10 transition-colors"
              title="Delete message"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="flex justify-start">
      <div className="max-w-[90%]">
        {agentName && <AgentLabel name={agentName} model={agentModel} />}
        <div className="rounded-2xl rounded-tl-sm bg-zinc-800 px-4 py-2 text-zinc-100 text-sm">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
              pre: ({ children }) => (
                <pre className="bg-zinc-900 rounded p-3 overflow-x-auto my-2 text-xs">{children}</pre>
              ),
              code: ({ children, className }) => {
                if (className) {
                  return <code className={`font-mono ${className}`}>{children}</code>
                }
                return (
                  <code className="bg-zinc-700 rounded px-1 py-0.5 text-xs font-mono text-zinc-200">
                    {children}
                  </code>
                )
              },
              ul: ({ children }) => <ul className="list-disc ml-4 mb-2 space-y-0.5">{children}</ul>,
              ol: ({ children }) => <ol className="list-decimal ml-4 mb-2 space-y-0.5">{children}</ol>,
              li: ({ children }) => <li>{children}</li>,
              a: ({ href, children }) => (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-400 underline"
                >
                  {children}
                </a>
              ),
              h1: ({ children }) => <h1 className="text-lg font-bold mb-2 mt-3">{children}</h1>,
              h2: ({ children }) => <h2 className="text-base font-bold mb-1.5 mt-2">{children}</h2>,
              h3: ({ children }) => <h3 className="font-semibold mb-1 mt-2">{children}</h3>,
              blockquote: ({ children }) => (
                <blockquote className="border-l-2 border-zinc-600 pl-3 my-2 text-zinc-400 italic">
                  {children}
                </blockquote>
              ),
              hr: () => <hr className="border-zinc-700 my-3" />,
            }}
          >
            {content}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  )
}

// Memoize so re-renders of the parent (e.g. keystrokes, streaming) don't
// re-parse markdown for every prior message. Default shallow equality on
// role/content/agentName is correct — finished messages are immutable.
export const MessageBubble = memo(MessageBubbleImpl)
