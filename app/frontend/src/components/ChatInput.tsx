import {ContextTray} from '../studio/ContextTray'
import { useUniverseStore } from '../store/universeStore'
import { forwardRef, useImperativeHandle, useRef, useState, useCallback, useMemo, useEffect, useLayoutEffect } from 'react'
import { listUploads } from '../api/client'
import type { Attachment } from '../api/types'
import { resolveMentions } from '../lib/mentions'
import { detectTrigger, type Suggestion, type TriggerMatch } from '../lib/composerSuggest'
import { ensureMentionSource, ensureMentionSourcesFor, mentionSources } from '../lib/mentionSources'
import { hasHighlights, tokenizeChatText } from '../lib/chatTokens'
import { ComposerSuggestions } from './ComposerSuggestions'
import { HighlightedText } from './HighlightedText'
import { useSessionStore } from '../store/session'
import { useWorkspaceStore } from '../store/workspaceStore'

export interface ChatInputHandle {
  setText: (text: string) => void
  clear: () => void
  focus: () => void
  submit: () => void | Promise<void>
}

/** Everything one send carries. An object, because these are not four numbers. */
export interface ComposerSubmission {
  /** Text for master, with subsystem mentions expanded. */
  text: string
  /** Text for the user's own bubble, with mentions left as written. */
  displayText: string
  files: File[]
  attachmentIds: string[]
  /** Notes to inline server-side, resolved from `@note:` mentions. */
  noteIds: string[]
}

interface ChatInputProps {
  onSubmit: (submission: ComposerSubmission) => void
  disabled?: boolean
  placeholder?: string
}

const MAX_FILES = 10
/** Tallest the composer grows before it starts scrolling instead. */
const MAX_HEIGHT = 320
/** Show the character count only once a message is long enough to care. */
const COUNT_THRESHOLD = 1200

const DRAFT_KEY = 'yapoc-composer-drafts'

/** Unsent text, per session, so switching chats does not throw it away. */
function readDrafts(): Record<string, string> {
  try {
    const raw = localStorage.getItem(DRAFT_KEY)
    const parsed: unknown = raw ? JSON.parse(raw) : {}
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Record<string, string>) : {}
  } catch {
    return {}
  }
}

function writeDraft(sessionId: string, text: string) {
  try {
    const drafts = readDrafts()
    if (text.trim()) drafts[sessionId] = text
    else delete drafts[sessionId]
    // Cap the store so a long-lived browser profile can't grow it without end.
    const trimmed = Object.fromEntries(Object.entries(drafts).slice(-20))
    localStorage.setItem(DRAFT_KEY, JSON.stringify(trimmed))
  } catch {
    // Private-mode / quota failures are not worth surfacing over a draft.
  }
}

const IMG_RE = /\.(png|jpe?g|gif|webp|svg|bmp)$/i
const PDF_RE = /\.pdf$/i
function isImage(file: File): boolean {
  return file.type.startsWith('image/') || IMG_RE.test(file.name)
}

function isPdf(file: File): boolean {
  return file.type === 'application/pdf' || PDF_RE.test(file.name)
}

/**
 * Isolated chat input with multi-file attachment staging (spec: a dedicated
 * fileHandler). Files can be added via the picker, drag-drop onto the chat
 * input, or clipboard paste. Each staged file gets an object-URL preview that
 * is always revoked on removal to avoid leaks. The parent interacts via the ref
 * handle and receives the staged File[] on submit.
 *
 * The field itself is a textarea rendered transparent over a highlight overlay,
 * so slash commands and `@` mentions are coloured as they are typed; the two
 * share their text metrics through `.composer-field` in index.css. It grows with
 * its content, remembers a per-session draft, and drives one suggestion palette
 * for commands and every mention kind.
 */
