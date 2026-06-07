import { useRef, useEffect, useState, useCallback } from 'react'
import { streamTask, ServerRestartError } from '../hooks/useStream'
import { useSessionStore } from '../store/session'
import { useWsStore } from '../store/wsStore'
import { useAppStore } from '../store/appStore'
import { useSpeechRecognition, useSpeechSynthesis } from '../hooks/useSpeech'
import { handleCommand, synthesizeSpeech, getAgents, uploadFiles } from '../api/client'
import { MessageBubble } from './MessageBubble'
import { ToolCallBlock } from './ToolCallBlock'
import { ThinkingBlock } from './ThinkingBlock'
import { GroupedToolCallBlock } from './GroupedToolCallBlock'
import { CompactionMarker } from './ContextGauge'
import { groupParts } from './groupParts'
import { TaskGroupBubble, type TaskGroup } from './TaskGroupBubble'
import { CostBar } from './CostBar'
import { VoiceSettings } from './VoiceSettings'
import { ChatInput, type ChatInputHandle } from './ChatInput'
import { startAsciiWave, ASCII_WAVE_FRAMES } from './spinner'
import type { UsageEvent, TaskPart, Attachment } from '../api/types'
import type { SessionEventEnvelope } from '../store/wsStore'

type Part = TaskPart

// Buffered stream events, flushed once per animation frame to cap streaming-
// induced re-renders at ~60Hz regardless of delta rate.
type PendingStreamEvent =
  | { kind: 'thinking_delta'; text: string }
  | { kind: 'text_delta'; text: string }
  | { kind: 'tool_start'; id: string; name: string; input: Record<string, unknown> }
  | { kind: 'tool_done'; name: string; result: string; isError: boolean }
  | { kind: 'compact'; tokensBefore: number; tokensAfter: number; reason: string }

/** ES2023 findLastIndex polyfill */
function findLastIndex<T>(arr: T[], predicate: (item: T) => boolean): number {
  for (let i = arr.length - 1; i >= 0; i--) {
    if (predicate(arr[i])) return i
  }
  return -1
}

function applyPendingEvents(prev: Part[], events: PendingStreamEvent[]): Part[] {
  let parts = prev
  for (const event of events) {
    if (event.kind === 'thinking_delta') {
      const last = parts[parts.length - 1]
      if (last && last.kind === 'thinking' && !last.done) {
        parts = [...parts.slice(0, -1), { ...last, text: last.text + event.text }]
      } else {
        parts = [
          ...parts,
          { kind: 'thinking', id: crypto.randomUUID(), text: event.text, done: false },
        ]
      }
    } else if (event.kind === 'text_delta') {
      const last = parts[parts.length - 1]
      if (last && last.kind === 'text') {
        parts = [...parts.slice(0, -1), { kind: 'text', text: last.text + event.text }]
      } else {
        parts = [...parts, { kind: 'text', text: event.text }]
      }
    } else if (event.kind === 'tool_start') {
      parts = [
        ...parts,
        { kind: 'tool', id: event.id, name: event.name, input: event.input, done: false },
      ]
    } else if (event.kind === 'tool_done') {
      const target = parts
        .map((p, i) => ({ p, i }))
        .reverse()
        .find(({ p }) => p.kind === 'tool' && !(p as { kind: 'tool'; id: string; name: string; input: Record<string, unknown>; result?: string; isError?: boolean; done: boolean }).done && p.name === event.name)
      if (target) {
        const updated = [...parts]
        updated[target.i] = {
          ...(updated[target.i] as { kind: 'tool'; id: string; name: string; input: Record<string, unknown>; result?: string; isError?: boolean; done: boolean }),
          result: event.result,
          isError: event.isError,
          done: true,
        }
        parts = updated
      }
    } else if (event.kind === 'compact') {
      parts = [
        ...parts,
        { kind: 'compact', id: crypto.randomUUID(), tokensBefore: event.tokensBefore, tokensAfter: event.tokensAfter, reason: event.reason },
      ]
    }
  }
  return parts
}

// Default model for cost estimation — overridden at runtime by masterModel state
const DEFAULT_MODEL = 'kimi-k2.6'

// How long to wait for a fire-and-forget background notification before giving
// up and finalizing the task group (so "Task running" never sticks forever).
const NOTIFICATION_TIMEOUT_MS = 150_000

// ── Animated send/stop button ──────────────────────────────────────
// Loading / typing indicator (spec §5). Drives the ASCII wave via the spinner
// module so the interval handle is owned and cleared on unmount (rule #5);
// honors prefers-reduced-motion by rendering a static frame.
function TypingIndicator() {
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce) {
      el.textContent = ASCII_WAVE_FRAMES[2]
      return
    }
    const handle = startAsciiWave(el, 120)
    return () => handle.stop()
  }, [])
  return <span ref={ref} className="font-mono text-[#FFB633] w-7 inline-block" aria-hidden />
}

