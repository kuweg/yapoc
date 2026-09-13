import {ProjectContext} from '../projects/ProjectContext'
import {projectSubmission,useProjects} from '../projects/store'
import type { StructuredTaskResult } from '../api/types'
import { StudioWelcome } from '../studio/StudioWelcome'
import { createLiveUsage, type LiveUsage } from './liveUsage'
import { NoteContextBar } from '../notes/NoteContextBar'
import { Mic, Settings2 } from 'lucide-react'
import { useRef, useEffect, useState, useCallback, useMemo } from 'react'
import { streamTask } from '../hooks/useStream'
import { useSessionStore } from '../store/session'
import { useWsStore, type BackgroundTask } from '../store/wsStore'
import { ArtifactStrip } from '../artifacts/ArtifactStrip'
import { useSessionArtifacts, taskIdFromCompletionId } from '../artifacts/useSessionArtifacts'
import { useAppStore } from '../store/appStore'
import { useSpeechRecognition, useSpeechSynthesis } from '../hooks/useSpeech'
import { useBackendSTT } from '../hooks/useBackendSTT'
import { handleCommand, synthesizeSpeech, getAgents, uploadFiles } from '../api/client'
import { MessageBubble } from './MessageBubble'
import { TaskCompletionCard } from './TaskCompletionCard'
import { ToolCallBlock } from './ToolCallBlock'
import { ThinkingBlock } from './ThinkingBlock'
import { GroupedToolCallBlock } from './GroupedToolCallBlock'
import { CompactionMarker } from './ContextGauge'
import { groupParts } from './groupParts'
import ChartBlock from './ChartBlock'
import MermaidBlock from './MermaidBlock'
import CalendarBlock from './CalendarBlock'
import { TaskGroupBubble, type TaskGroup } from './TaskGroupBubble'
import { SubAgentActivity } from './SubAgentActivity'
import { useLiveAgentParts } from './LiveAgentTranscript'
import { CostBar } from './CostBar'
import { VoiceSettings } from './VoiceSettings'
import { ChatInput, type ChatInputHandle } from './ChatInput'
import { ChatSearchBar } from './ChatSearchBar'
import { TurnStatusBar } from './TurnStatusBar'
import { commandHelpTable } from '../lib/chatCommands'
import { startAsciiWave, ASCII_WAVE_FRAMES } from './spinner'
import type { TaskPart, Attachment } from '../api/types'
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
  | { kind: 'message_boundary' }

/** ES2023 findLastIndex polyfill */
function findLastIndex<T>(arr: T[], predicate: (item: T) => boolean): number {
  for (let i = arr.length - 1; i >= 0; i--) {
    if (predicate(arr[i])) return i
  }
  return -1
}

/**
 * Close out any open (still "running") thinking or tool parts so an interrupt
 * (page reload mid-stream, connection loss) doesn't leave a spinner forever.
 * Mirrors the end-of-turn idiom; hoisted to module scope so the in-stream
 * close-out AND the pagehide/abort persistence handler share one definition.
 */
function closeOpenParts(parts: Part[]): Part[] {
  return parts.map((p) =>
    (p.kind === 'thinking' || p.kind === 'tool') && !p.done ? { ...p, done: true } : p,
  )
}

// Note appended to a partial assistant reply that was cut off mid-stream by a
// page reload / navigation / connection loss. Kept as plain italic markdown so
// it renders through both the ReactMarkdown bubbles and is immune to store
// schema changes.
const INTERRUPTED_MARKER = '\n\n_[interrupted — this reply was cut off mid-stream before it finished. It is not master\'s final answer; send another message or retry to continue.]_'

