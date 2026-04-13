import type { Message, StreamEvent } from '../api/types'

// Maximum number of reconnect attempts before giving up
const MAX_RETRIES = 3
// Base delay for exponential backoff (ms)
const RETRY_BASE_MS = 1_000

/**
 * Stream a task via SSE with automatic reconnection.
 *
 * The backend emits `: keepalive` comment lines every 15 s to prevent
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
): AsyncGenerator<StreamEvent> {
  let attempt = 0

  while (true) {
    try {
      yield* _streamOnce(task, history, signal)
      return // clean finish — no retry needed
    } catch (err) {
      // Never retry on user-initiated abort
      if (signal.aborted) throw err
      if ((err as Error).name === 'AbortError') throw err

      attempt++
      if (attempt > MAX_RETRIES) throw err

      // Exponential backoff: 1 s, 2 s, 4 s …
      const delay = RETRY_BASE_MS * Math.pow(2, attempt - 1)
      await _sleep(delay, signal)
    }
  }
}

async function _sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms)
    signal.addEventListener('abort', () => {
      clearTimeout(timer)
      reject(new DOMException('Aborted', 'AbortError'))
    }, { once: true })
  })
}

async function* _streamOnce(
  task: string,
  history: Message[],
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const res = await fetch('/api/task/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task, history, source: 'ui' }),
    signal,
  })

  if (!res.ok) throw new Error(`POST /task/stream: ${res.status}`)
  if (!res.body) throw new Error('No response body')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

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
        try {
          const event = JSON.parse(dataLine) as StreamEvent
          yield event
        } catch {
          // skip malformed frames
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}
