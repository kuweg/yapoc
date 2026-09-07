import { memo, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ThinkingBlock } from './ThinkingBlock'
import { ToolCallBlock } from './ToolCallBlock'
import { GroupedToolCallBlock } from './GroupedToolCallBlock'
import { groupParts, type GroupedPart } from './groupParts'
import ChartBlock from './ChartBlock'
import MermaidBlock from './MermaidBlock'
import { StreamingText } from './StreamingText'
import { AgentAvatar, getAgentColor, getAgentDisplayName } from '../lib/agentIdentity'
import { CompactionMarker } from './ContextGauge'
import { useFileViewerStore } from '../store/fileViewerStore'
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
const ATTACH_PDF_RE = /\.pdf$/i
const FILE_PATH_RE = /^(?:data\/(?:generated|telegram_media)\/|app\/projects\/)[^\n?#]+$/i

function isProjectFilePath(value: string): boolean {
  return FILE_PATH_RE.test(value.trim())
}

type TextAttachmentKind = 'spreadsheet' | 'presentation' | 'email' | 'calendar' | 'archive'

const TEXT_ATTACHMENT_TYPES: Array<{
  kind: TextAttachmentKind
  extensions: RegExp
  mimes: string[]
  icon: string
  label: string
  previewNote: string
}> = [
  {
    kind: 'spreadsheet',
    extensions: /\.xlsx$/i,
    mimes: ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'],
    icon: '📊',
    label: 'Spreadsheet',
    previewNote: 'View opens the spreadsheet in a new browser tab.',
  },
  {
    kind: 'presentation',
    extensions: /\.pptx$/i,
    mimes: ['application/vnd.openxmlformats-officedocument.presentationml.presentation'],
    icon: '📽️',
    label: 'Presentation',
    previewNote: 'View opens the presentation in an in-chat slide viewer.',
  },
  {
    kind: 'email',
    extensions: /\.(eml|mbox)$/i,
    mimes: ['message/rfc822'],
    icon: '✉️',
    label: 'Email message',
    previewNote: 'View opens the email file in a new browser tab.',
  },
  {
    kind: 'calendar',
    extensions: /\.ics$/i,
    mimes: ['text/calendar'],
    icon: '🗓️',
    label: 'Calendar file',
    previewNote: 'View opens the calendar file in a new browser tab.',
  },
  {
    kind: 'archive',
    extensions: /\.(zip|tar|tar\.gz|tgz|7z)$/i,
    mimes: ['application/zip', 'application/x-zip-compressed', 'application/x-tar', 'application/gzip', 'application/x-7z-compressed'],
    icon: '🗜️',
    label: 'Archive',
    previewNote: 'View opens the archive in a new browser tab; archive contents are not extracted in chat.',
  },
]

function attachIsImage(a: Attachment): boolean {
  return (a.mime || '').startsWith('image/') || ATTACH_IMG_RE.test(a.name || '')
}

function attachIsPdf(a: Attachment): boolean {
  return (a.mime || '').toLowerCase() === 'application/pdf' || ATTACH_PDF_RE.test(a.name || '')
}

function getTextAttachmentType(a: Attachment) {
  const mime = (a.mime || '').toLowerCase()
  return TEXT_ATTACHMENT_TYPES.find(({ extensions, mimes }) => extensions.test(a.name || '') || mimes.includes(mime))
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function InlineViewerModal({ href, name, onClose }: { href: string; name: string; onClose: () => void }) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = previousOverflow }
  }, [])

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/80 p-2 sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-label={`Viewer: ${name}`}
      onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}
    >
      <div className="flex h-[92dvh] w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-zinc-700 bg-zinc-900 shadow-2xl">
        <div className="flex items-center gap-3 border-b border-zinc-700 px-3 py-2 text-zinc-100">
          <span className="min-w-0 flex-1 truncate text-sm font-medium">{name}</span>
          <a href={href} download={name || true} className="rounded-md px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-700">Download</a>
          <button type="button" onClick={onClose} className="rounded-md px-3 py-1.5 text-sm font-medium text-zinc-100 hover:bg-zinc-700 focus:outline-none focus:ring-2 focus:ring-blue-400" aria-label="Close viewer">Close</button>
        </div>
        <iframe src={href} title={`Viewer: ${name}`} className="min-h-0 flex-1 bg-white" />
      </div>
    </div>,
    document.body,
  )
}

