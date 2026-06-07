import { memo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ThinkingBlock } from './ThinkingBlock'
import { ToolCallBlock } from './ToolCallBlock'
import { GroupedToolCallBlock } from './GroupedToolCallBlock'
import { groupParts, type GroupedPart } from './groupParts'
import { StreamingText } from './StreamingText'
import { AgentAvatar, getAgentColor, getAgentDisplayName } from '../lib/agentIdentity'
import { CompactionMarker } from './ContextGauge'
import type { TaskPart, Attachment } from '../api/types'

interface MessageBubbleProps {
  role: 'user' | 'assistant'
  content: string
  parts?: TaskPart[]
  agentName?: string
  agentModel?: string
  onDelete?: () => void
  attachments?: Attachment[]
  // When true the AI text is rendered through StreamingText (per-token fade)
  // instead of markdown — used only for the in-flight streaming bubble.
  streaming?: boolean
}

const ATTACH_IMG_RE = /\.(png|jpe?g|gif|webp|svg|bmp)$/i
function attachIsImage(a: Attachment): boolean {
  return (a.mime || '').startsWith('image/') || ATTACH_IMG_RE.test(a.name || '')
}

/** Render attachment cards for a user message (image thumbnails + file chips). */
function AttachCards({ attachments }: { attachments: Attachment[] }) {
  return (
    <div className="flex flex-wrap gap-1.5 mb-1.5 justify-end">
      {attachments.map((a, i) => {
        const src = a.previewUrl || (a.id ? `/api/upload/${a.id}?thumb=1` : undefined)
        if (attachIsImage(a) && src) {
          const full = a.id ? `/api/upload/${a.id}` : a.previewUrl
          return (
            <a key={a.id ?? i} href={full} target="_blank" rel="noopener noreferrer" className="block">
              <img
                src={src}
                alt={a.name}
                loading="lazy"
                className="max-h-32 max-w-[180px] rounded-lg border border-zinc-700 object-cover hover:opacity-90 transition-opacity"
              />
            </a>
          )
        }
        const href = a.id ? `/api/upload/${a.id}` : undefined
        return (
          <a
            key={a.id ?? i}
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-lg bg-zinc-800 border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-700 font-mono"
            title={a.name}
          >
            📄 <span className="truncate max-w-[140px]">{a.name}</span>
          </a>
        )
      })}
    </div>
  )
}

const MARKDOWN_COMPONENTS = {
  p: ({ children }: { children?: React.ReactNode }) => <p className="mb-2 last:mb-0">{children}</p>,
  pre: ({ children }: { children?: React.ReactNode }) => (
    <pre className="bg-zinc-900 rounded p-3 overflow-x-auto my-2 text-xs">{children}</pre>
  ),
  code: ({ children, className }: { children?: React.ReactNode; className?: string }) => {
    if (className) {
      return <code className={`font-mono ${className}`}>{children}</code>
    }
    return (
      <code className="bg-zinc-700 rounded px-1 py-0.5 text-xs font-mono text-zinc-200">
        {children}
      </code>
    )
  },
  ul: ({ children }: { children?: React.ReactNode }) => <ul className="list-disc ml-4 mb-2 space-y-0.5">{children}</ul>,
  ol: ({ children }: { children?: React.ReactNode }) => <ol className="list-decimal ml-4 mb-2 space-y-0.5">{children}</ol>,
  li: ({ children }: { children?: React.ReactNode }) => <li>{children}</li>,
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-400 underline"
    >
      {children}
    </a>
  ),
  h1: ({ children }: { children?: React.ReactNode }) => <h1 className="text-lg font-bold mb-2 mt-3">{children}</h1>,
  h2: ({ children }: { children?: React.ReactNode }) => <h2 className="text-base font-bold mb-1.5 mt-2">{children}</h2>,
  h3: ({ children }: { children?: React.ReactNode }) => <h3 className="font-semibold mb-1 mt-2">{children}</h3>,
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote className="border-l-2 border-zinc-600 pl-3 my-2 text-zinc-400 italic">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="border-zinc-700 my-3" />,
}

