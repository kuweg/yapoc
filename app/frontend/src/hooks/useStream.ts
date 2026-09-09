import type { Message, StreamEvent } from '../api/types'

// Maximum number of reconnect attempts before giving up
const MAX_RETRIES = 8
// Base delay for exponential backoff (ms)
const RETRY_BASE_MS = 1_000
// Bound silent sockets left open by a failed proxy.
const READ_IDLE_TIMEOUT_MS = 25_000

/**
 * Stream a task via SSE with automatic reconnection.
 *
 * The backend emits `: keepalive` comment lines regularly to prevent
 * proxy/browser idle-connection timeouts during long agent tasks.  If the
 * connection still drops (network blip, server restart), this generator
 * retries up to MAX_RETRIES times with exponential backoff before throwing.
 *
 * The `signal` AbortSignal is forwarded to every fetch attempt so the caller
 * can cancel the stream at any time (e.g. user clicks Stop).
 */
export async function* streamTask(
  task: string,
  history: Message[],
  signal: AbortSignal,
  sessionId?: string | null,
  attachments?: string[],
  taskId: string = crypto.randomUUID(),
  noteIds: string[] = [],
): AsyncGenerator<StreamEvent> {
  let attempt = 0
  let afterSeq = 0

  while (true) {
    try {
      for await (const event of _streamOnce(task, history, signal, sessionId, attachments, taskId, afterSeq, noteIds)) {
        const seq = (event as StreamEvent & { seq?: number }).seq
        if (seq !== undefined) {
          if (seq <= afterSeq) continue
          afterSeq = seq
        }
        yield event
      }
      return // clean finish — no retry needed
    } catch (err) {
      // Never retry on user-initiated abort
      if (signal.aborted) throw err
      if ((err as Error).name === 'AbortError') throw err
      if ((err as Error).name === 'TaskRequestError') throw err
      // Reattach to the same durable run and ordered cursor. This POST never
      // creates a second execution, even if the prior response was lost.

      attempt++
      if (attempt > MAX_RETRIES) throw err

      // Exponential backoff: 1 s, 2 s, 4 s …
      const delay = Math.min(5_000, RETRY_BASE_MS * Math.pow(2, attempt - 1))
      await _sleep(delay, signal)
    }
  }
}

async function _readWithIdleTimeout(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  signal: AbortSignal,
): Promise<ReadableStreamReadResult<Uint8Array>> {
  if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
  let timer: ReturnType<typeof setTimeout> | undefined
  let onAbort: () => void = () => {}
  const idle = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error('SSE idle timeout')), READ_IDLE_TIMEOUT_MS)
    onAbort = () => reject(new DOMException('Aborted', 'AbortError'))
    signal.addEventListener('abort', onAbort, { once: true })
  })
  try {
    return await Promise.race([reader.read(), idle])
  } finally {
    clearTimeout(timer)
    signal.removeEventListener('abort', onAbort)
  }
}

async function _sleep(ms: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer)
      reject(new DOMException('Aborted', 'AbortError'))
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

async function* _streamOnce(
  task: string,
  history: Message[],
  signal: AbortSignal,
  sessionId?: string | null,
  attachments?: string[],
  taskId?: string,
  afterSeq = 0,
  noteIds: string[] = [],
): AsyncGenerator<StreamEvent> {
  const res = await fetch('/api/task/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      task,
      task_id: taskId,
      after_seq: afterSeq,
      history,
      source: 'ui',
      session_id: sessionId || undefined,
      attachments: attachments && attachments.length ? attachments : undefined,
      note_ids: noteIds,
    }),
    signal,
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const error = new Error(typeof body.detail === 'string' ? body.detail : `Task request failed (${res.status})`)
    if (res.status >= 400 && res.status < 500 && res.status !== 429) error.name = 'TaskRequestError'
    throw error
  }
  if (!res.body) throw new Error('No response body')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await _readWithIdleTimeout(reader, signal)
      if (done) throw new Error("SSE closed before terminal event")

      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() ?? ''

      for (const part of parts) {
        const line = part.trim()
        if (!line) continue
        // SSE comment lines (keepalive pings) — skip silently
        if (line.startsWith(':')) continue
        const dataLine = line.startsWith('data: ') ? line.slice(6) : line
        if (dataLine === '[DONE]') return
        yield JSON.parse(dataLine) as StreamEvent
      }
    }
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}
