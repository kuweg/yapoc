import { useRef, useEffect, useState, useCallback } from 'react'
import { streamTask } from '../hooks/useStream'
import { useSessionStore } from '../store/session'
import { useWsStore } from '../store/wsStore'
import { useAppStore } from '../store/appStore'
import { useSpeechRecognition, useSpeechSynthesis } from '../hooks/useSpeech'
import { handleCommand, synthesizeSpeech } from '../api/client'
import { MessageBubble } from './MessageBubble'
import { ToolCallBlock } from './ToolCallBlock'
import { ThinkingBlock } from './ThinkingBlock'
import { CostBar } from './CostBar'
import { VoiceSettings } from './VoiceSettings'
import { ChatInput, type ChatInputHandle } from './ChatInput'
import type { UsageEvent } from '../api/types'
import type { SessionEventEnvelope } from '../store/wsStore'

type TextPart = { kind: 'text'; text: string }
type ThinkingPart = { kind: 'thinking'; id: string; text: string; done: boolean }
type ToolCallPart = {
  kind: 'tool'
  id: string
  name: string
  input: Record<string, unknown>
  result?: string
  isError?: boolean
  done: boolean
}
type Part = TextPart | ThinkingPart | ToolCallPart

// Buffered stream events, flushed once per animation frame to cap streaming-
// induced re-renders at ~60Hz regardless of delta rate.
type PendingStreamEvent =
  | { kind: 'thinking_delta'; text: string }
  | { kind: 'text_delta'; text: string }
  | { kind: 'tool_start'; id: string; name: string; input: Record<string, unknown> }
  | { kind: 'tool_done'; name: string; result: string; isError: boolean }

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
        .find(({ p }) => p.kind === 'tool' && !(p as ToolCallPart).done && p.name === event.name)
      if (target) {
        const updated = [...parts]
        updated[target.i] = {
          ...(updated[target.i] as ToolCallPart),
          result: event.result,
          isError: event.isError,
          done: true,
        }
        parts = updated
      }
    }
  }
  return parts
}

// Default model for cost estimation — update when backend exposes model in usage events
const DEFAULT_MODEL = 'claude-sonnet-4-6'