function applyPendingEvents(prev: Part[], events: PendingStreamEvent[]): Part[] {
  let parts = prev
  for (const event of events) {
    if (event.kind === 'message_boundary') {
      parts = [...parts.map((p): Part => p.kind === 'thinking' ? { ...p, done: true } : p), { kind: 'text', text: '' }]
    } else if (event.kind === 'thinking_delta') {
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
        if (event.name === 'render_mermaid' && !event.isError) {
          // render_mermaid returns a validated JSON payload. Replace its tool
          // card with a diagram part so the source is never displayed as a
          // raw tool result in the chat.
          try {
            const parsed: unknown = JSON.parse(event.result)
            if (
              typeof parsed === 'object' &&
              parsed !== null &&
              !Array.isArray(parsed) &&
              (parsed as Record<string, unknown>).type === 'mermaid' &&
              typeof (parsed as Record<string, unknown>).source === 'string'
            ) {
              const updated = [...parts]
              updated[target.i] = {
                kind: 'mermaid',
                source: (parsed as Record<string, unknown>).source as string,
              }
              parts = updated
              continue
            }
          } catch {
            // fall through to the normal tool result so failures remain visible
          }
        }
        if (event.name === 'render_chart' && !event.isError) {
          // A successful render_chart resolves to an interactive ECharts option
          // payload (normalized compact JSON). Try to parse it and, on success,
          // REPLACE the tool card with a chart part in the same slot so the
          // chart renders instantly (no `done` field) instead of a collapsed
          // tool card. Any parse failure falls back to a normal (error) tool
          // card below so errors stay visible.
          try {
            const parsed: unknown = JSON.parse(event.result)
            const isObj = typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
            if (isObj) {
              const updated = [...parts]
              updated[target.i] = {
                kind: 'chart',
                option: parsed as Record<string, unknown>,
              }
              parts = updated
              continue
            }
          } catch {
            // fall through to the tool-done render below
          }
        }
        if (event.name === 'render_calendar' && !event.isError) {
          // A successful render_calendar resolves to a validated events payload.
          // Replace the tool card with a calendar part so the events render as
          // a block instead of a collapsed tool card.
          try {
            const parsed: unknown = JSON.parse(event.result)
            if (
              typeof parsed === 'object' &&
              parsed !== null &&
              !Array.isArray(parsed) &&
              (parsed as Record<string, unknown>).type === 'calendar' &&
              Array.isArray((parsed as Record<string, unknown>).events)
            ) {
              const updated = [...parts]
              updated[target.i] = {
                kind: 'calendar',
                events: (parsed as Record<string, unknown>).events as Array<{
                  summary: string
                  start: string
                  end: string
                  location?: string
                  description?: string
                }>,
                weekStart:
                  typeof (parsed as Record<string, unknown>).week_start === 'string'
                    ? ((parsed as Record<string, unknown>).week_start as string)
                    : undefined,
              }
              parts = updated
              continue
            }
          } catch {
            // fall through to the tool-done render below
          }
        }
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
        if (part.kind === 'chart') {
          return <ChartBlock key={`chart-${i}`} option={part.option} />
        }
        if (part.kind === 'mermaid') {
          return <MermaidBlock key={`mermaid-${i}`} source={part.source} />
        }
        if (part.kind === 'calendar') {
          return <CalendarBlock key={`calendar-${i}`} events={part.events} weekStart={part.weekStart} />
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
  const [usage, setUsage] = useState<LiveUsage | null>(null)
  const usageRef = useRef<LiveUsage | null>(null)
  useEffect(() => { usageRef.current = usage }, [usage])
  const [masterModel, setMasterModel] = useState<string>('')
  // Artifacts for the whole conversation, fetched once and grouped by task.
  // Keyed on isStreaming so a turn that just produced a chart shows it
  // without the user reloading or opening the Artifacts panel.
  const { byTask: artifactsByTask } = useSessionArtifacts(activeId, isStreaming)
  const [masterAdapter, setMasterAdapter] = useState<string>('')
  const [awaitingNotification, setAwaitingNotification] = useState(false)
  /** Set when master is busy and this turn is waiting for its lock. */
  const [queuedNotice, setQueuedNotice] = useState('')
  const queuedNoticeRef = useRef(false)
  /** Completions already rendered in this session — the store dedupes its own
   *  replay, but this guards the append site itself (React StrictMode invokes
   *  effects twice, and the clear is an async state update). */
  const appendedCompletionsRef = useRef<Set<string>>(new Set())

  // Tasks the backend started without a user turn in this chat. `resume` is the
  // one users hit most (server_restart → RESUME.MD → startup dispatch).
  const backgroundTasks = useWsStore((s) => s.backgroundTasks)
  // Every agent master has spawned this turn. Deliberately NOT filtered by
  // `p.done`: spawn_agent resolves the moment the child is dispatched — it is
  // wait_for_agent that takes the minutes — so filtering on it unmounted the
  // activity card about a second in, before the child had done any work.
  const liveDelegations = useMemo(() => {
    const out: string[] = []
    for (const p of streamingParts) {
      if (p.kind !== 'tool' || p.name !== 'spawn_agent') continue
      const input = (p.input || {}) as Record<string, unknown>
      const name = String(input.agent_name ?? input.name ?? '')
      if (name && !out.includes(name)) out.push(name)
    }
    return out
  }, [streamingParts])

  // Live parts for whatever autonomous turn is running, converted from the
  // per-agent activity channel into the chat's normal Part[] shape. Derived
  // straight from backgroundTasks so the hook runs unconditionally at the top
  // level, before autonomousRunning is computed below.
  const autonomousStartedAt = useMemo(() => {
    // Only follow a turn that belongs to THIS chat. YAPOC restarts itself for
    // its own reasons, and those resumes carry their own session — rendering
    // them here showed master doing unrelated work under the user's request,
    // which reads as "it ignored my instructions after the restart".
    const running = backgroundTasks.find(
      (t) =>
        t.status === 'running' &&
        ['resume', 'goal', 'cron', 'notification', 'continuation'].includes((t.source ?? '').toLowerCase()) &&
        t.session_id === activeId,
    )
    return running?.started_at
  }, [backgroundTasks, activeId])
  const liveParts = useLiveAgentParts('master', autonomousStartedAt, activeId ?? undefined)

  const autonomousRunning = useMemo(
    () =>
      backgroundTasks.filter(
        (t) =>
          t.status === 'running' &&
          ['resume', 'goal', 'cron', 'notification', 'continuation'].includes((t.source ?? '').toLowerCase()) &&
          t.session_id === activeId,
      ),
    [backgroundTasks, activeId],
  )
  // The tool still in flight, and a plain-language phase for the status bar.
  const liveTool = useMemo(() => {
    for (let i = streamingParts.length - 1; i >= 0; i--) {
      const part = streamingParts[i]
      if (part.kind === 'tool' && !part.done) return part.name
    }
    return undefined
  }, [streamingParts])

  // What actually happened last wins. The queued notice is only the phase while
  // nothing has streamed yet: it is set once when the turn goes behind master's
  // lock and never cleared, so preferring it outright left the bar claiming
  // "Queued" while a tool was visibly running.
  const livePhase = useMemo(() => {
    if (liveTool) return 'Running tool'
    const last = streamingParts[streamingParts.length - 1]
    if (last?.kind === 'thinking' && !last.done) return 'Thinking'
    if (last?.kind === 'text') return 'Writing'
    if (streamingParts.length === 0) return queuedNotice || 'Thinking'
    return 'Working'
  }, [queuedNotice, liveTool, streamingParts])

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
  /** When the in-flight turn began, for the status bar's elapsed clock. */
  const [turnStartedAt, setTurnStartedAt] = useState(() => Date.now())
  // Scroll position as state, not just the ref: the jump-to-latest button has
  // to render on it. `unseen` counts what arrived while the user was reading
  // further up, so the button can say how much they have missed.
  const [atBottom, setAtBottom] = useState(true)
  const [unseen, setUnseen] = useState(0)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchIndex, setSearchIndex] = useState(0)
  const abortRef = useRef<AbortController | null>(null)
  const runIdRef = useRef<string | null>(null)
  // Mirror of the live `assembledText` accumulator inside sendMessage, so a
  // synchronous pagehide/abort handler can read "what arrived so far" even
  // though assembledText is a closure `let` scoped to sendMessage.
  const assembledTextRef = useRef('')
  // True once the partial interrupted text has been committed to the store,
  // preventing double-append from (1) pagehide firing and (2) the AbortError
  // catch on the same disconnect.
  const partialCommittedRef = useRef(false)
  // Set by handleStop BEFORE aborting so the AbortError catch can tell an
  // intentional user Stop (do NOT persist a partial as a real answer) apart
  // from a genuine mid-stream disconnect (DO persist).
  const stoppingRef = useRef(false)
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
    setAgentSpeaking,
    setAgentListening,
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

  // Mirror local speaking state up into the shared store so global chrome
  // (e.g. the header speaking sphere) can react to it.
  useEffect(() => {
    setAgentSpeaking(isSpeaking)
  }, [isSpeaking, setAgentSpeaking])

  const { isListening: sttListening, start: sttStart, stop: sttStop, supported: sttSupported } =
    useSpeechRecognition({
      onResult: (transcript) => {
        chatInputRef.current?.setText(transcript)
      },
      onEnd: () => {},
      onError: (err) => setVoiceError(`Speech recognition error: ${err}`),
    })

  // Backend STT (OpenAI Whisper) is preferred whenever it is supported; the
  // browser-native SpeechRecognition path stays as a fallback.
  const {
    isListening: backendSttListening,
    start: backendSttStart,
    stop: backendSttStop,
    supported: backendSttSupported,
  } = useBackendSTT({
    engine: voiceBackendEngine,
    language: 'en-US',
    onResult: (result) => {
      chatInputRef.current?.setText(result.text)
    },
    onError: (err) => setVoiceError(err),
  })

  const useBackendMic = voiceEnabled && backendSttSupported
  const micListening = useBackendMic ? backendSttListening : sttListening
  const micSupported = useBackendMic ? backendSttSupported : sttSupported

  const startListening = useCallback(() => {
    setVoiceError(null)
    if (useBackendMic) {
      backendSttStart()
    } else {
      sttStart()
    }
  }, [useBackendMic, backendSttStart, sttStart])

  const stopListening = useCallback(() => {
    if (backendSttListening) backendSttStop()
    if (sttListening) sttStop()
  }, [backendSttListening, backendSttStop, sttListening, sttStop])

  // Mirror the mic-listening state up into the shared store so the header
  // sphere can show its "listening" third state.
  useEffect(() => {
    setAgentListening(micListening)
  }, [micListening, setAgentListening])
  // Clear the listening flag on unmount.
  useEffect(() => {
    return () => setAgentListening(false)
  }, [setAgentListening])

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
    const nearBottom = distanceFromBottom < 80
    stickToBottomRef.current = nearBottom
    setAtBottom(nearBottom)
    if (nearBottom) setUnseen(0)
  }, [])

  const jumpToLatest = useCallback(() => {
    stickToBottomRef.current = true
    setUnseen(0)
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  // Auto-scroll on new content — only when user is already at (or near) bottom
  useEffect(() => {
    if (!stickToBottomRef.current) return
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history, streamingParts])

  const historyLengthRef = useRef(history.length)
  useEffect(() => {
    const grew = history.length - historyLengthRef.current
    historyLengthRef.current = history.length
    if (grew > 0 && !stickToBottomRef.current) setUnseen((n) => n + grew)
  }, [history.length])

  // Which messages match the search. A hit is outlined in place rather than
  // filtered into a list, so the turns around it still give it context; the
  // haystack includes the parts trace, since a tool result is often what the
  // user half-remembers and is looking for.
  const searchMatches = useMemo(() => {
    const needle = searchQuery.trim().toLowerCase()
    if (!needle) return []
    const out: number[] = []
    history.forEach((msg, i) => {
      const trace = (msg.parts ?? []).map((part) => {
        if (part.kind === 'text' || part.kind === 'thinking') return part.text
        if (part.kind === 'tool') return `${part.name} ${part.result ?? ''}`
        return ''
      })
      if ([msg.content, ...trace].join('\n').toLowerCase().includes(needle)) out.push(i)
    })
    return out
  }, [history, searchQuery])

  useEffect(() => {
    setSearchIndex((prev) => (prev < searchMatches.length ? prev : 0))
  }, [searchMatches.length])

  // Bring the active hit into view. Scrolling here means the user is driving,
  // so release the stick-to-bottom that would otherwise yank them back.
  useEffect(() => {
    if (!searchOpen || searchMatches.length === 0) return
    const target = scrollRef.current?.querySelector(`[data-msg-index="${searchMatches[searchIndex]}"]`)
    if (!target) return
    stickToBottomRef.current = false
    target.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [searchOpen, searchIndex, searchMatches])

  const stepSearch = useCallback((delta: number) => {
    setSearchIndex((prev) => {
      if (searchMatches.length === 0) return 0
      return (prev + delta + searchMatches.length) % searchMatches.length
    })
  }, [searchMatches.length])

  // Ctrl/Cmd+F opens find-in-conversation, Alt+Arrow walks the user's own
  // turns. Both are only claimed while the chat is actually on screen, so the
  // browser's find still works everywhere else in the app.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const visible = scrollRef.current?.offsetParent != null
      if (!visible) return
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f') {
        event.preventDefault()
        setSearchOpen(true)
        return
      }
      if (event.altKey && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) {
        const turns = history.reduce<number[]>((acc, msg, i) => {
          if (msg.role === 'user') acc.push(i)
          return acc
        }, [])
        if (turns.length === 0) return
        event.preventDefault()
        const container = scrollRef.current
        if (!container) return
        // Walk relative to whichever turn is nearest the top of the viewport,
        // so the jump follows what the user is looking at.
        const tops = turns.map((index) => {
          const el = container.querySelector(`[data-msg-index="${index}"]`)
          return el ? (el as HTMLElement).offsetTop : Number.POSITIVE_INFINITY
        })
        const current = tops.findIndex((top) => top >= container.scrollTop - 4)
        const base = current === -1 ? turns.length - 1 : current
        const next = Math.min(turns.length - 1, Math.max(0, base + (event.key === 'ArrowUp' ? -1 : 1)))
        stickToBottomRef.current = false
        container.querySelector(`[data-msg-index="${turns[next]}"]`)?.scrollIntoView({ block: 'start', behavior: 'smooth' })
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [history])

  // Fetch master agent's model name on mount and whenever the WebSocket reconnects
  // (so the label updates after a server restart / model switch)
  useEffect(() => {
    getAgents().then((agents) => {
      const master = agents.find((a) => a.name === 'master')
      if (master?.model) setMasterModel(master.model)
      if (master?.adapter) setMasterAdapter(master.adapter)
    }).catch(() => {
      // ignore — model will just be empty
    })
  }, [wsConnected])

  // A hot swap of master lands as a `model_changed` broadcast. Without this the
  // label above every assistant message would keep naming the old model until
  // the next reconnect, since nothing else refetches it.
  const masterBinding = useWsStore((s) => s.modelBindings.master)
  useEffect(() => {
    if (masterBinding?.model) setMasterModel(masterBinding.model)
    if (masterBinding?.adapter) setMasterAdapter(masterBinding.adapter)
  }, [masterBinding])

  // When the user sends a new message, snap to bottom regardless
  useEffect(() => {
    if (isStreaming) stickToBottomRef.current = true
  }, [isStreaming])

  // Persist a completed task group to history and remove it from taskGroups
  const persistTaskGroupToHistory = useCallback((group: TaskGroup) => {
    const text = group.finalText || '_Task completed_'
    const partsToSave = group.parts.length > 0 ? group.parts : undefined
    // Bind to the session the group started in — the user may have switched
    // chats while the delegation was still running.
    appendMessage('assistant', text, partsToSave, undefined, group.sessionId, undefined, `${group.id}:0`)
    setTaskGroups((prev) => prev.filter((g) => g.id !== group.id))
  }, [appendMessage])

  // WebSocket notification: when a background task completes, persist to history
  useEffect(() => {
    if (!lastCompletedTask || !activeId) return
    // Reconnect snapshots can queue hundreds of completions. Consuming the
    // head synchronously inside this effect exposes the next head and runs
    // the effect again, eventually hitting React's nested-update limit even
    // though the queue is finite. Yield between deliveries so catch-up cannot
    // unmount the app. Cancel stale work on unmount/session changes (including
    // StrictMode's effect replay); the queued task remains available to retry.
    const deliveryTimer = window.setTimeout(() => {
      const result = lastCompletedTask.result?.trim()
      const hasError = Boolean(lastCompletedTask.error)
      const targetSession = lastCompletedTask.session_id
      // Service work remains in Notifications/Tasks. A result with an owner is
      // appended to that owner's conversation even if another chat is open.
      if (!targetSession || !useSessionStore.getState().sessions.some((s) => s.id === targetSession)) {
        clearLastCompletedTask()
        return
      }

      // Same completion delivered twice (live event + a state_sync replay after a
      // reconnect) previously rendered two "Task completed" cards.
      const completionId = lastCompletedTask.task_id
      if (completionId) {
        const owner = useSessionStore.getState().sessions.find((s) => s.id === targetSession)
        if (appendedCompletionsRef.current.has(completionId) || owner?.completionIds?.some((id) => id.startsWith(`${completionId}:`)) || owner?.history.some((m) => m.completionId?.startsWith(`${completionId}:`))) {
          clearLastCompletedTask()
          return
        }
        appendedCompletionsRef.current.add(completionId)
      }

      if (!awaitingNotification || !taskGroups.some((g) => g.status === 'running') || targetSession !== activeId || lastCompletedTask.source === 'resume') {
        const finalText = hasError
          ? `${result ? `${result}\n\n` : ''}Task failed: ${lastCompletedTask.error}`
          : result || '_Task completed_'
        // A completion whose session IS this chat is master talking to the user —
        // a post-restart resume of something they asked for. Render it as an
        // ordinary assistant message, not a "task completed" card: a card reads
        // as a job report and, for longer work, hides master's own words behind a
        // summary the user must wait for.
        //
        // Multi-turn output arrives pre-split on turn boundaries. Append each
        // as its own message so the chat reads as a conversation rather than one
        // concatenated paragraph.
        const blocks = hasError ? [] : (lastCompletedTask.messages ?? []).filter((m) => m && m.trim())
        if (blocks.length > 1) {
          blocks.forEach((m, i) => appendMessage('assistant', m, undefined, undefined, targetSession, i === blocks.length - 1 && lastCompletedTask.structured_result ? { structured_result: lastCompletedTask.structured_result } : undefined, `${completionId}:${i}`))
        } else {
          appendMessage('assistant', finalText, undefined, undefined, targetSession, lastCompletedTask.structured_result ? { structured_result: lastCompletedTask.structured_result } : undefined, `${completionId}:0`)
        }
        if (targetSession === activeId) {
          setAwaitingNotification(false)
          setBackgroundActivity('')
        }
        clearLastCompletedTask()
        return
      }

      // Interactive delegation: only drop a result whose session genuinely isn't
      // this chat's (i.e. the user switched chats mid-delegation).
      if (lastCompletedTask.session_id && lastCompletedTask.session_id !== activeId) return

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
    }, 0)
    return () => window.clearTimeout(deliveryTimer)
  }, [lastCompletedTask, awaitingNotification, taskGroups, activeId, clearLastCompletedTask, persistTaskGroupToHistory, appendMessage])

  useEffect(() => {
    if (!awaitingNotification || !lastSessionEvent || !activeId) return
    if (lastSessionEvent.session_id !== activeId) return
    const eventType = String(lastSessionEvent.event.type ?? '')
    if (eventType === 'notification_result') {
      // New backends also send task_complete with this delivery ID.
      if (lastSessionEvent.event.task_id) return
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

  // Fired on pagehide/beforeunload and on a genuine mid-stream connection
  // loss. Persists "what arrived so far" (partial text + the closed parts
  // trace) as an assistant message marked INTERRUPTED, so a page reload shows
  // the partial reply instead of nothing. Tool side-effects are NOT re-run;
  // this only records what already happened.
  const persistInterruptedPartial = useCallback(
    (sessionId: string | null) => {
      if (partialCommittedRef.current) return
      const textSoFar = (assembledTextRef.current || '').trim()
      // Flush any RAF-buffered parts into the parts ref so the trace is current.
      if (pendingEventsRef.current.length > 0) {
        streamingPartsRef.current = applyPendingEvents(
          streamingPartsRef.current,
          pendingEventsRef.current,
        )
        pendingEventsRef.current = []
      }
      const partsSnap = closeOpenParts(streamingPartsRef.current)
      const hasTextPart = partsSnap.some((p) => p.kind === 'text' && (p.text || '').trim().length > 0)
      if (!textSoFar && partsSnap.length === 0) return // nothing arrived — nothing to persist
      partialCommittedRef.current = true
      // Mirror the established error-render path: when we have running text we
      // persist a collapsed single bubble (content + marker) so the marker is
      // never hidden by PartsChain's hasText-suppresses-content logic.
      if (textSoFar) {
        appendMessage('assistant', textSoFar + INTERRUPTED_MARKER, undefined, undefined, sessionId)
      } else if (!hasTextPart && partsSnap.length > 0) {
        // Mid-tool/thinking interrupt with no assembled prose: keep the trace.
        appendMessage('assistant', INTERRUPTED_MARKER.trimStart(), partsSnap, undefined, sessionId)
      } else {
        appendMessage('assistant', INTERRUPTED_MARKER.trimStart(), undefined, undefined, sessionId)
      }
    },
    [appendMessage],
  )

  // Persist any partial stream on page unload (refresh/nav/close). Fires
  // synchronously on pagehide before the fetch is aborted; the AbortError
  // catch is a backstop for genuine connection loss without navigation.
  useEffect(() => {
    if (!isStreaming) return undefined
    const onPageHide = () => {
      persistInterruptedPartial(useSessionStore.getState().activeId)
    }
    window.addEventListener('pagehide', onPageHide)
    window.addEventListener('beforeunload', onPageHide)
    return () => {
      window.removeEventListener('pagehide', onPageHide)
      window.removeEventListener('beforeunload', onPageHide)
    }
  }, [isStreaming, persistInterruptedPartial])

  // Clear task groups and usage when switching sessions
  useEffect(() => {
    usageRef.current = null
    setUsage(null)
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

  const sendMessage = useCallback(async (rawText: string, files: File[] = [], referencedAttachmentIds: string[] = [], referencedNoteIds: string[] = [], rawDisplayText?: string) => {
    const projectContext = projectSubmission(useSessionStore.getState().activeId)
    const text = rawText.trim()
    // Mentions are expanded for master but shown to the user as they typed them.
    const displayText = (rawDisplayText ?? rawText).trim()
    if (!text && files.length === 0) return
    if (isStreaming) return

    // Two-phase: upload staged files first, then send the message carrying only
    // their IDs. The server resolves IDs (owner-scoped) and injects image_read
    // markers + inline text — the chat request never carries file bytes.
    let attachmentIds: string[] = [...referencedAttachmentIds]
    let attachments: Attachment[] | undefined
    if (files.length > 0) {
      try {
        const { files: uploaded, errors } = await uploadFiles(files)
        attachments = uploaded.map((u) => ({
          id: u.id, name: u.name, mime: u.mime, size: u.size, width: u.width, height: u.height,
        }))
        attachmentIds = [...new Set([...attachmentIds, ...uploaded.map((u) => u.id)])]
        if (errors.length) {
          appendMessage('assistant', `_Some files were rejected: ${errors.map((e) => `${e.name}: ${e.error}`).join('; ')}_`)
        }
      } catch (e) {
        appendMessage('user', displayText || '(attachments)')
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
    setTurnStartedAt(Date.now())
    setStreamingParts([])
    setIsStreaming(true)
    setBackgroundActivity('')

    const runId = crypto.randomUUID()
    runIdRef.current = runId
    appendedCompletionsRef.current.add(runId)
    const controller = new AbortController()
    abortRef.current = controller
    // Reset per-send persistence + stop flags so a prior turn's committed
    // partial doesn't suppress this turn's commit.
    assembledTextRef.current = ''
    partialCommittedRef.current = false
    stoppingRef.current = false

    // Track assembled text locally — avoids React ref/useEffect timing races
    let assembledText = ''
    let structuredResult: StructuredTaskResult | undefined
    const updateLiveUsage = createLiveUsage(usageRef.current)
    setUsage(updateLiveUsage({ type: 'turn_start' }))
    // Track whether any sub-agents were spawned — if so, poll for background results
    let hadSpawnAgent = false
    // Did master resolve the delegation inline (wait/read) in this same turn?
    let hadInlineResult = false

    try {
      // Notes reach the backend as ids, never as text: `@note "Title"` in the
      // message is only for the reader. Pinned context and this turn's mentions
      // are one list, capped at the 12 the API accepts.
      const pinnedNoteIds = useSessionStore.getState().sessions.find(s => s.id === sessionId)?.noteContext?.map(n => n.id) ?? []
      const noteIds = [...new Set([...pinnedNoteIds, ...referencedNoteIds])].slice(0, 12)
      let projectAccepted = false
      for await (const event of streamTask(text, apiHistory, controller.signal, sessionId, attachmentIds, runId, noteIds, projectContext)) {
        if (!projectAccepted && projectContext.project_id && sessionId) {
          projectAccepted = true
          const state = useProjects.getState()
          if (JSON.stringify(state.excluded[sessionId] || []) === JSON.stringify(projectContext.project_excluded || [])) useProjects.setState({excluded:{...state.excluded,[sessionId]:[]}})
        }
        const liveUsage = updateLiveUsage(event)
        if (liveUsage) setUsage(liveUsage)
        if (event.type === 'task_result') {
          structuredResult = event.result
        } else if (event.type === 'message_boundary') {
          enqueueStreamEvent({ kind: 'message_boundary' })
          assembledText += '\n\n'
        } else if (event.type === 'thinking') {
          enqueueStreamEvent({ kind: 'thinking_delta', text: event.text })
        } else if (event.type === 'text') {
          assembledText += event.text
          assembledTextRef.current = assembledText
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
        } else if (event.type === 'status') {
          // Master serializes turns on one lock. This arrives when the chat
          // turn is queued behind autonomous work — without it the composer
          // shows a bare "Thinking…" for however long that takes while the
          // agent-flow panel visibly streams something else, which reads as a
          // hung chat.
          queuedNoticeRef.current = true
          setQueuedNotice(String((event as { text?: string }).text || ''))
        } else if (event.type === 'usage_stats') {
          // Reconciled with provider counts by updateLiveUsage above.
        } else if (event.type === 'model_swapped') {
          // A hot swap landed mid-turn. The PUT that caused it already
          // broadcast over the WebSocket, but a swap can also come from the
          // settings file changing under a running agent — this is the only
          // signal for that case.
          if (event.agent === 'master') {
            setMasterModel(event.model)
            setMasterAdapter(event.adapter)
          }
        } else if (event.type === 'compact') {
          setQueuedNotice('')
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

      // The turn is over — nothing is still "running". Close out any open
      // thinking OR tool parts so a tool whose tool_done never arrived (e.g.
      // wait_for_agent, whose result master surfaced inline) doesn't spin
      // forever. Applied to BOTH the live view and the captured finalParts
      // (what gets persisted/grouped), since the ref lags the last flush.
      setStreamingParts((prev) => closeOpenParts(prev))

      // Capture the full parts array before resetting
      const finalParts = closeOpenParts(streamingPartsRef.current)

      const partsToSave = finalParts.length > 0 ? finalParts : undefined
      appendMessage('assistant', assembledText, partsToSave, undefined, sessionId, structuredResult ? { structured_result: structuredResult } : undefined, `${runId}:0`)
      if (hadSpawnAgent && !hadInlineResult) setAwaitingNotification(true)
      if (assembledText) {
        const { voiceEnabled: ve, voiceAutoSpeak: vas } = useAppStore.getState()
        if (ve && vas) speakText(assembledText)
      }
    } catch (e) {
      // Release live-SSE suppression so a later durable completion can arrive
      // via WebSocket. A completion already received remains in backgroundTasks.
      appendedCompletionsRef.current.delete(runId)
      const finished = useWsStore.getState().backgroundTasks.find((t) => t.task_id === runId && ['done', 'error', 'timeout', 'cancelled'].includes(t.status))
      if ((e as Error).name === 'TaskRequestError') {
        appendMessage('assistant', `Could not start task: ${(e as Error).message}`, undefined, undefined, sessionId)
      } else if (finished) {
        const text = finished.result || finished.error || '_Task completed_'
        appendMessage('assistant', text, undefined, undefined, sessionId, finished.structured_result ? { structured_result: finished.structured_result } : undefined, `${runId}:0`)
        appendedCompletionsRef.current.add(runId)
      } else if ((e as Error).name === 'AbortError') {
        if (!stoppingRef.current) persistInterruptedPartial(sessionId)
        else appendMessage('assistant', assembledText + '\n\n_Cancelled._', undefined, undefined, sessionId, structuredResult ? { structured_result: structuredResult } : undefined, `${runId}:0`)
      } else {
        const errText = `\n\n_Connection interrupted: ${(e as Error).message}. The task remains in the backend; its result will appear here when available._`
        appendMessage('assistant', (assembledText + errText).trim(), undefined, undefined, sessionId)
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
    // Mark an intentional Stop so the AbortError catch does NOT persist a
    // half-finished partial as if it were a real answer. Only page-unload /
    // genuine connection-loss persists.
    stoppingRef.current = true
    const runId = runIdRef.current
    if (runId) {
      void fetch(`/api/tasks/${runId}/cancel`, { method: 'POST' }).then((response) => {
        if (!response.ok) throw new Error(`Cancel failed: ${response.status}`)
        abortRef.current?.abort()
      }).catch((error) => {
        stoppingRef.current = false
        setQueuedNotice(String(error))
      })
    }
  }

  return (
    <div className="studio-chat flex flex-col h-full bg-zinc-950" style={{ minHeight: 0 }}>
      {/* Message list */}
      <div className="studio-chat-usage" aria-label="Master model and usage">
        <CostBar compact showModel adapter={masterAdapter} model={masterModel}
          inputTokens={usage?.input_tokens ?? 0} outputTokens={usage?.output_tokens ?? 0}
          tokensPerSecond={usage?.tokens_per_second ?? 0} contextWindow={usage?.context_window ?? 0}
          estimated={usage?.estimated ?? false} inputKnown={usage?.inputKnown ?? false} outputKnown={usage !== null} />
      </div>
      <div className="relative flex flex-1 flex-col" style={{ minHeight: 0 }}>
      {searchOpen && (
        <ChatSearchBar
          query={searchQuery}
          onQuery={(value) => { setSearchQuery(value); setSearchIndex(0) }}
          matchCount={searchMatches.length}
          activeIndex={searchIndex}
          onPrev={() => stepSearch(-1)}
          onNext={() => stepSearch(1)}
          onClose={() => { setSearchOpen(false); setSearchQuery('') }}
        />
      )}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className={`chat-history flex-1 overflow-y-auto px-4 py-4 space-y-3 ${noAnimate ? 'no-animate' : ''}`}
        style={{ minHeight: 0 }}
      >
        {history.length === 0 && !isStreaming && (
          <div
            className={`studio-welcome-wrap ${
              welcomeReady ? 'welcome-ready' : 'splash-hidden'
            }`}
          >
            <StudioWelcome onChoose={prompt => { chatInputRef.current?.setText(prompt); chatInputRef.current?.focus() }} />
          </div>
        )}

        {history.map((msg, i) => {
          const hitPosition = searchMatches.indexOf(i)
          return (
          <div
            key={i}
            data-msg-index={i}
            className={`group relative ${hitPosition >= 0 ? 'chat-search-hit' : ''} ${hitPosition === searchIndex ? 'is-current' : ''}`}
          >
            {msg.role === 'assistant' && msg.taskCompletion && !msg.taskCompletion.structured_result ? (
              // A "what just finished" card: the backend completed a background
              // task (resume/notification/goal/cron) that carried structured
              // metadata. Show the rich card instead of the old bare text.
              <TaskCompletionCard task={msg.taskCompletion} />
            ) : msg.role === 'assistant' && msg.parts && msg.parts.length > 0 ? (
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
                onEdit={msg.role === 'user' && !isStreaming ? (content) => {
                  chatInputRef.current?.setText(content)
                  chatInputRef.current?.focus()
                } : undefined}
              />
            )}
            {msg.role === 'assistant' && msg.taskCompletion?.structured_result && <TaskCompletionCard task={msg.taskCompletion} artifacts={artifactsByTask.get(taskIdFromCompletionId(msg.completionId) ?? '')} />}
            {msg.role === 'assistant' && !msg.taskCompletion?.structured_result && (
              <ArtifactStrip artifacts={artifactsByTask.get(taskIdFromCompletionId(msg.completionId) ?? '')} />
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
          )
        })}

        {/* Completed task groups */}
        {taskGroups.map((group) => (
          <TaskGroupBubble
            key={group.id}
            group={group}
            masterModel={masterModel}
            artifacts={artifactsByTask.get(group.id)}
          />
        ))}

        {/* Streaming assistant response */}
        {isStreaming && streamingParts.length > 0 && (
          <PartsChain parts={streamingParts} masterModel={masterModel} streaming />
        )}

        {isStreaming && (
          <TurnStatusBar
            spinner={<TypingIndicator />}
            label={livePhase}
            tool={liveTool}
            startedAt={turnStartedAt}
            tokensPerSecond={usage?.tokens_per_second ?? undefined}
            outputTokens={usage?.output_tokens ?? undefined}
            onStop={handleStop}
          />
        )}

        {/* Children master has spawned in this turn and not yet collected.
            The delegation trace only becomes a task group once the turn ends,
            so without this the most interesting moment — the sub-agent actually
            working — has nothing on screen but a spinner. */}
        {liveDelegations.map((agent) => (
          <SubAgentActivity key={`live-${agent}`} agentName={agent} running />
        ))}

        {/* Autonomous work the server started on its own (a post-restart
            resume, a cron tick, a goal). Its output streams to the agent panel,
            not this chat's SSE, so without this the chat looks idle while
            master is visibly working elsewhere — then a result appears from
            nowhere. Show it running here, in the chat the user is actually
            looking at. */}
        {autonomousRunning.length > 0 && !awaitingNotification && (
          <div className="space-y-1" data-testid="autonomous-running">
            {/* Rendered through the SAME PartsChain as a live chat turn, so a
                resumed turn reads as master talking — bubble, tool call,
                bubble — rather than a "background task" block the user has to
                wait on and unpack. */}
            {liveParts.length > 0 && (
              <PartsChain parts={liveParts} masterModel={masterModel} streaming />
            )}
            {autonomousRunning.map((t: BackgroundTask) => (
              <div
                key={t.task_id}
                className="flex items-center gap-2 text-zinc-500 text-sm pl-1"
              >
                <TypingIndicator />
                <span>
                  {t.session_id === activeId
                    ? (t.source === 'resume' ? 'Resuming after restart' : `Running ${t.source ?? 'background'} task`)
                    : `Master is busy with other ${t.source ?? 'background'} work`}
                  {t.prompt ? ` — ${t.prompt.replace(/^\[Resume\]\s*/, '').slice(0, 80)}` : ''}
                </span>
              </div>
            ))}
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
              <div className="pl-6 text-[13px] text-zinc-400 font-mono">
                {backgroundActivity}
              </div>
            )}
          </div>
        )}

        <div ref={bottomRef} />
      </div>
      {!atBottom && (history.length > 0 || isStreaming) && (
        <button type="button" className="chat-jump" onClick={jumpToLatest} title="Scroll to the newest message">
          ↓ Latest
          {unseen > 0 && <span className="chat-jump-badge">{unseen > 99 ? '99+' : unseen}</span>}
        </button>
      )}
      </div>

      {/* Input area */}
      <div className="studio-composer flex-shrink-0">
        {showVoiceSettings && (
          <div className="mb-3 rounded-lg border border-zinc-700 bg-zinc-900">
            <VoiceSettings />
          </div>
        )}
        {voiceError && (
          <div className="mb-2 text-xs text-red-400">{voiceError}</div>
        )}
        <ProjectContext />
        <NoteContextBar />
        <div className="studio-composer-controls flex flex-wrap gap-2 items-end">
          <ChatInput
            ref={chatInputRef}
            onSubmit={(submission) => sendMessage(
              submission.text,
              submission.files,
              submission.attachmentIds,
              submission.noteIds,
              submission.displayText,
            )}
            disabled={isStreaming}
          />
          {micSupported && voiceEnabled && (
            <button
              onClick={() => {
                if (micListening) {
                  stopListening()
                } else {
                  startListening()
                }
              }}
              className={`px-3 py-2 rounded-lg text-sm flex-shrink-0 ${
                micListening
                  ? 'bg-red-700 text-white hover:bg-red-600 animate-pulse'
                  : 'bg-zinc-700 text-zinc-300 hover:bg-zinc-600'
              }`}
              title={micListening ? 'Stop listening' : 'Start listening'}
            >
              <Mic size={16} aria-hidden="true" />
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
            <span className="inline-flex items-center gap-1.5"><Settings2 size={14} aria-hidden="true" />Voice</span>
          </button>
          <SendButton
            isStreaming={isStreaming}
            launchTick={launchTick}
            onSend={() => chatInputRef.current?.submit()}
            onStop={handleStop}
          />
        </div>
        <div className="studio-composer-hint"><span>Talk to Master · your agents work together</span><span>Enter to send <span aria-hidden="true">↵</span></span></div>

      </div>
    </div>
  )
}

function _helpText(): string {
  return commandHelpTable()
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