export const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(
  function ChatInput({ onSubmit, disabled, placeholder }, ref) {
    const [actionsOpen, setActionsOpen] = useState(false)
    const [text, setText] = useState('')
    const [caret, setCaret] = useState(0)
    const [trigger, setTrigger] = useState<TriggerMatch | null>(null)
    const [menuDismissed, setMenuDismissed] = useState(false)
    const [activeIndex, setActiveIndex] = useState(0)
    /** Bumped when an entity list finishes loading, to re-run trigger detection. */
    const [sourceTick, setSourceTick] = useState(0)
    const [uploads, setUploads] = useState<Attachment[]>([])
    const [pending, setPending] = useState<File[]>([])
    const [expanded, setExpanded] = useState(false)
    const [dragOver, setDragOver] = useState(false)
    const activeId = useSessionStore((s) => s.activeId)
    const pendingInsertion = useWorkspaceStore((state) => state.pendingInsertion)
    const consumePendingInsertion = useWorkspaceStore((state) => state.consumePendingInsertion)
    const fileInputRef = useRef<HTMLInputElement>(null)
    const textareaRef = useRef<HTMLTextAreaElement>(null)
    const overlayRef = useRef<HTMLDivElement>(null)
    // File -> object URL (preview). WeakMap so URLs are reclaimable with files.
    const previews = useRef<WeakMap<File, string>>(new WeakMap())

    useEffect(() => {
      const insertion = consumePendingInsertion()
      if (!insertion) return
      setText((current) => `${current}${current && !/\s$/.test(current) ? ' ' : ''}${insertion}`)
      textareaRef.current?.focus()
    }, [pendingInsertion, consumePendingInsertion])

    // Restore this session's draft on switch, and save it as it changes. Keyed
    // on activeId only: a re-render must not clobber what is being typed.
    useEffect(() => {
      if (!activeId) return
      setText(readDrafts()[activeId] ?? '')
      setTrigger(null)
    }, [activeId])

    useEffect(() => {
      if (!activeId) return
      const timer = window.setTimeout(() => writeDraft(activeId, text), 400)
      return () => window.clearTimeout(timer)
    }, [activeId, text])

    // Grow with the content up to MAX_HEIGHT, then scroll.
    useLayoutEffect(() => {
      const el = textareaRef.current
      if (!el) return
      el.style.height = 'auto'
      el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`
    }, [text])

    const tokens = useMemo(() => tokenizeChatText(text), [text])
    const highlighted = useMemo(() => hasHighlights(tokens), [tokens])

    // Which mentions in the current text point at nothing. Recomputed from the
    // already-loaded lists only — typing must never wait on a fetch — and
    // suppressed while the palette is open, since a half-typed mention is
    // "unresolved" on every keystroke and warning about it is just noise.
    const unresolved = useMemo(() => {
      if (!text.includes('@') || trigger) return []
      const sources = mentionSources()
      return resolveMentions(text, uploads, sources.artifacts ?? [], sources).unresolved
    }, [text, uploads, sourceTick, trigger])

    // What the palette should show for the caret's surroundings.
    useEffect(() => {
      if (menuDismissed) return
      const match = detectTrigger(text, caret)
      setTrigger(match)
      setActiveIndex((prev) => (match && prev < match.suggestions.length ? prev : 0))
      if (match?.needsSource) {
        // Resolves true only when a fetch actually ran, so this settles.
        void ensureMentionSource(match.needsSource).then((loaded) => {
          if (loaded) setSourceTick((t) => t + 1)
        })
      }
    }, [text, caret, sourceTick, menuDismissed])

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

    /** Replace the trigger span with a suggestion and put the caret after it. */
    const applySuggestion = useCallback((suggestion: Suggestion) => {
      const match = trigger
      if (!match) return
      const next = text.slice(0, match.start) + suggestion.insert + text.slice(match.end)
      const nextCaret = match.start + suggestion.insert.length
      setText(next)
      setCaret(nextCaret)
      setMenuDismissed(false)
      if (!suggestion.keepOpen) setTrigger(null)
      // The textarea is uncontrolled between renders here, so move the caret
      // once React has painted the new value.
      requestAnimationFrame(() => {
        const el = textareaRef.current
        if (!el) return
        el.focus()
        el.setSelectionRange(nextCaret, nextCaret)
      })
    }, [text, trigger])

    const doSubmit = useCallback(async () => {
      const trimmed = text.trim()
      if ((!trimmed && pending.length === 0) || disabled) return
      // A full `@file:<id>` reference is typed/pasted directly and never goes
      // through the `@file <name>` autocomplete path, so `uploads` may be empty
      // and the ID would fail to resolve. Fetch the upload list on demand when
      // the text contains any `@file:` reference so IDs resolve reliably.
      let resolvedUploads = uploads
      if (/@file:/i.test(trimmed) && resolvedUploads.length === 0) {
        try {
          const { files } = await listUploads()
          resolvedUploads = files
          setUploads(files)
        } catch {
          // leave empty — the reference stays literal and the backend fallback
          // (resolve_upload_by_ref) will still resolve it server-side.
        }
      }
      // Same idea for the other mention kinds: a mention typed or pasted whole
      // must resolve even if its palette never opened. This matters most for
      // notes, where an unresolved `@note:` token would otherwise reach the
      // backend and fail the entire request.
      await ensureMentionSourcesFor(trimmed)
      const sources = mentionSources()
      const resolved = resolveMentions(trimmed, resolvedUploads, sources.artifacts ?? [], sources)
      onSubmit({
        text: resolved.cleanedText,
        displayText: resolved.displayText,
        files: pending,
        attachmentIds: resolved.attachmentIds,
        noteIds: resolved.noteIds,
      })
      setText('')
      setCaret(0)
      setTrigger(null)
      setMenuDismissed(false)
      if (activeId) writeDraft(activeId, '')
      // Keep object URLs valid for the optimistic bubble; the parent owns them now.
      setPending([])
      setExpanded(false)
    }, [text, disabled, onSubmit, pending, uploads, activeId])

    useImperativeHandle(ref, () => ({
      setText: (value: string) => {
        setText(value)
        setCaret(value.length)
        setMenuDismissed(false)
      },
      clear: () => { setText(''); setCaret(0); setTrigger(null) },
      focus: () => textareaRef.current?.focus(),
      submit: doSubmit,
    }), [doSubmit])

    const menuOpen = Boolean(trigger && trigger.suggestions.length > 0 && !menuDismissed)

    function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
      if (menuOpen && trigger) {
        const count = trigger.suggestions.length
        if (e.key === 'ArrowDown') {
          e.preventDefault()
          setActiveIndex((prev) => (prev + 1) % count)
          return
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault()
          setActiveIndex((prev) => (prev - 1 + count) % count)
          return
        }
        if (e.key === 'Tab' || e.key === 'Enter') {
          const selected = trigger.suggestions[activeIndex]
          if (selected) {
            e.preventDefault()
            applySuggestion(selected)
            return
          }
        }
        if (e.key === 'Escape') {
          e.preventDefault()
          setMenuDismissed(true)
          setTrigger(null)
          return
        }
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        void doSubmit()
      }
    }

    function handleChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
      setText(e.target.value)
      setCaret(e.target.selectionStart ?? e.target.value.length)
      setMenuDismissed(false)
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
                      <span className="text-zinc-400 text-xs font-mono truncate">{isPdf(file) ? '📕' : '📄'} {file.name}</span>
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

        <ContextTray text={text} onRemove={(start,end)=>{setText(value=>value.slice(0,start)+value.slice(end));setCaret(start);setTrigger(null);setMenuDismissed(true);textareaRef.current?.focus()}}/>
        {menuOpen && trigger && (
          <ComposerSuggestions
            suggestions={trigger.suggestions}
            activeIndex={activeIndex}
            onPick={applySuggestion}
            onHover={setActiveIndex}
          />
        )}

        <div className="flex items-end gap-2">
          <div className="relative">
            <button type="button" aria-label="Composer actions" aria-expanded={actionsOpen} onClick={() => setActionsOpen(value => !value)} disabled={disabled} className="w-8 h-8 rounded-lg bg-zinc-700 text-zinc-300">+</button>
            {actionsOpen && <div className="absolute bottom-10 left-0 z-50 w-56 rounded-lg border border-zinc-700 bg-zinc-900 p-1 shadow-xl" onKeyDown={e => { if (e.key === 'Escape') setActionsOpen(false) }}>
              <button type="button" className="block w-full rounded px-3 py-2 text-left text-sm hover:bg-zinc-800" onClick={() => { setActionsOpen(false); fileInputRef.current?.click() }}>Attach files</button>
              <button type="button" className="block w-full rounded px-3 py-2 text-left text-sm hover:bg-zinc-800" onClick={() => { setActionsOpen(false); useUniverseStore.getState().setup(text) }}>Try parallel approaches</button>
            </div>}
          </div>
          <div className={`composer-field ${highlighted ? '' : 'is-plain'}`}>
            {highlighted && (
              <div ref={overlayRef} className="composer-overlay" aria-hidden="true">
                <HighlightedText text={text} variant="overlay" />
              </div>
            )}
            <textarea
              aria-label="Message YAPOC"
              ref={textareaRef}
              value={text}
              onChange={handleChange}
              onKeyDown={handleKeyDown}
              onSelect={(e) => setCaret(e.currentTarget.selectionStart ?? 0)}
              onScroll={() => {
                if (overlayRef.current && textareaRef.current) {
                  overlayRef.current.scrollTop = textareaRef.current.scrollTop
                }
              }}
              onBlur={() => setTrigger(null)}
              placeholder={placeholder ?? 'What would you like to work on? / for commands, @ for notes, agents, files…'}
              disabled={disabled}
              rows={1}
              aria-autocomplete="list"
              aria-expanded={menuOpen}
            />
          </div>
        </div>

        {(unresolved.length > 0 || text.length > COUNT_THRESHOLD) && (
          <div className="flex items-baseline gap-3">
            {unresolved.length > 0 && (
              <div className="composer-warning">
                {unresolved.map((u) => `@${u.kind}:${u.query}`).join(', ')} — no match{unresolved.length > 1 ? 'es' : ''} found
                {unresolved.some((u) => u.kind === 'note') ? '; sent as plain text' : ''}
              </div>
            )}
            {text.length > COUNT_THRESHOLD && (
              <div className="composer-warning composer-count ml-auto text-zinc-500">{text.length.toLocaleString()} chars</div>
            )}
          </div>
        )}
      </div>
    )
  },
)