function PptxPathView({ path }: { path: string }) {
  const [open, setOpen] = useState(false)
  const name = path.split('/').pop() || path
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 rounded-md bg-zinc-700 px-2 py-0.5 text-xs font-medium text-zinc-100 hover:bg-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-400 align-middle"
        title={`View ${name}`}
      >
        📽️ View presentation
      </button>
      {open && (
        <InlineViewerModal
          href={`/api/pptx/view?path=${encodeURIComponent(path)}`}
          name={name}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  )
}

/** Render attachment cards for a user message (image thumbnails + file chips). */
function AttachCards({ attachments }: { attachments: Attachment[] }) {
  const [viewer, setViewer] = useState<{ href: string; name: string } | null>(null)
  return (
    <>
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
        const inlineHref = a.id ? `/api/upload/${a.id}?inline=1` : undefined
        if (attachIsPdf(a)) {
          return (
            <div
              key={a.id ?? i}
              className="w-full max-w-[min(100%,22rem)] rounded-xl border border-red-900/70 bg-zinc-800 p-3 text-xs text-zinc-200 shadow-sm"
              title={a.name}
            >
              <div className="flex min-w-0 items-center gap-2">
                <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-red-950/60 text-base" aria-hidden="true">📕</span>
                <div className="min-w-0 flex-1">
                  <div className="truncate font-mono text-zinc-100">{a.name}</div>
                  <div className="mt-0.5 text-zinc-500">PDF document{a.size ? ` · ${formatFileSize(a.size)}` : ''}</div>
                </div>
              </div>
              {href && (
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setViewer({ href: inlineHref!, name: a.name || 'PDF document' })}
                    className="rounded-lg bg-zinc-700 px-3 py-1.5 font-medium text-zinc-100 hover:bg-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-400"
                    title="Open PDF in chat"
                  >
                    View
                  </button>
                  <a
                    href={href}
                    download={a.name || true}
                    className="rounded-lg border border-zinc-600 px-3 py-1.5 font-medium text-zinc-200 hover:bg-zinc-700"
                    title="Download PDF"
                  >
                    Download
                  </a>
                </div>
              )}
              <p className="mt-2 text-[11px] leading-snug text-zinc-500">View opens the browser&apos;s PDF viewer inside chat.</p>
            </div>
          )
        }
        const textAttachment = getTextAttachmentType(a)
        if (textAttachment) {
          return (
            <div
              key={a.id ?? i}
              className="w-full max-w-[min(100%,22rem)] rounded-xl border border-blue-900/70 bg-zinc-800 p-3 text-xs text-zinc-200 shadow-sm"
              title={a.name}
            >
              <div className="flex min-w-0 items-center gap-2">
                <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-blue-950/60 text-base" aria-hidden="true">{textAttachment.icon}</span>
                <div className="min-w-0 flex-1">
                  <div className="truncate font-mono text-zinc-100">{a.name}</div>
                  <div className="mt-0.5 text-zinc-500">{textAttachment.label}{a.size ? ` · ${formatFileSize(a.size)}` : ''}</div>
                </div>
              </div>
              {href && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {textAttachment.kind === 'presentation' ? (
                    <button
                      type="button"
                      onClick={() => setViewer({ href: `/api/pptx/view?upload_id=${a.id}`, name: a.name || 'Presentation' })}
                      className="rounded-lg bg-zinc-700 px-3 py-1.5 font-medium text-zinc-100 hover:bg-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-400"
                      title="Open presentation in chat"
                    >
                      View
                    </button>
                  ) : (
                    <a
                      href={inlineHref}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="rounded-lg bg-zinc-700 px-3 py-1.5 font-medium text-zinc-100 hover:bg-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-400"
                      title={`Open ${textAttachment.label.toLowerCase()}`}
                    >
                      View
                    </a>
                  )}
                  <a
                    href={href}
                    download={a.name || true}
                    className="rounded-lg border border-zinc-600 px-3 py-1.5 font-medium text-zinc-200 hover:bg-zinc-700"
                    title={`Download ${textAttachment.label.toLowerCase()}`}
                  >
                    Download
                  </a>
                </div>
              )}
              <p className="mt-2 text-[11px] leading-snug text-zinc-500">{textAttachment.previewNote}</p>
            </div>
          )
        }
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
    {viewer && <InlineViewerModal href={viewer.href} name={viewer.name} onClose={() => setViewer(null)} />}
    </>
  )
}

