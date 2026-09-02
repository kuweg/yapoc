import { forwardRef, useImperativeHandle, useRef, useState, useCallback, useMemo, useEffect } from 'react'

export interface ChatInputHandle {
  setText: (text: string) => void
  clear: () => void
  focus: () => void
  submit: () => void
}

interface ChatInputProps {
  onSubmit: (text: string, files: File[]) => void
  disabled?: boolean
  placeholder?: string
}

const MAX_FILES = 10

// Slash commands for autocomplete
const SLASH_COMMANDS = [
  { cmd: '/help', desc: 'Show available commands' },
  { cmd: '/clear', desc: 'Clear conversation and start new session' },
  { cmd: '/ping', desc: 'Ping the server' },
  { cmd: '/status', desc: 'Show server & agent status' },
  { cmd: '/agents', desc: 'List all agents' },
  { cmd: '/model', desc: 'Show current adapter/model' },
  { cmd: '/cost', desc: 'Show session cost breakdown' },
  { cmd: '/sessions', desc: 'List recent sessions' },
  { cmd: '/continue', desc: 'Resume the latest session' },
  { cmd: '/resume', desc: 'Resume a specific session (e.g. /resume <id>)' },
  { cmd: '/export', desc: 'Export conversation to file (e.g. /export <filename>)' },
  { cmd: '/doctor', desc: 'Run doctor health check' },
  { cmd: '/start', desc: 'Start the backend server' },
  { cmd: '/stop', desc: 'Stop the backend server' },
  { cmd: '/restart', desc: 'Restart the backend server' },
  { cmd: '/exit', desc: 'No-op in web UI' },
]

const IMG_RE = /\.(png|jpe?g|gif|webp|svg|bmp)$/i
function isImage(file: File): boolean {
  return file.type.startsWith('image/') || IMG_RE.test(file.name)
}

/**
 * Isolated chat input with multi-file attachment staging (spec: a dedicated
 * fileHandler). Files can be added via the picker, drag-drop onto the chat
 * input, or clipboard paste. Each staged file gets an object-URL preview that
 * is always revoked on removal to avoid leaks. The parent interacts via the ref
 * handle and receives the staged File[] on submit.
 */
