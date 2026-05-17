import { forwardRef, useImperativeHandle, useRef, useState } from 'react'

export interface ChatInputHandle {
  setText: (text: string) => void
  clear: () => void
  focus: () => void
  submit: () => void
}

interface ChatInputProps {
  onSubmit: (text: string) => void
  disabled?: boolean
  placeholder?: string
}

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
    const textareaRef = useRef<HTMLTextAreaElement>(null)

    function doSubmit() {
      const trimmed = text.trim()
      if (!trimmed || disabled) return
      onSubmit(trimmed)
      setText('')
    }

    useImperativeHandle(ref, () => ({
      setText,
      clear: () => setText(''),
      focus: () => textareaRef.current?.focus(),
      submit: doSubmit,
    }))

    function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        doSubmit()
      }
    }

    return (
      <textarea
        ref={textareaRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder ?? 'Message YAPOC… (Enter to send, Shift+Enter for newline)'}
        disabled={disabled}
        rows={3}
        className="flex-1 min-w-[12rem] resize-none rounded-lg bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-500 disabled:opacity-50"
      />
    )
  },
)