function SendButton({ isStreaming, launchTick, onSend, onStop }: { isStreaming: boolean; launchTick: number; onSend: () => void; onStop: () => void }) {
  // `view` is the VISUAL icon state, decoupled from isStreaming so the launch
  // (arrow flies up & out) completes before the stop icon swaps in (spec §4):
  //   send --launch--> [animationend] --> streaming(stop) --land--> send
  const [view, setView] = useState<'send' | 'streaming'>('send')
  const [phase, setPhase] = useState<'processing' | 'receiving'>('processing')
  const [animClass, setAnimClass] = useState('')
  const launching = useRef(false)
  const firstTick = useRef(true)

  // Launch on every real send (click OR Enter — driven by launchTick), keeping
  // view='send' so the arrow is mounted to animate. The swap to the stop icon
  // happens on the launch's animationend.
  useEffect(() => {
    if (firstTick.current) {
      firstTick.current = false
      return
    }
    launching.current = true
    setAnimClass('anim-launch')
  }, [launchTick])

  // Drive the streaming phase (processing pulse -> receiving quarter-turn).
  useEffect(() => {
    if (view !== 'streaming') return
    setPhase('processing')
    const t = setTimeout(() => setPhase('receiving'), 2000)
    return () => clearTimeout(t)
  }, [view])

  const prevStreaming = useRef(isStreaming)
  useEffect(() => {
    if (prevStreaming.current && !isStreaming) {
      // Stream ended — arrow returns (land).
      setView('send')
      setAnimClass('anim-land')
    } else if (!prevStreaming.current && isStreaming && !launching.current) {
      // Streaming started without a launch (e.g. programmatic) — show stop now.
      setView('streaming')
    }
    prevStreaming.current = isStreaming
  }, [isStreaming])

  const handleClick = () => {
    if (view === 'send') onSend() // launch is fired by launchTick on the actual send
    else onStop()
  }

  const handleAnimEnd = () => {
    if (animClass === 'anim-launch') {
      setAnimClass('')
      launching.current = false
      if (isStreaming) setView('streaming') // swap to stop icon after the launch
    } else if (animClass === 'anim-land') {
      setAnimClass('')
    }
  }

  const mode = view

  return (
    <button
      onClick={handleClick}
      onAnimationEnd={handleAnimEnd}
      data-mode={mode}
      data-phase={phase}
      className={`send-btn flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center transition-colors ${
        mode === 'send'
          ? animClass === 'anim-launch' ? 'bg-[#FFB633]' : 'bg-[#FFB633] hover:bg-[#ffc84d]'
          : 'bg-red-700 hover:bg-red-600'
      } ${animClass}`}
      title={mode === 'send' ? 'Send message' : 'Stop streaming'}
    >
      {mode === 'send' ? (
        <svg
          width="16" height="16" viewBox="0 0 24 24"
          fill="none" stroke="#0a0a0a" strokeWidth="2.5"
          strokeLinecap="round" strokeLinejoin="round"
          className={animClass === 'anim-launch' ? 'anim-launch' : ''}
        >
          <line x1="12" y1="19" x2="12" y2="5" />
          <polyline points="5 12 12 5 19 12" />
        </svg>
      ) : (
        <svg
          width="14" height="14" viewBox="0 0 24 24"
          fill="white" stroke="white" strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round"
          className={phase === 'processing' ? 'animate-[siren-icon_1.5s_ease-in-out_infinite]' : 'animate-[quarter-turn_2s_cubic-bezier(0.4,0,0.2,1)_infinite]'}
        >
          <rect x="6" y="6" width="12" height="12" rx="1" />
        </svg>
      )}
    </button>
  )
}

/**
 * Renders a TaskPart[] as a vertical CHAIN of steps — each text run is its own
 * bubble, consecutive same-name tool calls are grouped, thinking blocks inline.
 * Used identically for the live stream AND the saved message, so a response does
 * NOT collapse into a single block when it finishes (it just stops updating).
 *
 * `content` (the assembled summary text) is only rendered as a trailing bubble
 * when there are no text parts — otherwise it would duplicate the text already
 * shown in the chain (e.g. a direct response where the text *is* the answer).
 */