function AgentLabel({ name, model }: { name: string; model?: string }) {
  const color = getAgentColor(name)
  return (
    <div className="flex items-center gap-1.5 mb-1 pl-1">
      <AgentAvatar name={name} size={16} />
      <span className="text-xs font-semibold uppercase tracking-wide" style={{ color }}>
        {getAgentDisplayName(name)}
        {model && <span className="text-[10px] font-normal text-zinc-500 lowercase ml-1.5">[{model}]</span>}
      </span>
    </div>
  )
}

function MessageBubbleImpl({ role, content, parts, agentName, agentModel, onDelete, attachments, streaming }: MessageBubbleProps) {
  if (role === 'user') {
    // Legacy single-image marker (older messages); new attachments come via the
    // `attachments` prop and render as cards above the bubble.
    const photoMatch = content.match(/\[📎 photo attached: ([^\]]+)\]/)
    const photoPath = photoMatch?.[1] ?? null
    let displayContent = photoPath ? content.replace(photoMatch![0], '').trim() : content
    displayContent = displayContent.replace(/!\[image\]\(blob:[^)]+\)/g, '').trim()

    return (
      <div className="msg flex flex-col items-end gap-0.5 group">
        {attachments && attachments.length > 0 && <AttachCards attachments={attachments} />}
        {(displayContent || photoPath) && (
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
        )}
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

  // Helper to render a single grouped part
  function renderPart(part: GroupedPart, i: number) {
    if (part.kind === 'tool_group') {
      return <GroupedToolCallBlock key={`grp-${part.name}-${i}`} name={part.name} calls={part.calls} />
    }
    if (part.kind === 'text') {
      return (
        <MessageBubbleImpl
          key={`p-t-${i}`}
          role="assistant"
          content={part.text}
          agentName={agentName}
          agentModel={agentModel}
        />
      )
    }
    if (part.kind === 'thinking') {
      return <ThinkingBlock key={part.id} text={part.text} done={part.done} />
    }
    if (part.kind === 'compact') {
      return <CompactionMarker key={part.id} tokensBefore={part.tokensBefore} tokensAfter={part.tokensAfter} reason={part.reason} />
    }
    return (
      <ToolCallBlock
        key={part.id}
        id={part.id}
        name={part.name}
        input={part.input}
        result={part.result}
        isError={part.isError}
        done={part.done}
      />
    )
  }

  // If the message has structured parts, render them as the execution trace
  // (tool calls, thinking blocks, text) followed by the final text summary.
  if (parts && parts.length > 0) {
    const grouped = groupParts(parts)
    return (
      <div className="msg msg-ai flex justify-start">
        <div className="max-w-[90%] space-y-1">
          {agentName && <AgentLabel name={agentName} model={agentModel} />}
          <div className="rounded-2xl rounded-tl-sm bg-zinc-800/70 px-3 py-2">
            {grouped.map((part, i) => renderPart(part, i))}
            {content && (
              <div className="pt-2 border-t border-zinc-700/30 mt-2">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={MARKDOWN_COMPONENTS}
                >
                  {content}
                </ReactMarkdown>
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="msg msg-ai flex justify-start">
      <div className="max-w-[90%]">
        {agentName && <AgentLabel name={agentName} model={agentModel} />}
        <div className="rounded-2xl rounded-tl-sm bg-zinc-800 px-4 py-2 text-zinc-100 text-sm">
          {streaming ? (
            <StreamingText text={content} />
          ) : (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={MARKDOWN_COMPONENTS}
            >
              {content}
            </ReactMarkdown>
          )}
        </div>
      </div>
    </div>
  )
}

// Memoize so re-renders of the parent (e.g. keystrokes, streaming) don't
// re-parse markdown for every prior message. Default shallow equality on
// role/content/agentName is correct — finished messages are immutable.
export const MessageBubble = memo(MessageBubbleImpl)
