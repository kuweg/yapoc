import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface MessageBubbleProps {
  role: 'user' | 'assistant'
  content: string
  agentName?: string
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

function AgentLabel({ name }: { name: string }) {
  const colors = AGENT_COLORS[name] ?? DEFAULT_AGENT_COLORS
  const displayName = name.replace(/_/g, ' ')
  return (
    <div className="flex items-center gap-1.5 mb-1 pl-1">
      <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${colors.dot}`} />
      <span className={`text-xs font-semibold uppercase tracking-wide ${colors.label}`}>
        {displayName}
      </span>
    </div>
  )
}

export function MessageBubble({ role, content, agentName }: MessageBubbleProps) {
  if (role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-blue-600 px-4 py-2 text-white text-sm whitespace-pre-wrap">
          {content}
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-start">
      <div className="max-w-[90%]">
        {agentName && <AgentLabel name={agentName} />}
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