function PartsChain({
  parts,
  content,
  masterModel,
  streaming,
}: {
  parts: Part[]
  content?: string
  masterModel?: string
  streaming?: boolean
}) {
  const grouped = groupParts(parts)
  const hasText = parts.some((p) => p.kind === 'text')
  let labelShown = false // show the agent label once, on the first text bubble
  return (
    <div className="space-y-1">
      {grouped.map((part, i) => {
        if (part.kind === 'tool_group') {
          return <GroupedToolCallBlock key={`grp-${part.name}-${i}`} name={part.name} calls={part.calls} />
        }
        if (part.kind === 'text') {
          const showLabel = !labelShown
          labelShown = true
          return (
            <MessageBubble
              key={`t-${i}`}
              role="assistant"
              content={part.text}
              agentName={showLabel ? 'master' : undefined}
              agentModel={masterModel}
              streaming={streaming}
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
      })}
      {content && !hasText && (
        <MessageBubble role="assistant" content={content} agentName="master" agentModel={masterModel} />
      )}
    </div>
  )
}

export function ChatPanel() {
  const { activeId, history, appendMessage, pendingChatInput, clearPendingChatInput } = useSessionStore()
  const [streamingParts, setStreamingParts] = useState<Part[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [usage, setUsage] = useState<UsageEvent | null>(null)
  const [masterModel, setMasterModel] = useState<string>('')
  const [awaitingNotification, setAwaitingNotification] = useState(false)
  const [backgroundActivity, setBackgroundActivity] = useState<string>('')
  const [showVoiceSettings, setShowVoiceSettings] = useState(false)
  const [voiceError, setVoiceError] = useState<string | null>(null)
  const [backendSpeaking, setBackendSpeaking] = useState(false)
  const [taskGroups, setTaskGroups] = useState<TaskGroup[]>([])
  // Bulk-render guard (rule #2): suppress msg-enter while a session's history
  // is loaded wholesale, so old messages don't all animate in at once.
  const [noAnimate, setNoAnimate] = useState(true)
  // Welcome-screen reveal gate (spec §6): hold the splash hidden until after
  // first paint so the clip-path name reveal doesn't flicker during font load.
  const [welcomeReady, setWelcomeReady] = useState(false)
  // Bumped on every real send (click OR Enter) so the send button plays its
  // launch animation regardless of how the message was submitted (spec §4).
  const [launchTick, setLaunchTick] = useState(0)
  const abortRef = useRef<AbortController | null>(null)
  const backendAudioRef = useRef<HTMLAudioElement | null>(null)
  const backendAudioUrlRef = useRef<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickToBottomRef = useRef(true)
  const chatInputRef = useRef<ChatInputHandle>(null)
  // Ref to read latest streamingParts without closure staleness
  const streamingPartsRef = useRef<Part[]>([])
  // Stream-event coalescing — one setState per animation frame regardless of
  // how many SSE deltas arrive in that frame.
  const pendingEventsRef = useRef<PendingStreamEvent[]>([])
  const rafHandleRef = useRef<number | null>(null)

  // Keep ref in sync so sendMessage can capture the latest parts
  useEffect(() => {
    streamingPartsRef.current = streamingParts
  }, [streamingParts])

  // Rule #2: when a session's history loads in bulk, paint it once with
  // .no-animate, then drop the class on the next frame so subsequently
  // appended messages animate normally. Re-runs on session switch.
  useEffect(() => {
    setNoAnimate(true)
    const r1 = requestAnimationFrame(() =>
      requestAnimationFrame(() => setNoAnimate(false)),
    )
    return () => cancelAnimationFrame(r1)
  }, [activeId])

  // Spec §6: reveal the welcome splash only after first paint.
  useEffect(() => {
    const r = requestAnimationFrame(() => setWelcomeReady(true))
    return () => cancelAnimationFrame(r)
  }, [])

  const flushPendingEvents = useCallback(() => {
    rafHandleRef.current = null
    const events = pendingEventsRef.current
    if (events.length === 0) return
    pendingEventsRef.current = []
    setStreamingParts((prev) => applyPendingEvents(prev, events))
  }, [])

  const enqueueStreamEvent = useCallback(
    (event: PendingStreamEvent) => {
      pendingEventsRef.current.push(event)
      if (rafHandleRef.current == null) {
        rafHandleRef.current = requestAnimationFrame(flushPendingEvents)
      }
    },
    [flushPendingEvents],
  )

  const {
    voiceEnabled,
    selectedVoice,
    voiceSpeed,
    voiceTtsMode,
    voiceBackendEngine,
  } = useAppStore()

  const {
    speak: ttsSpeak,
    stop: ttsStop,
    isSpeaking: ttsSpeaking,
    supported: ttsSupported,
  } = useSpeechSynthesis({
    voice: selectedVoice || undefined,
    rate: voiceSpeed,
  })
  const isSpeaking = ttsSpeaking || backendSpeaking

  const { isListening: sttListening, start: sttStart, stop: sttStop, supported: sttSupported } =
    useSpeechRecognition({
      onResult: (transcript) => {
        chatInputRef.current?.setText(transcript)
      },
      onEnd: () => {},
      onError: () => {},
    })

  const cleanupBackendAudio = useCallback(() => {
    const audio = backendAudioRef.current
    if (audio) {
      audio.pause()
      backendAudioRef.current = null
    }
    if (backendAudioUrlRef.current) {
      URL.revokeObjectURL(backendAudioUrlRef.current)
      backendAudioUrlRef.current = null
    }
    setBackendSpeaking(false)
  }, [])

  const stopSpeaking = useCallback(() => {
    ttsStop()
    cleanupBackendAudio()
  }, [ttsStop, cleanupBackendAudio])

  const playBackendSpeech = useCallback(async (text: string) => {
    cleanupBackendAudio()
    setVoiceError(null)
    setBackendSpeaking(true)

    try {
      const audioBlob = await synthesizeSpeech({
        text,
        engine: voiceBackendEngine,
        speed: voiceSpeed,
        format: 'wav',
      })
      const url = URL.createObjectURL(audioBlob)
      const audio = new Audio(url)
      backendAudioRef.current = audio
      backendAudioUrlRef.current = url

      audio.onended = () => cleanupBackendAudio()
      audio.onerror = () => {
        cleanupBackendAudio()
        setVoiceError('Backend audio playback failed')
      }

      await audio.play()
    } catch (error) {
      cleanupBackendAudio()
      setVoiceError(error instanceof Error ? error.message : String(error))
    }
  }, [cleanupBackendAudio, voiceBackendEngine, voiceSpeed])

  const speakText = useCallback((text: string) => {
    const clean = text.trim()
    if (!voiceEnabled || !clean) return
    if (voiceTtsMode === 'backend') {
      void playBackendSpeech(clean)
      return
    }
    if (!ttsSupported) {
      setVoiceError('Browser speech is unavailable. Switch to Backend TTS mode.')
      return
    }
    setVoiceError(null)
    ttsSpeak(clean)
  }, [voiceEnabled, voiceTtsMode, playBackendSpeech, ttsSupported, ttsSpeak])

  // WebSocket-based background notification listener
  const lastCompletedTask = useWsStore((s) => s.lastCompletedTask)
  const clearLastCompletedTask = useWsStore((s) => s.clearLastCompletedTask)
  const lastSessionEvent = useWsStore((s) => s.lastSessionEvent)
  const lastOrphanNotification = useWsStore((s) => s.lastOrphanNotification)
  const clearLastOrphanNotification = useWsStore((s) => s.clearLastOrphanNotification)
  const wsConnected = useWsStore((s) => s.connected)

  const stopPolling = useCallback(() => {
    setAwaitingNotification(false)
    setBackgroundActivity('')
  }, [])

  // Track whether the user is parked at the bottom. If they've scrolled up
  // to read earlier output, don't yank them back down while new chunks stream.
  const handleScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    stickToBottomRef.current = distanceFromBottom < 80
  }, [])

  // Auto-scroll on new content — only when user is already at (or near) bottom
  useEffect(() => {
    if (!stickToBottomRef.current) return
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history, streamingParts])

  // Fetch master agent's model name on mount and whenever the WebSocket reconnects
  // (so the label updates after a server restart / model switch)
  useEffect(() => {
    getAgents().then((agents) => {
      const master = agents.find((a) => a.name === 'master')
      if (master?.model) setMasterModel(master.model)
    }).catch(() => {
      // ignore — model will just be empty
    })
  }, [wsConnected])

  // When the user sends a new message, snap to bottom regardless
  useEffect(() => {
    if (isStreaming) stickToBottomRef.current = true
  }, [isStreaming])

  // Persist a completed task group to history and remove it from taskGroups
  const persistTaskGroupToHistory = useCallback((group: TaskGroup) => {
    const text = group.finalText || '_Task completed_'
    const partsToSave = group.parts.length > 0 ? group.parts : undefined
    appendMessage('assistant', text, partsToSave)
    setTaskGroups((prev) => prev.filter((g) => g.id !== group.id))
  }, [appendMessage])

  // WebSocket notification: when a background task completes, persist to history
  useEffect(() => {
    if (!awaitingNotification || !lastCompletedTask || !activeId) return
    if (lastCompletedTask.session_id && lastCompletedTask.session_id !== activeId) return
    const result = lastCompletedTask.result?.trim()
    const hasError = Boolean(lastCompletedTask.error)

    setTaskGroups((prev) => {
      const idx = findLastIndex(prev, (g) => g.status === 'running')
      if (idx < 0) return prev
      const group = prev[idx]
      const errorText = lastCompletedTask.error
      const isGenericError = hasError && (!errorText || errorText === 'unknown' || errorText.trim() === '')
      const finalText = result || (hasError
        ? (isGenericError ? '_Task failed — check agent health logs_' : `_Background task error: ${errorText}_`)
        : '_Task completed_')
      const completedGroup: TaskGroup = {
        ...group,
        finalText,
        status: hasError ? 'error' : 'done',
      }
      // Schedule persistence via setTimeout to avoid setState-during-render
      setTimeout(() => persistTaskGroupToHistory(completedGroup), 0)
      return prev.filter((g) => g.id !== group.id)
    })

    setAwaitingNotification(false)
    setBackgroundActivity('')
    clearLastCompletedTask()
  }, [lastCompletedTask, awaitingNotification, activeId, clearLastCompletedTask, persistTaskGroupToHistory])

  useEffect(() => {
    if (!awaitingNotification || !lastSessionEvent || !activeId) return
    if (lastSessionEvent.session_id !== activeId) return
    const eventType = String(lastSessionEvent.event.type ?? '')
    if (eventType === 'notification_result') {
      const text = String(lastSessionEvent.event.text ?? '').trim()
      setTaskGroups((prev) => {
        const idx = findLastIndex(prev, (g) => g.status === 'running')
        if (idx < 0) return prev
        const group = prev[idx]
        const finalText = text || '_Task completed_'
        const completedGroup: TaskGroup = { ...group, finalText, status: 'done' }
        setTimeout(() => persistTaskGroupToHistory(completedGroup), 0)
        return prev.filter((g) => g.id !== group.id)
      })
      setAwaitingNotification(false)
      setBackgroundActivity('')
      return
    }
    const line = formatSessionActivity(lastSessionEvent)
    if (line) setBackgroundActivity(line)
  }, [awaitingNotification, lastSessionEvent, activeId, persistTaskGroupToHistory])

  // Orphan-notification fallback: when the backend couldn't route master's
  // notification result to a specific session (session_id lost upstream),
  // it broadcasts a top-level notification_result event. Persist to history.
  useEffect(() => {
    if (!awaitingNotification || !lastOrphanNotification) return
    const text = lastOrphanNotification.text.trim()
    setTaskGroups((prev) => {
      const idx = findLastIndex(prev, (g) => g.status === 'running')
      if (idx < 0) return prev
      const group = prev[idx]
      const finalText = text || '_Task completed_'
      const completedGroup: TaskGroup = { ...group, finalText, status: 'done' }
      setTimeout(() => persistTaskGroupToHistory(completedGroup), 0)
      return prev.filter((g) => g.id !== group.id)
    })
    setAwaitingNotification(false)
    setBackgroundActivity('')
    clearLastOrphanNotification()
  }, [awaitingNotification, lastOrphanNotification, clearLastOrphanNotification, persistTaskGroupToHistory])

  // Safety net: a fire-and-forget spawn whose completion notification never
  // arrives (lost/mis-routed) would otherwise leave "Task running" stuck
  // forever. After a grace period with no resolution, finalize any running
  // groups so the UI never lies about a task still running.
  useEffect(() => {
    if (!awaitingNotification) return
    const timer = setTimeout(() => {
      setTaskGroups((prev) => {
        if (!prev.some((g) => g.status === 'running')) return prev
        for (const group of prev) {
          if (group.status !== 'running') continue
          const completedGroup: TaskGroup = {
            ...group,
            finalText: group.finalText || '_Task finished — no result notification received._',
            status: 'done',
          }
          setTimeout(() => persistTaskGroupToHistory(completedGroup), 0)
        }
        return prev.filter((g) => g.status !== 'running')
      })
      setAwaitingNotification(false)
      setBackgroundActivity('')
    }, NOTIFICATION_TIMEOUT_MS)
    return () => clearTimeout(timer)
  }, [awaitingNotification, persistTaskGroupToHistory])

  // Clean up on unmount
  useEffect(() => {
    return () => {
      stopPolling()
      stopSpeaking()
      if (rafHandleRef.current != null) {
        cancelAnimationFrame(rafHandleRef.current)
        rafHandleRef.current = null
      }
    }
  }, [stopPolling, stopSpeaking])

  // Clear task groups when switching sessions
  useEffect(() => {
    setTaskGroups([])
    setAwaitingNotification(false)
    setBackgroundActivity('')
  }, [activeId])

  // Auto-send when the dashboard assigns a task to master and switches to chat
  useEffect(() => {
    if (pendingChatInput && !isStreaming) {
      sendMessage(pendingChatInput)
      clearPendingChatInput()
    }
  // sendMessage identity is stable enough for this use; overrideText bypasses stale input
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingChatInput])

  const sendMessage = useCallback(async (rawText: string, files: File[] = []) => {
    const text = rawText.trim()
    const displayText = text
    if (!text && files.length === 0) return
    if (isStreaming) return

    // Two-phase: upload staged files first, then send the message carrying only
    // their IDs. The server resolves IDs (owner-scoped) and injects image_read
    // markers + inline text — the chat request never carries file bytes.
    let attachmentIds: string[] = []
    let attachments: Attachment[] | undefined
    if (files.length > 0) {
      try {
        const { files: uploaded, errors } = await uploadFiles(files)
        attachmentIds = uploaded.map((u) => u.id)
        attachments = uploaded.map((u) => ({
          id: u.id, name: u.name, mime: u.mime, size: u.size, width: u.width, height: u.height,
        }))
        if (errors.length) {
          appendMessage('assistant', `_Some files were rejected: ${errors.map((e) => `${e.name}: ${e.error}`).join('; ')}_`)
        }
      } catch (e) {
        appendMessage('user', rawText || '(attachments)')
        appendMessage('assistant', `_Failed to upload attachments: ${(e as Error).message}_`)
        return
      }
    }

    // ── Slash command interception ──────────────────────────────────────
    if (text.startsWith('/')) {
      const parts = text.split(/\s+/)
      const cmd = parts[0].toLowerCase()
      const args = parts.slice(1).join(' ')

      // Client-side commands (no API call needed)
      if (cmd === '/help') {
        appendMessage('user', text)
        appendMessage('assistant', _helpText())
        return
      }
      if (cmd === '/clear') {
        appendMessage('user', text)
        useSessionStore.getState().newSession()
        return
      }
      if (cmd === '/exit' || cmd === '/quit') {
        appendMessage('user', text)
        appendMessage('assistant', 'Exit is a no-op in the web UI. Close the tab or navigate away.')
        return
      }

      // Server-side commands (call backend)
      appendMessage('user', text)
      try {
        const { response } = await handleCommand(cmd, args)
        appendMessage('assistant', response)
      } catch (e) {
        appendMessage('assistant', `_Error handling command: ${(e as Error).message}_`)
      }
      return
    }
    // ── End slash command interception ──────────────────────────────────

    // Cancel any in-progress background notification polling
    stopPolling()

    // Capture history BEFORE appending the new user message
    const apiHistory = useSessionStore.getState().history

    appendMessage('user', displayText, undefined, attachments)
    const sessionId = useSessionStore.getState().activeId
    setLaunchTick((t) => t + 1) // fire the send-button launch (spec §4)
    setStreamingParts([])
    setIsStreaming(true)
    setBackgroundActivity('')

    const controller = new AbortController()
    abortRef.current = controller

    // Track assembled text locally — avoids React ref/useEffect timing races
    let assembledText = ''
    // Track whether any sub-agents were spawned — if so, poll for background results
    let hadSpawnAgent = false
    // Did master resolve the delegation inline (wait/read) in this same turn?
    let hadInlineResult = false

    try {
      for await (const event of streamTask(text, apiHistory, controller.signal, sessionId, attachmentIds)) {
        if (event.type === 'thinking') {
          enqueueStreamEvent({ kind: 'thinking_delta', text: event.text })
        } else if (event.type === 'text') {
          assembledText += event.text
          enqueueStreamEvent({ kind: 'text_delta', text: event.text })
        } else if (event.type === 'tool_start') {
          if (event.name === 'spawn_agent') hadSpawnAgent = true
          // If master waits for / reads the child's result in THIS turn, the
          // result is already in its response — there is no separate background
          // notification coming, so we must not arm awaitingNotification (which
          // would leave "Task running" stuck forever).
          if (
            event.name === 'wait_for_agent' ||
            event.name === 'wait_for_agents' ||
            event.name === 'read_task_result' ||
            event.name === 'execute_dag'
          ) {
            hadInlineResult = true
          }
          enqueueStreamEvent({
            kind: 'tool_start',
            id: crypto.randomUUID(),
            name: event.name,
            input: event.input,
          })
        } else if (event.type === 'tool_done') {
          enqueueStreamEvent({
            kind: 'tool_done',
            name: event.name,
            result: event.result,
            isError: event.is_error,
          })
        } else if (event.type === 'usage_stats') {
          setUsage(event)
        } else if (event.type === 'compact') {
          enqueueStreamEvent({
            kind: 'compact',
            tokensBefore: event.tokens_before,
            tokensAfter: event.tokens_after,
            reason: event.reason,
          })
        } else if (event.type === 'error') {
          // Backend emits `{type: "error", error: "..."}` when
          // master_agent.handle_task_stream raises (e.g. budget cap,
          // adapter chain exhausted, internal crash). Without this
          // branch, the event is dropped and the UI looks like master
          // "suddenly stops". Render the error as visible text so the
          // user knows what happened instead of seeing silence.
          const errText = `\n\n_⚠ master error: ${(event as { error?: string }).error || 'unknown'}_`
          setStreamingParts((prev) => [...prev, { kind: 'text', text: errText }])
          assembledText = (assembledText + errText)
        }
      }

      // Drain any events still buffered before marking thinking-parts done,
      // so the close-out write doesn't get clobbered by a later RAF flush.
      if (rafHandleRef.current != null) {
        cancelAnimationFrame(rafHandleRef.current)
        rafHandleRef.current = null
      }
      flushPendingEvents()

      // Mark any open thinking parts as done
      setStreamingParts((prev) =>
        prev.map((p) => (p.kind === 'thinking' && !p.done ? { ...p, done: true } : p)),
      )

      // Capture the full parts array before resetting
      const finalParts = streamingPartsRef.current

      if (hadSpawnAgent && !hadInlineResult) {
        // Genuine fire-and-forget spawn: master ended its turn without waiting,
        // so the child completes later → a background notification will resolve
        // this. Render the trace as a live task group meanwhile.
        setTaskGroups((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            parts: finalParts,
            finalText: assembledText,
            status: 'running',
          },
        ])
        setAwaitingNotification(true)
      } else if (hadSpawnAgent && hadInlineResult) {
        // master spawned AND waited/read the result in this turn — it's already
        // in `assembledText`. Show the delegation trace as a COMPLETED task group
        // and persist it; do NOT wait for a notification that will never come.
        const doneGroup: TaskGroup = {
          id: crypto.randomUUID(),
          parts: finalParts,
          finalText: assembledText,
          status: 'done',
        }
        setTaskGroups((prev) => [...prev, doneGroup])
        setTimeout(() => persistTaskGroupToHistory(doneGroup), 0)
      } else {
        // Save both the structured parts AND the final assembled text into history.
        // On page refresh, MessageBubble will render the parts as the execution trace.
        const partsToSave = finalParts.length > 0 ? finalParts : undefined
        appendMessage('assistant', assembledText, partsToSave)
        // Auto-speak response if voice auto-speak is enabled
        if (assembledText) {
          const { voiceEnabled: ve, voiceAutoSpeak: vas } = useAppStore.getState()
          if (ve && vas) {
            speakText(assembledText)
          }
        }
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        // ServerRestartError → backend bounced mid-stream and is already back
        // up (useStream waited for /health). Show a recovery hint, not a raw
        // network error. Any partial assistant text is preserved before the
        // hint so the user can still see what arrived before the restart.
        const errText = e instanceof ServerRestartError
          ? `\n\n_Server restarted — connection lost. Reconnected; please retry your message._`
          : `\n\n_Error: ${(e as Error).message}_`
        setStreamingParts((prev) => [...prev, { kind: 'text', text: errText }])
        const full = (assembledText + errText).trim()
        if (full) appendMessage('assistant', full)
      }
    } finally {
      // Drop any pending buffered events and cancel the scheduled flush —
      // the streaming UI is about to be reset.
      if (rafHandleRef.current != null) {
        cancelAnimationFrame(rafHandleRef.current)
        rafHandleRef.current = null
      }
      pendingEventsRef.current = []
      setIsStreaming(false)
      setStreamingParts([])
      abortRef.current = null
      chatInputRef.current?.focus()
    }
  }, [isStreaming, appendMessage, speakText, stopPolling, enqueueStreamEvent, flushPendingEvents])

  function handleStop() {
    abortRef.current?.abort()
  }

  return (
    <div className="flex flex-col h-full bg-zinc-950" style={{ minHeight: 0 }}>
      {/* Message list */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className={`chat-history flex-1 overflow-y-auto px-4 py-4 space-y-3 ${noAnimate ? 'no-animate' : ''}`}
        style={{ minHeight: 0 }}
      >
        {history.length === 0 && !isStreaming && (
          <div
            className={`flex flex-col items-center justify-center h-full gap-3 select-none ${
              welcomeReady ? 'welcome-ready' : 'splash-hidden'
            }`}
          >
            <div
              className="welcome-name text-4xl font-bold tracking-[0.2em] font-mono"
              style={{ color: 'var(--color-text-primary, #FFB633)' }}
            >
              YAPOC
            </div>
            <div className="text-zinc-600 text-sm">Send a message to get started</div>
          </div>
        )}

        {history.map((msg, i) => (
          <div key={i} className="group relative">
            {msg.role === 'assistant' && msg.parts && msg.parts.length > 0 ? (
              // Render the saved step chain exactly as it streamed (no collapse
              // into a single block, no duplicated final-text blob).
              <PartsChain parts={msg.parts} content={msg.content} masterModel={masterModel} />
            ) : (
              <MessageBubble
                role={msg.role}
                content={msg.content}
                attachments={msg.attachments}
                agentName={msg.role === 'assistant' ? 'master' : undefined}
                agentModel={msg.role === 'assistant' ? masterModel : undefined}
                onDelete={msg.role === 'user' ? () => useSessionStore.getState().deleteMessage(i) : undefined}
              />
            )}
            {msg.role === 'assistant' && voiceEnabled && (
              <button
                onClick={() => {
                  if (isSpeaking) {
                    stopSpeaking()
                  } else {
                    speakText(msg.content)
                  }
                }}
                className={`absolute -right-2 top-1 opacity-0 group-hover:opacity-100 transition-opacity px-1.5 py-0.5 rounded text-xs ${
                  isSpeaking ? 'bg-zinc-600 text-zinc-200' : 'bg-zinc-700 text-zinc-400 hover:bg-zinc-600 hover:text-zinc-200'
                }`}
                title={isSpeaking ? 'Stop playback' : 'Read aloud'}
              >
                {isSpeaking ? '⏹' : '🔊'}
              </button>
            )}
          </div>
        ))}

        {/* Completed task groups */}
        {taskGroups.map((group) => (
          <TaskGroupBubble key={group.id} group={group} masterModel={masterModel} />
        ))}

        {/* Streaming assistant response */}
        {isStreaming && streamingParts.length === 0 && (
          <div className="flex items-center gap-2 text-zinc-500 text-sm pl-1">
            <TypingIndicator />
            <span>Thinking…</span>
          </div>
        )}

        {isStreaming && streamingParts.length > 0 && (
          <PartsChain parts={streamingParts} masterModel={masterModel} streaming />
        )}

        {awaitingNotification && (
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-zinc-500 text-xs pl-1 py-1">
            <span className="animate-spin inline-block">⟳</span>
            <span>
              Agents working in background
              {wsConnected ? ' — listening for results via WebSocket' : ' — connecting…'}
            </span>
            <button
              onClick={stopPolling}
              className="ml-auto text-zinc-600 hover:text-zinc-400 text-xs"
            >
              dismiss
            </button>
            </div>
            {backgroundActivity && (
              <div className="pl-6 text-[11px] text-zinc-400 font-mono">
                {backgroundActivity}
              </div>
            )}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="px-4 py-3 border-t border-zinc-700 bg-zinc-900 flex-shrink-0">
        {showVoiceSettings && (
          <div className="mb-3 rounded-lg border border-zinc-700 bg-zinc-900">
            <VoiceSettings />
          </div>
        )}
        {voiceError && (
          <div className="mb-2 text-xs text-red-400">{voiceError}</div>
        )}
        <div className="flex flex-wrap gap-2 items-end">
          <ChatInput
            ref={chatInputRef}
            onSubmit={(text, files) => sendMessage(text, files)}
            disabled={isStreaming}
          />
          {sttSupported && voiceEnabled && (
            <button
              onClick={() => {
                if (sttListening) {
                  sttStop()
                } else {
                  sttStart()
                }
              }}
              className={`px-3 py-2 rounded-lg text-sm flex-shrink-0 ${
                sttListening
                  ? 'bg-red-700 text-white hover:bg-red-600 animate-pulse'
                  : 'bg-zinc-700 text-zinc-300 hover:bg-zinc-600'
              }`}
              title={sttListening ? 'Stop listening' : 'Start listening'}
            >
              🎤
            </button>
          )}
          <button
            onClick={() => setShowVoiceSettings((v) => !v)}
            className={`px-3 py-2 rounded-lg text-sm flex-shrink-0 ${
              showVoiceSettings
                ? 'bg-zinc-600 text-zinc-100'
                : 'bg-zinc-700 text-zinc-300 hover:bg-zinc-600'
            }`}
            title={showVoiceSettings ? 'Hide voice settings' : 'Show voice settings'}
          >
            ⚙ Voice
          </button>
          <SendButton
            isStreaming={isStreaming}
            launchTick={launchTick}
            onSend={() => chatInputRef.current?.submit()}
            onStop={handleStop}
          />
        </div>
        {usage && (
          <CostBar
            model={masterModel || DEFAULT_MODEL}
            inputTokens={usage.input_tokens}
            outputTokens={usage.output_tokens}
            tokensPerSecond={usage.tokens_per_second}
            contextWindow={usage.context_window}
          />
        )}
      </div>
    </div>
  )
}

function _helpText(): string {
  return (
    '**Available commands:**\n\n' +
    '| Command | Description |\n' +
    '|---------|-------------|\n' +
    '| `/help` | Show this help message |\n' +
    '| `/clear` | Clear conversation and start a new session |\n' +
    '| `/ping` | Ping the server and show response time |\n' +
    '| `/status` | Show server & agent status |\n' +
    '| `/agents` | List all agents |\n' +
    '| `/model` | Show current adapter/model |\n' +
    '| `/cost` | Show session cost breakdown |\n' +
    '| `/sessions` | List recent sessions |\n' +
    '| `/continue` | Resume the latest session |\n' +
    '| `/resume <id>` | Resume a specific session |\n' +
    '| `/export <filename>` | Export conversation to file |\n' +
    '| `/doctor` | Run doctor health check |\n' +
    '| `/start` | Start the backend server |\n' +
    '| `/stop` | Stop the backend server |\n' +
    '| `/restart` | Restart the backend server |\n' +
    '| `/exit` | No-op in web UI |'
  )
}

function formatSessionActivity(envelope: SessionEventEnvelope): string {
  const event = envelope.event
  const agent = event.agent || 'agent'
  if (event.type === 'tool_call') {
    const tool = String(event.name ?? 'tool')
    return `[${agent}] tool start: ${tool}`
  }
  if (event.type === 'tool_result') {
    const tool = String(event.name ?? 'tool')
    const isError = Boolean(event.is_error)
    return `[${agent}] tool ${tool}: ${isError ? 'error' : 'done'}`
  }
  if (event.type === 'thinking_delta' || event.type === 'message_delta') {
    return `[${agent}] generating...`
  }
  if (event.type === 'notification_result') {
    return `[${agent}] sent final background result`
  }
  return ''
}
