import { useRef, useEffect, useState, useCallback } from 'react'
import { streamTask } from '../hooks/useStream'
import { useSessionStore } from '../store/session'
import { useDashboardStore } from '../dashboard/store/dashboardStore'
import { useWsStore } from '../store/wsStore'
import { updateTicket } from '../dashboard/api/ticketClient'
import { MessageBubble } from './MessageBubble'
import { ToolCallBlock } from './ToolCallBlock'
import { ThinkingBlock } from './ThinkingBlock'
import { CostBar } from './CostBar'
import { ApprovalDialog } from './ApprovalDialog'
import type { UsageEvent } from '../api/types'

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

interface PendingApproval {
  requestId: string
  toolName: string
  input: Record<string, unknown>
}

// Default model for cost estimation — update when backend exposes model in usage events
const DEFAULT_MODEL = 'claude-sonnet-4-6'

export function ChatPanel() {
  const { history, appendMessage, pendingChatInput, clearPendingChatInput } = useSessionStore()
  const [input, setInput] = useState('')
  const [streamingParts, setStreamingParts] = useState<Part[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [usage, setUsage] = useState<UsageEvent | null>(null)
  const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(null)
  const [awaitingNotification, setAwaitingNotification] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // WebSocket-based background notification listener
  const lastCompletedTask = useWsStore((s) => s.lastCompletedTask)
  const wsConnected = useWsStore((s) => s.connected)

  const stopPolling = useCallback(() => {
    setAwaitingNotification(false)
  }, [])

  // Auto-scroll on new content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history, streamingParts])

  // WebSocket notification: when a background task completes, show result in chat
  useEffect(() => {
    if (!awaitingNotification || !lastCompletedTask) return
    const result = lastCompletedTask.result?.trim()
    if (result) {
      appendMessage('assistant', result)
    } else if (lastCompletedTask.error) {
      appendMessage('assistant', `_Background task error: ${lastCompletedTask.error}_`)
    }
    setAwaitingNotification(false)
    // Clear the lastCompletedTask so it doesn't re-trigger
    useWsStore.getState().lastCompletedTask = null
  }, [lastCompletedTask, awaitingNotification, appendMessage])

  // Clean up on unmount
  useEffect(() => () => stopPolling(), [stopPolling])

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
    if (overrideText == null) setInput('')
    setStreamingParts([])
    setIsStreaming(true)

    const controller = new AbortController()
    abortRef.current = controller

    // Track assembled text locally — avoids React ref/useEffect timing races
    let assembledText = ''
    // Track whether any sub-agents were spawned — if so, poll for background results
    let hadSpawnAgent = false

    try {
      for await (const event of streamTask(text, apiHistory, controller.signal)) {
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
        } else if (event.type === 'tool_approval_request') {
          setPendingApproval({
            requestId: event.request_id,
            toolName: event.name,
            input: event.input,
          })
        } else if (event.type === 'tool_approval_result') {
          // Belt-and-suspenders close (dialog normally closes itself via onClose)
          setPendingApproval((cur) =>
            cur?.requestId === event.request_id ? null : cur,
          )
        }
      }

      // Mark any open thinking parts as done
      setStreamingParts((prev) =>
        prev.map((p) => (p.kind === 'thinking' && !p.done ? { ...p, done: true } : p)),
      )
      if (assembledText) appendMessage('assistant', assembledText)

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
      setPendingApproval(null)
      abortRef.current = null
      textareaRef.current?.focus()

      // Mark the dashboard ticket as done if this stream was triggered by a master assignment
      if (assembledText) {
        const ticketId = useDashboardStore.getState().activeMasterTicketId
        if (ticketId) {
          useDashboardStore.getState().setActiveMasterTicketId(null)
          updateTicket(ticketId, { status: 'done' }).then((updated) => {
            useDashboardStore.getState().upsertTicket(updated)
          }).catch(() => {})
        }
      }
    }
  }, [input, isStreaming, appendMessage])

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
      {/* Approval dialog — rendered as fixed overlay */}
      {pendingApproval && (
        <ApprovalDialog
          requestId={pendingApproval.requestId}
          toolName={pendingApproval.toolName}
          input={pendingApproval.input}
          onClose={() => setPendingApproval(null)}
        />
      )}

      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {history.length === 0 && !isStreaming && (
          <div className="flex items-center justify-center h-full text-zinc-600 text-sm">
            Send a message to get started
          </div>
        )}

        {history.map((msg, i) => (
          <MessageBubble key={i} role={msg.role} content={msg.content} agentName={msg.role === 'assistant' ? 'master' : undefined} />
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
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="px-4 py-3 border-t border-zinc-700 bg-zinc-900 flex-shrink-0">
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
            <button
              onClick={() => sendMessage()}
              disabled={!input.trim()}
              className="px-4 py-2 rounded-lg bg-[#FFB633] text-[#0a0a0a] text-sm font-semibold hover:bg-[#ffc84d] disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0"
            >
              Send ↵
            </button>
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