export const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(
  function ChatInput({ onSubmit, disabled, placeholder }, ref) {
    const [text, setText] = useState('')
    const [showAutocomplete, setShowAutocomplete] = useState(false)
    const [selectedIndex, setSelectedIndex] = useState(0)
    const [pending, setPending] = useState<File[]>([])
    const [expanded, setExpanded] = useState(false)
    const [dragOver, setDragOver] = useState(false)
    const fileInputRef = useRef<HTMLInputElement>(null)
    const textareaRef = useRef<HTMLTextAreaElement>(null)
    const autocompleteRef = useRef<HTMLDivElement>(null)
    // File -> object URL (preview). WeakMap so URLs are reclaimable with files.
    const previews = useRef<WeakMap<File, string>>(new WeakMap())

    const previewFor = useCallback((file: File): string | null => {
      if (!isImage(file)) return null
      let url = previews.current.get(file)
      if (!url) {
        url = URL.createObjectURL(file)
        previews.current.set(file, url)
      }
      return url
    }, [])

    const revoke = useCallback((file: File) => {
      const url = previews.current.get(file)
      if (url) {
        URL.revokeObjectURL(url)
        previews.current.delete(file)
      }
    }, [])

    const filteredCommands = useMemo(() => {
      if (!text.startsWith('/')) return []
      const typed = text.toLowerCase()
      return SLASH_COMMANDS.filter((c) => c.cmd.startsWith(typed))
    }, [text])

    const addFiles = useCallback((files: FileList | File[]) => {
      const incoming = Array.from(files)
      if (!incoming.length) return
      setPending((prev) => {
        const room = MAX_FILES - prev.length
        if (room <= 0) return prev
        return [...prev, ...incoming.slice(0, room)]
      })
    }, [])

    const removePending = useCallback((idx: number) => {
      setPending((prev) => {
        const f = prev[idx]
        if (f) revoke(f)
        return prev.filter((_, i) => i !== idx)
      })
    }, [revoke])

    const clearPending = useCallback(() => {
      setPending((prev) => { prev.forEach(revoke); return [] })
      setExpanded(false)
    }, [revoke])

    const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files) addFiles(e.target.files)
      e.target.value = '' // allow re-selecting the same file
    }, [addFiles])

    // Clipboard paste of files/images anywhere on the page.
    useEffect(() => {
      const onPaste = (e: ClipboardEvent) => {
        const items = e.clipboardData?.items
        if (!items) return
        const files: File[] = []
        for (const it of items) {
          if (it.kind === 'file') {
            const f = it.getAsFile()
            if (f) {
              // Name pasted images so the server has an extension.
              files.push(f.name ? f : new File([f], 'paste.png', { type: f.type || 'image/png' }))
            }
          }
        }
        if (files.length) { e.preventDefault(); addFiles(files) }
      }
      window.addEventListener('paste', onPaste)
      return () => window.removeEventListener('paste', onPaste)
    }, [addFiles])

    const doSubmit = useCallback(() => {
      const trimmed = text.trim()
      if ((!trimmed && pending.length === 0) || disabled) return
      onSubmit(trimmed, pending)
      setText('')
      setShowAutocomplete(false)
      // Keep object URLs valid for the optimistic bubble; the parent owns them now.
      setPending([])
      setExpanded(false)
    }, [text, disabled, onSubmit, pending])

    useImperativeHandle(ref, () => ({
      setText,
      clear: () => { setText(''); setShowAutocomplete(false) },
      focus: () => textareaRef.current?.focus(),
      submit: doSubmit,
    }), [setText, doSubmit])

    function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
      if (showAutocomplete && filteredCommands.length > 0) {
        if (e.key === 'ArrowDown') {
          e.preventDefault()
          setSelectedIndex((prev) => (prev + 1) % filteredCommands.length)
          return
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault()
          setSelectedIndex((prev) => (prev - 1 + filteredCommands.length) % filteredCommands.length)
          return
        }
        if (e.key === 'Tab' || e.key === 'Enter') {
          const selected = filteredCommands[selectedIndex]
          if (selected) {
            e.preventDefault()
            setText(selected.cmd + ' ')
            setShowAutocomplete(false)
            setSelectedIndex(0)
            return
          }
        }
        if (e.key === 'Escape') {
          setShowAutocomplete(false)
          setSelectedIndex(0)
          return
        }
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        doSubmit()
      }
    }

    function handleChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
      const newText = e.target.value
      setText(newText)
      if (newText.startsWith('/')) {
        const matches = SLASH_COMMANDS.filter((c) => c.cmd.startsWith(newText.toLowerCase()))
        setShowAutocomplete(matches.length > 0)
        setSelectedIndex(0)
      } else {
        setShowAutocomplete(false)
      }
    }

    const collapsed = pending.length > 3 && !expanded

    return (
      <div
        className={`relative flex flex-col flex-1 min-w-[12rem] ${dragOver ? 'ring-2 ring-[#FFB633] rounded-lg' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={(e) => { e.preventDefault(); setDragOver(false) }}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files) }}
      >
        <input
          type="file"
          ref={fileInputRef}
          multiple
          onChange={handleFileSelect}
          className="hidden"
        />

        {/* Attach strip */}
        {pending.length > 0 && (
          <div id="attach-strip" className="mb-1 flex flex-wrap gap-1.5">
            {collapsed ? (
              <button
                onClick={() => setExpanded(true)}
                className="inline-flex items-center gap-2 rounded-lg bg-zinc-800 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-700"
              >
                📎 {pending.length} files
                <span
                  role="button"
                  onClick={(e) => { e.stopPropagation(); clearPending() }}
                  className="w-4 h-4 rounded-full bg-zinc-700 hover:bg-red-600 flex items-center justify-center"
                >×</span>
              </button>
            ) : (
              pending.map((file, idx) => {
                const url = previewFor(file)
                return (
                  <div key={idx} className="relative inline-flex items-center gap-2 rounded-lg bg-zinc-800 px-2 py-1.5 max-w-[180px]">
                    {url ? (
                      <img src={url} alt={file.name} className="max-h-12 max-w-[80px] rounded object-cover" />
                    ) : (
                      <span className="text-zinc-400 text-xs font-mono truncate">📄 {file.name}</span>
                    )}
                    <button
                      onClick={() => removePending(idx)}
                      className="w-4 h-4 rounded-full bg-zinc-700 text-zinc-300 text-xs flex items-center justify-center hover:bg-red-600 flex-shrink-0"
                      title="Remove"
                    >×</button>
                  </div>
                )
              })
            )}
          </div>
        )}

        {/* Autocomplete dropdown */}
        {showAutocomplete && filteredCommands.length > 0 && (
          <div
            ref={autocompleteRef}
            className="absolute bottom-full left-0 right-0 mb-1 rounded-lg border border-zinc-700 bg-zinc-900 shadow-xl overflow-hidden z-50"
          >
            {filteredCommands.map((cmd, i) => (
              <button
                key={cmd.cmd}
                onClick={() => { setText(cmd.cmd + ' '); setShowAutocomplete(false); setSelectedIndex(0); textareaRef.current?.focus() }}
                onMouseEnter={() => setSelectedIndex(i)}
                className={`w-full flex items-center gap-3 px-3 py-2 text-left text-sm transition-colors ${
                  i === selectedIndex ? 'bg-zinc-700 text-zinc-100' : 'text-zinc-300 hover:bg-zinc-800'
                }`}
              >
                <span className="font-mono text-[#FFB633] font-semibold">{cmd.cmd}</span>
                <span className="text-zinc-500 truncate">{cmd.desc}</span>
              </button>
            ))}
          </div>
        )}

        <div className="flex items-end gap-2">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled}
            className="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-lg bg-zinc-700 text-zinc-300 hover:bg-zinc-600 disabled:opacity-50 text-lg"
            title="Attach files (drag-drop or paste too)"
          >
            +
          </button>
          <textarea
        aria-label="Message YAPOC"
            ref={textareaRef}
            value={text}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            placeholder={placeholder ?? 'Message YAPOC… (Enter to send, Shift+Enter for newline)'}
            disabled={disabled}
            rows={3}
            className="w-full resize-none rounded-lg bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-500 disabled:opacity-50"
          />
        </div>
      </div>
    )
  },
)
