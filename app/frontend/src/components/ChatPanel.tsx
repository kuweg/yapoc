import { useRef, useEffect, useState, useCallback } from 'react'
import { streamTask } from '../hooks/useStream'
import { useSessionStore } from '../store/session'
import { useWsStore } from '../store/wsStore'
import { useAppStore } from '../store/appStore'
import { useSpeechRecognition, useSpeechSynthesis } from '../hooks/useSpeech'
import { synthesizeSpeech } from '../api/client'
import { MessageBubble } from './MessageBubble'
import { ToolCallBlock } from './ToolCallBlock'
import { ThinkingBlock } from './ThinkingBlock'
import { CostBar } from './CostBar'
import { VoiceSettings } from './VoiceSettings'
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

// Default model for cost estimation — update when backend exposes model in usage events
const DEFAULT_MODEL = 'claude-sonnet-4-6'

export function ChatPanel() {
  const { activeId, history, appendMessage, pendingChatInput, clearPendingChatInput } = useSessionStore()
  const [input, setInput] = useState('')
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
  const textareaRef = useRef<HTMLTextAreaElement>(null)

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
        setInput(transcript)
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

  // Auto-scroll on new content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history, streamingParts])

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

  const sendMessage = useCallback(async (overrideText?: string) => {
    const text = (overrideText != null ? overrideText : input).trim()
    if (!text || isStreaming) return

    // Cancel any in-progress background notification polling
    stopPolling()

    // Capture history BEFORE appending the new user message
    const apiHistory = useSessionStore.getState().history

    appendMessage('user', text)
    const sessionId = useSessionStore.getState().activeId
    if (overrideText == null) setInput('')
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
          const chunk = event.text
          setStreamingParts((prev) => {
            const last = prev[prev.length - 1]
            if (last && last.kind === 'thinking' && !last.done) {
              return [...prev.slice(0, -1), { ...last, text: last.text + chunk }]
            }
            return [...prev, { kind: 'thinking', id: crypto.randomUUID(), text: chunk, done: false }]
          })
        } else if (event.type === 'text') {
          assembledText += event.text
          const chunk = event.text
          setStreamingParts((prev) => {
            const last = prev[prev.length - 1]
            if (last && last.kind === 'text') {
              return [...prev.slice(0, -1), { kind: 'text', text: last.text + chunk }]
            }
            return [...prev, { kind: 'text', text: chunk }]
          })
        } else if (event.type === 'tool_start') {
          if (event.name === 'spawn_agent') hadSpawnAgent = true
          setStreamingParts((prev) => [
            ...prev,
            {
              kind: 'tool',
              id: crypto.randomUUID(),
              name: event.name,
              input: event.input,
              done: false,
            },
          ])
        } else if (event.type === 'tool_done') {
          const toolName = event.name
          const result = event.result
          const isError = event.is_error
          setStreamingParts((prev) => {
            const idx = prev
              .map((p, i) => ({ p, i }))
              .reverse()
              .find(({ p }) => p.kind === 'tool' && !(p as ToolCallPart).done && p.name === toolName)
            if (!idx) return prev
            const updated = [...prev]
            updated[idx.i] = { ...(updated[idx.i] as ToolCallPart), result, isError, done: true }
            return updated
          })
        } else if (event.type === 'usage_stats') {
          setUsage(event)
        }
      }

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
      setIsStreaming(false)
      setStreamingParts([])
      abortRef.current = null
      textareaRef.current?.focus()
    }
  }, [input, isStreaming, appendMessage, speakText, stopPolling])

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  function handleStop() {
    abortRef.current?.abort()
  }

  return (
    <div className="flex flex-col h-full bg-zinc-950">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
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
        <div className="flex gap-2 items-end">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message YAPOC… (Enter to send, Shift+Enter for newline)"
            disabled={isStreaming}
            rows={3}
            className="flex-1 resize-none rounded-lg bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-500 disabled:opacity-50"
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
                onClick={() => sendMessage()}
                disabled={!input.trim()}
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