/**
 * Extract the raw source text out of a react-markdown code element's children.
 * react-markdown hands us the fenced-block content as a single text child (or
 * an array of strings when the block is split across nodes). We join them so a
 * multi-line Mermaid definition survives intact.
 */
function codeChildrenToText(children: React.ReactNode): string {
  const parts: string[] = []
  const walk = (node: React.ReactNode) => {
    if (node == null) return
    if (typeof node === 'string' || typeof node === 'number') {
      parts.push(String(node))
    } else if (Array.isArray(node)) {
      node.forEach(walk)
    } else if (typeof node === 'object' && 'props' in (node as object)) {
      walk((node as { props: { children?: React.ReactNode } }).props?.children)
    }
  }
  walk(children)
  return parts.join('')
}

const MARKDOWN_COMPONENTS = {
  p: ({ children }: { children?: React.ReactNode }) => <p className="mb-2 last:mb-0">{children}</p>,
  pre: ({ children }: { children?: React.ReactNode }) => {
    // A fenced ```mermaid block arrives as <pre><code class="language-mermaid">.
    // Detect it here (the <pre> wrapper owns the block) and mount a real
    // rendered diagram instead of dumping the raw source as unsupported code.
    const codeEl = Array.isArray(children) ? children[0] : children
    const className =
      codeEl && typeof codeEl === 'object' && 'props' in (codeEl as object)
        ? (codeEl as { props?: { className?: string } }).props?.className
        : undefined
    if (typeof className === 'string' && /\blanguage-mermaid\b/.test(className)) {
      const source = codeChildrenToText(
        (codeEl as { props?: { children?: React.ReactNode } }).props?.children,
      ).trim()
      if (source) {
        return <MermaidBlock source={source} />
      }
    }
    return <pre className="bg-zinc-900 rounded p-3 overflow-x-auto my-2 text-xs">{children}</pre>
  },
  code: ({ children, className }: { children?: React.ReactNode; className?: string }) => {
    const text = codeChildrenToText(children).trim()
    if (!className && /\.pptx$/i.test(text) && !/\s/.test(text) && (text.startsWith('data/generated/') || text.startsWith('data/') || text.includes('/'))) {
      return <PptxPathView path={text} />
    }
    if (!className && isProjectFilePath(text)) {
      const selectFile = useFileViewerStore.getState().selectFile
      return <button type="button" onClick={() => selectFile({ path: text, name: text.split('/').pop() })} className="rounded bg-zinc-700 px-1 py-0.5 text-xs font-mono text-blue-300 underline hover:bg-zinc-600">{children}</button>
    }
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
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => {
    const selectFile = useFileViewerStore.getState().selectFile
    const rawPath = href?.replace(/^\/?(?:api\/)?files\/(?:download|preview)\?path=/, '')
    const decodedPath = rawPath ? decodeURIComponent(rawPath.split('&')[0]) : ''
    const childText = codeChildrenToText(children).trim()
    const path = isProjectFilePath(decodedPath) ? decodedPath : isProjectFilePath(childText) ? childText : ''
    if (path) {
      return <button type="button" onClick={() => selectFile({ path, name: path.split('/').pop() })} className="text-left text-blue-400 underline hover:text-blue-300">{children}</button>
    }
    return <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-400 underline">{children}</a>
  },
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
        {model && <span className="text-[12px] font-normal text-zinc-500 lowercase ml-1.5">[{model}]</span>}
      </span>
    </div>
  )
}

function MessageBubbleImpl({ role, content, parts, agentName, agentModel, onDelete, attachments, streaming }: MessageBubbleProps) {
  useFileViewerStore((s) => s.selectFile)

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
    if (part.kind === 'chart') {
      return <ChartBlock key={`chart-${i}`} option={part.option} />
    }
    if (part.kind === 'mermaid') {
      return <MermaidBlock key={`mermaid-${i}`} source={part.source} />
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
