import type { Message, StreamEvent } from '../api/types'

// Maximum number of reconnect attempts before giving up
const MAX_RETRIES = 3
// Base delay for exponential backoff (ms)
const RETRY_BASE_MS = 1_000
// How long to wait for /health to come back after a mid-stream drop
const HEALTH_WAIT_MS = 15_000
const HEALTH_POLL_MS = 500
// Idle-detection on the SSE reader. Backend emits `: keepalive` every 15s,
// so going 25s with zero bytes (not even a comment) means the socket is dead.
// On Vite's dev proxy a hard-killed upstream can leave the proxied client
// connection hanging indefinitely with no FIN — without this timeout the
// reader would block forever and the recovery path below never fires.
const READ_IDLE_TIMEOUT_MS = 25_000

/**
 * Thrown by streamTask when the SSE response is interrupted mid-stream and
 * the backend looks like it bounced (master's server_restart, deploy, kill).
 * The generator waits for /health to return OK before throwing, so callers
 * can show a friendly "server restarted, please retry" message and know the
 * backend is ready when the user re-sends.
 */
export class ServerRestartError extends Error {
  constructor(message = 'Server restarted mid-response. Please send again.') {
    super(message)
    this.name = 'ServerRestartError'
  }
}

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
  sessionId?: string | null,
): AsyncGenerator<StreamEvent> {
  let attempt = 0
  let yieldedAny = false

  while (true) {
    try {
      for await (const event of _streamOnce(task, history, signal, sessionId)) {
        yieldedAny = true
        yield event
      }
      return // clean finish — no retry needed
    } catch (err) {
      // Never retry on user-initiated abort
      if (signal.aborted) throw err
      if ((err as Error).name === 'AbortError') throw err
      // If the request already started streaming, retrying would replay a
      // side-effectful POST and can duplicate tool calls/delegations.
      // Instead, wait for /health to come back so the UI lands in a known-good
      // state, then surface a typed error so the caller can show a friendly
      // "server restarted" message rather than a raw NetworkError.
      if (yieldedAny) {
        const recovered = await _waitForHealth(signal)
        if (recovered) throw new ServerRestartError()
        throw err
      }

      attempt++
      if (attempt > MAX_RETRIES) throw err

      // Exponential backoff: 1 s, 2 s, 4 s …
      const delay = RETRY_BASE_MS * Math.pow(2, attempt - 1)
      await _sleep(delay, signal)
    }
  }
}

/**
 * Poll /health until it returns 200 OK or HEALTH_WAIT_MS elapses.
 * Used after a mid-stream drop to wait out a server restart so the UI
 * doesn't show "NetworkError" while the backend is mid-boot.
 */
async function _waitForHealth(signal: AbortSignal): Promise<boolean> {
  const deadline = Date.now() + HEALTH_WAIT_MS
  while (Date.now() < deadline) {
    if (signal.aborted) return false
    try {
      const res = await fetch('/health', { signal, cache: 'no-store' })
      if (res.ok) return true
    } catch {
      // backend not back yet — keep polling
    }
    try {
      await _sleep(HEALTH_POLL_MS, signal)
    } catch {
      return false
    }
  }
  return false
}

/**
 * Race reader.read() against an idle timeout. If READ_IDLE_TIMEOUT_MS elapses
 * with no data (including backend keepalives), throw so the outer recovery
 * path can probe /health and surface ServerRestartError. Without this the
 * stream can hang forever when the backend is killed behind a proxy that
 * doesn't propagate the upstream FIN.
 */
async function _readWithIdleTimeout(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  signal: AbortSignal,
): Promise<ReadableStreamReadResult<Uint8Array>> {
  let timer: ReturnType<typeof setTimeout> | null = null
  const idle = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      reject(new Error('SSE idle timeout — no data for 25s'))
    }, READ_IDLE_TIMEOUT_MS)
    signal.addEventListener('abort', () => {
      if (timer) clearTimeout(timer)
      reject(new DOMException('Aborted', 'AbortError'))
    }, { once: true })
  })
  try {
    return await Promise.race([reader.read(), idle])
  } finally {
    if (timer) clearTimeout(timer)
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
  sessionId?: string | null,
): AsyncGenerator<StreamEvent> {
  const res = await fetch('/api/task/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task, history, source: 'ui', session_id: sessionId || undefined }),
    signal,
  })

  if (!res.ok) throw new Error(`POST /task/stream: ${res.status}`)
  if (!res.body) throw new Error('No response body')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await _readWithIdleTimeout(reader, signal)
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
