import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import hljs from 'highlight.js'
import type { VaultFile } from '../types'

// ── Code block with highlight.js ───────────────────────────────────────────

function CodeBlock({ code, lang }: { code: string; lang: string }) {
  const ref = useRef<HTMLElement>(null)

  useEffect(() => {
    if (!ref.current) return
    // Reset highlight.js state on content change
    delete (ref.current.dataset as Record<string, unknown>).highlighted
    ref.current.className = `language-${lang}`
    ref.current.textContent = code
    if (lang !== 'plaintext' && lang !== 'text') {
      try {
        hljs.highlightElement(ref.current)
      } catch {
        // Unsupported language — leave as plain text
      }
    }
  }, [code, lang])

  return (
    <pre className="vault-code-pre">
      <code ref={ref} className={`language-${lang} hljs`} />
    </pre>
  )
}

// ── File info bar ───────────────────────────────────────────────────────────

function InfoBar({ file, onCopy, copied }: {
  file: VaultFile
  onCopy: () => void
  copied: boolean
}) {
  const parts = file.path.split('/')
  const name = parts[parts.length - 1] ?? file.path
  const dir = parts.slice(0, -1).join('/') || '.'
  const sizeStr = file.size < 1024 ? `${file.size}B`
    : file.size < 1024 * 1024 ? `${(file.size / 1024).toFixed(1)} KB`
    : `${(file.size / 1024 / 1024).toFixed(2)} MB`

  const meta = file.type === 'text'
    ? `${file.lang} · ${sizeStr}`
    : `${file.type} · ${sizeStr}`

  return (
    <div className="flex items-center gap-3 px-4 py-2 border-b border-zinc-800 bg-zinc-900 flex-shrink-0 min-w-0">
      <span className="text-zinc-500 text-xs flex-shrink-0">{dir}/</span>
      <span className="text-[#FFB633] text-xs font-medium truncate">{name}</span>
      <span className="text-zinc-500 text-xs flex-shrink-0">{meta}</span>
      {'truncated' in file && file.truncated && (
        <span className="text-yellow-500 text-xs flex-shrink-0">⚠ truncated</span>
      )}
      <div className="flex-1" />
      {file.type === 'text' && (
        <button
          onClick={onCopy}
          className="text-zinc-500 hover:text-zinc-300 text-xs transition-colors flex-shrink-0"
        >
          {copied ? '✓ copied' : 'copy'}
        </button>
      )}
    </div>
  )
}

// ── View mode slider (segmented control) ───────────────────────────────────

type ViewMode = 'edit' | 'split' | 'preview'

const VIEW_MODES: { value: ViewMode; label: string }[] = [
  { value: 'edit',    label: 'EDIT' },
  { value: 'split',   label: 'SPLIT' },
  { value: 'preview', label: 'PREVIEW' },
]

function ViewModeSlider({ mode, onChange }: { mode: ViewMode; onChange: (m: ViewMode) => void }) {
  return (
    <div className="vault-view-slider">
      {VIEW_MODES.map(({ value, label }) => (
        <button
          key={value}
          onClick={() => onChange(value)}
          className={`vault-view-slider__btn${mode === value ? ' vault-view-slider__btn--active' : ''}`}
        >
          {mode === value ? `[${label}]` : label}
        </button>
      ))}
    </div>
  )
}

// ── Markdown preview panel ──────────────────────────────────────────────────

function MarkdownPreview({ content }: { content: string }) {
  return (
    <div className="vault-md-preview">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {content}
      </ReactMarkdown>
    </div>
  )
}

// ── Main viewer ─────────────────────────────────────────────────────────────

interface Props {
  file: VaultFile | null
  loading: boolean
  error: string | null
}