export function ChatPanel() {
  const { activeId, history, appendMessage, pendingChatInput, clearPendingChatInput } = useSessionStore()
  const [streamingParts, setStreamingParts] = useState<Part[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [usage, setUsage] = useState<UsageEvent | null>(null)
  const [awaitingNotification, setAwaitingNotification] = useState(false)
  const [backgroundActivity, setBackgroundActivity] = useState<string>('')
  const [showVoiceSettings, setShowVoiceSettings] = useState(false)
  const [voiceError, setVoiceError] = useState<string | null>(null)
  const [backendSpeaking, setBackendSpeaking] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const backendAudioRef = useRef<HTMLAudioElement | null>(null)
  const backendAudioUrlRef = useRef<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickToBottomRef = useRef(true)
  const chatInputRef = useRef<ChatInputHandle>(null)
  // Stream-event coalescing — one setState per animation frame regardless of
  // how many SSE deltas arrive in that frame.
  const pendingEventsRef = useRef<PendingStreamEvent[]>([])
  const rafHandleRef = useRef<number | null>(null)

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

  // When the user sends a new message, snap to bottom regardless
  useEffect(() => {
    if (isStreaming) stickToBottomRef.current = true
  }, [isStreaming])

  // WebSocket notification: when a background task completes, show result in chat
  useEffect(() => {
    if (!awaitingNotification || !lastCompletedTask || !activeId) return
    if (lastCompletedTask.session_id && lastCompletedTask.session_id !== activeId) return
    const result = lastCompletedTask.result?.trim()
    if (result) {
      appendMessage('assistant', result)
    } else if (lastCompletedTask.error) {
      appendMessage('assistant', `_Background task error: ${lastCompletedTask.error}_`)
    }
    setAwaitingNotification(false)
    setBackgroundActivity('')
    // Clear the lastCompletedTask so it doesn't re-trigger
    clearLastCompletedTask()
  }, [lastCompletedTask, awaitingNotification, activeId, appendMessage, clearLastCompletedTask])

  useEffect(() => {
    if (!awaitingNotification || !lastSessionEvent || !activeId) return
    if (lastSessionEvent.session_id !== activeId) return
    const eventType = String(lastSessionEvent.event.type ?? '')
    if (eventType === 'notification_result') {
      const text = String(lastSessionEvent.event.text ?? '').trim()
      if (text) {
        appendMessage('assistant', text)
      }
      setAwaitingNotification(false)
      setBackgroundActivity('')
      return
    }
    const line = formatSessionActivity(lastSessionEvent)
    if (line) setBackgroundActivity(line)
  }, [awaitingNotification, lastSessionEvent, activeId, appendMessage])

  // Orphan-notification fallback: when the backend couldn't route master's
  // notification result to a specific session (session_id lost upstream),
  // it broadcasts a top-level notification_result event. If we're actively
  // awaiting a sub-agent chain to finish, surface the result in this chat
  // rather than letting it die silently.
  useEffect(() => {
    if (!awaitingNotification || !lastOrphanNotification) return
    const text = lastOrphanNotification.text.trim()
    if (text) appendMessage('assistant', text)
    setAwaitingNotification(false)
    setBackgroundActivity('')
    clearLastOrphanNotification()
  }, [awaitingNotification, lastOrphanNotification, appendMessage, clearLastOrphanNotification])

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

  // Auto-send when the dashboard assigns a task to master and switches to chat
  useEffect(() => {
    if (pendingChatInput && !isStreaming) {
      sendMessage(pendingChatInput)
      clearPendingChatInput()
    }
  // sendMessage identity is stable enough for this use; overrideText bypasses stale input
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingChatInput])

  const sendMessage = useCallback(async (rawText: string) => {
    const text = rawText.trim()
    if (!text || isStreaming) return

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

    appendMessage('user', text)
    const sessionId = useSessionStore.getState().activeId
    setStreamingParts([])
    setIsStreaming(true)
    setBackgroundActivity('')

    const controller = new AbortController()
    abortRef.current = controller

    // Track assembled text locally — avoids React ref/useEffect timing races
    let assembledText = ''
    // Track whether any sub-agents were spawned — if so, poll for background results
    let hadSpawnAgent = false

    try {
      for await (const event of streamTask(text, apiHistory, controller.signal, sessionId)) {
        if (event.type === 'thinking') {
          enqueueStreamEvent({ kind: 'thinking_delta', text: event.text })
        } else if (event.type === 'text') {
          assembledText += event.text
          enqueueStreamEvent({ kind: 'text_delta', text: event.text })
        } else if (event.type === 'tool_start') {
          if (event.name === 'spawn_agent') hadSpawnAgent = true
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
      if (assembledText) appendMessage('assistant', assembledText)

      // Auto-speak response if voice auto-speak is enabled
      if (assembledText) {
        const { voiceEnabled: ve, voiceAutoSpeak: vas } = useAppStore.getState()
        if (ve && vas) {
          speakText(assembledText)
        }
      }

      // If sub-agents were spawned, listen for background results via WebSocket
      if (hadSpawnAgent) {
        setAwaitingNotification(true)
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        const errText = `\n\n_Error: ${(e as Error).message}_`
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
        className="flex-1 overflow-y-auto px-4 py-4 space-y-3"
        style={{ minHeight: 0 }}
      >
        {history.length === 0 && !isStreaming && (
          <div className="flex items-center justify-center h-full text-zinc-600 text-sm">
            Send a message to get started
          </div>
        )}

        {history.map((msg, i) => (
          <div key={i} className="group relative">
            <MessageBubble role={msg.role} content={msg.content} agentName={msg.role === 'assistant' ? 'master' : undefined} />
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

        {/* Streaming assistant response */}
        {isStreaming && streamingParts.length === 0 && (
          <div className="flex items-center gap-2 text-zinc-500 text-sm pl-1">
            <span className="animate-pulse">●</span>
            <span>Thinking…</span>
          </div>
        )}

        {isStreaming && streamingParts.length > 0 && (
          <div className="space-y-1">
            {streamingParts.map((part, i) =>
              part.kind === 'text' ? (
                <MessageBubble key={`t-${i}`} role="assistant" content={part.text} agentName="master" />
              ) : part.kind === 'thinking' ? (
                <ThinkingBlock key={part.id} text={part.text} done={part.done} />
              ) : (
                <ToolCallBlock
                  key={part.id}
                  id={part.id}
                  name={part.name}
                  input={part.input}
                  result={part.result}
                  isError={part.isError}
                  done={part.done}
                />
              ),
            )}
          </div>
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
            onSubmit={sendMessage}
            disabled={isStreaming}
          />
          {isStreaming ? (
            <button
              onClick={handleStop}
              className="px-4 py-2 rounded-lg bg-red-700 text-white text-sm hover:bg-red-600 flex-shrink-0"
            >
              Stop
            </button>
          ) : (
            <>
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
              <button
                onClick={() => chatInputRef.current?.submit()}
                className="px-4 py-2 rounded-lg bg-[#FFB633] text-[#0a0a0a] text-sm font-semibold hover:bg-[#ffc84d] disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0"
              >
                Send ↵
              </button>
            </>
          )}
        </div>
        {usage && (
          <CostBar
            model={DEFAULT_MODEL}
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
