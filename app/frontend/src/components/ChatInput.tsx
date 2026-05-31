import { forwardRef, useImperativeHandle, useRef, useState, useCallback, useMemo } from 'react'

export interface ChatInputHandle {
  setText: (text: string) => void
  clear: () => void
  focus: () => void
  submit: () => void
}

interface ChatInputProps {
  onSubmit: (text: string, imageFile?: File) => void
  disabled?: boolean
  placeholder?: string
}

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

/**
 * Isolated chat input. Owns its own text state so keystrokes do NOT
 * re-render the parent (and therefore do not re-render the message list,
 * which is the dominant cost on long conversations). The parent interacts
 * with the input imperatively via the ref handle (setText / clear / focus /
 * submit) — never by passing the text down as a controlled prop.
 */
export const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(
  function ChatInput({ onSubmit, disabled, placeholder }, ref) {
    const [text, setText] = useState('')
    const [showAutocomplete, setShowAutocomplete] = useState(false)
    const [selectedIndex, setSelectedIndex] = useState(0)
    const [imageFile, setImageFile] = useState<File | null>(null)
    const [imagePreview, setImagePreview] = useState<string | null>(null)
    const fileInputRef = useRef<HTMLInputElement>(null)
    const textareaRef = useRef<HTMLTextAreaElement>(null)
    const autocompleteRef = useRef<HTMLDivElement>(null)

    // Filter commands based on current text
    const filteredCommands = useMemo(() => {
      if (!text.startsWith('/')) return []
      const typed = text.toLowerCase()
      return SLASH_COMMANDS.filter((c) => c.cmd.startsWith(typed))
    }, [text])

    const handleImageSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (!file) return
      setImageFile(file)
      const url = URL.createObjectURL(file)
      setImagePreview(url)
      e.target.value = '' // reset so same file can be reselected
    }, [])

    const clearImage = useCallback(() => {
      setImageFile(null)
      if (imagePreview) URL.revokeObjectURL(imagePreview)
      setImagePreview(null)
    }, [imagePreview])

    const doSubmit = useCallback(() => {
      const trimmed = text.trim()
      if (!trimmed || disabled) return
      onSubmit(trimmed, imageFile ?? undefined)
      setText('')
      setShowAutocomplete(false)
      clearImage()
    }, [text, disabled, onSubmit, imageFile, clearImage])

    useImperativeHandle(ref, () => ({
      setText,
      clear: () => { setText(''); setShowAutocomplete(false) },
      focus: () => textareaRef.current?.focus(),
      submit: doSubmit,
    }))

    function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
      // Autocomplete navigation
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

      // Enter to submit (without shift)
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        doSubmit()
        return
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

    function handleAutocompleteClick(cmd: string) {
      setText(cmd + ' ')
      setShowAutocomplete(false)
      setSelectedIndex(0)
      textareaRef.current?.focus()
    }

    return (
      <div className="relative flex flex-col flex-1 min-w-[12rem]">
        {/* Hidden file input for image selection */}
        <input
          type="file"
          ref={fileInputRef}
          accept="image/png,image/jpeg,image/gif,image/webp"
          onChange={handleImageSelect}
          className="hidden"
        />

        {/* Image preview */}
        {imagePreview && (
          <div className="relative mb-1 inline-block">
            <img src={imagePreview} alt="preview" className="max-h-24 rounded-lg" />
            <button
              onClick={clearImage}
              className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-zinc-700 text-zinc-300 text-xs flex items-center justify-center hover:bg-red-600"
            >
              ×
            </button>
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
                onClick={() => handleAutocompleteClick(cmd.cmd)}
                onMouseEnter={() => setSelectedIndex(i)}
                className={`w-full flex items-center gap-3 px-3 py-2 text-left text-sm transition-colors ${
                  i === selectedIndex
                    ? 'bg-zinc-700 text-zinc-100'
                    : 'text-zinc-300 hover:bg-zinc-800'
                }`}
              >
                <span className="font-mono text-[#FFB633] font-semibold">{cmd.cmd}</span>
                <span className="text-zinc-500 truncate">{cmd.desc}</span>
              </button>
            ))}
          </div>
        )}

        {/* Note: the autocomplete dropdown's parent .relative div is the outer
            container, so the dropdown still positions relative to the whole block.
            The textarea + attach button are wrapped in a flex row below. */}

        <div className="flex items-end gap-2">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled}
            className="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-lg bg-zinc-700 text-zinc-300 hover:bg-zinc-600 disabled:opacity-50 text-lg"
            title="Attach image"
          >
            +
          </button>
          <textarea
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