export function VaultFileViewer({ file, loading, error }: Props) {
  const [copied, setCopied] = useState(false)
  const [viewMode, setViewMode] = useState<ViewMode>('split')
  const [editContent, setEditContent] = useState<string>('')

  // Detect if current file is markdown
  const isMarkdown = file?.type === 'text' && file?.lang === 'markdown'

  // Sync editContent when file changes
  const fileContent = file?.type === 'text' ? file.content : undefined
  useEffect(() => {
    if (file?.type === 'text') {
      setEditContent(file.content)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file?.path, fileContent])

  // Reset copied + viewMode when file changes
  useEffect(() => {
    setCopied(false)
    // Reset to split when switching to a markdown file, edit for others
    if (file) {
      const ext = file.path.split('.').pop()?.toLowerCase() ?? ''
      const isMd = ['md', 'mdx'].includes(ext)
      setViewMode(isMd ? 'split' : 'edit')
    }
  }, [file?.path])

  function handleCopy() {
    if (!file || file.type !== 'text') return
    // For markdown files, copy the (possibly edited) content; for others, copy original
    const textToCopy = isMarkdown ? editContent : file.content
    navigator.clipboard.writeText(textToCopy).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-zinc-400 text-sm animate-pulse">
        loading…
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <span className="text-red-400 text-sm">{error}</span>
      </div>
    )
  }

  if (!file) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-zinc-500 text-sm select-none">
        <span className="text-4xl">◈</span>
        <span>select a file from the tree</span>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden min-h-0">
      <InfoBar file={file} onCopy={handleCopy} copied={copied} />

      {/* View mode slider — only for markdown files */}
      {isMarkdown && (
        <div className="vault-view-slider-bar">
          <ViewModeSlider mode={viewMode} onChange={setViewMode} />
        </div>
      )}

      <div className="flex-1 overflow-hidden min-h-0 flex">
        {/* ── Markdown file rendering ── */}
        {isMarkdown && (
          <>
            {/* Edit pane */}
            {(viewMode === 'edit' || viewMode === 'split') && (
              <div className={`vault-editor-pane${viewMode === 'split' ? ' vault-editor-pane--split' : ' vault-editor-pane--full'}`}>
                <textarea
                  className="vault-editor-textarea"
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  spellCheck={false}
                  autoComplete="off"
                  autoCorrect="off"
                  autoCapitalize="off"
                />
              </div>
            )}

            {/* Divider in split mode */}
            {viewMode === 'split' && (
              <div className="vault-split-divider" />
            )}

            {/* Preview pane */}
            {(viewMode === 'preview' || viewMode === 'split') && (
              <div className={`vault-preview-pane${viewMode === 'split' ? ' vault-preview-pane--split' : ' vault-preview-pane--full'}`}>
                <MarkdownPreview content={editContent} />
              </div>
            )}
          </>
        )}

        {/* ── Non-markdown text (code) ── */}
        {file.type === 'text' && !isMarkdown && (
          <div className="flex-1 overflow-auto">
            <CodeBlock code={file.content} lang={file.lang} />
          </div>
        )}

        {/* ── Raster image ── */}
        {file.type === 'image' && (
          <div className="flex-1 flex items-center justify-center p-6">
            <img
              src={`data:${file.mime};base64,${file.data}`}
              alt={file.path}
              className="max-w-full max-h-[80vh] object-contain"
              style={{ imageRendering: 'auto' }}
            />
          </div>
        )}

        {/* ── SVG ── */}
        {file.type === 'svg' && (
          <div className="flex-1 flex items-center justify-center p-6">
            <img
              src={`data:image/svg+xml;utf8,${encodeURIComponent(file.content)}`}
              alt={file.path}
              className="max-w-full max-h-[80vh] object-contain"
              style={{ imageRendering: 'auto' }}
            />
          </div>
        )}

        {/* ── PDF ── */}
        {file.type === 'pdf' && (
          <iframe
            src={`data:application/pdf;base64,${file.data}`}
            className="flex-1 w-full border-0"
            style={{ minHeight: '600px' }}
            title={file.path}
          />
        )}
      </div>
    </div>
  )
}
