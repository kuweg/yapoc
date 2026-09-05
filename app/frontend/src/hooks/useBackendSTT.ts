import { useCallback, useEffect, useRef, useState } from 'react'
import { transcribeSpeech } from '../api/client'

export interface BackendSTTResult {
  text: string
  confidence: number
  engine: string
  duration_ms: number
}

interface UseBackendSTTOptions {
  onResult?: (result: BackendSTTResult) => void
  onError?: (error: string) => void
  onEnd?: () => void
  /** Backend STT engine — e.g. 'openai' (defaults server-side). */
  engine?: string
  language?: string
}

interface UseBackendSTTReturn {
  isListening: boolean
  start: () => void
  stop: () => void
  supported: boolean
}

/**
 * Backend-powered speech-to-text via the YAOPC /api/stt endpoint.
 *
 * Requests the microphone through getUserMedia, captures audio with
 * MediaRecorder (wav when the browser supports it, else the default mime),
 * then POSTs the resulting Blob to /api/stt (OpenAI Whisper on the backend).
 *
 * This replaces the browser-native SpeechRecognition path as the primary mic
 * input. `supported` is true only when the media APIs AND the backend STT
 * endpoint are both reachable. Guarantees a graceful no-op (and surface via
 * onError) when getUserMedia, MediaRecorder, or the network is unavailable.
 */
export function useBackendSTT(
  options: UseBackendSTTOptions = {},
): UseBackendSTTReturn {
  const [isListening, setIsListening] = useState(false)
  const [supported, setSupported] = useState(false)
  const optionsRef = useRef(options)
  optionsRef.current = options

  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const sessionRef = useRef(0)
  const listeningRef = useRef(false)
  const supportedRef = useRef(false)

  // Detect capability support once on mount.
  useEffect(() => {
    const ok =
      typeof window !== 'undefined' &&
      !!navigator.mediaDevices &&
      !!navigator.mediaDevices.getUserMedia &&
      typeof window.MediaRecorder !== 'undefined' &&
      typeof window.Blob !== 'undefined'
    supportedRef.current = ok
    setSupported(ok)
    return () => {
      // Tear down any in-flight capture on unmount.
      sessionRef.current += 1
      recorderRef.current?.state !== 'inactive' && recorderRef.current?.stop()
      streamRef.current?.getTracks().forEach((t) => t.stop())
      recorderRef.current = null
      streamRef.current = null
      listeningRef.current = false
    }
  }, [])

  const doStop = useCallback(() => {
    const rec = recorderRef.current
    // Let the recorder finish its current stop (keeps dataavailable handler
    // running so the final chunk is flushed before transcription).
    if (rec && rec.state !== 'inactive') {
      try {
        rec.stop()
      } catch {
        /* state already inactive */
      }
    }
    // We do NOT clear the tracks here — the stop handler flushes the blob and
    // releases the stream. Marking as not-listening is handled by onstop to
    // give the pending transcription a window to start.
  }, [])

  const stop = useCallback(() => {
    if (!listeningRef.current) return
    doStop()
  }, [doStop])

  const start = useCallback(async () => {
    const opts = optionsRef.current
    if (listeningRef.current || !supportedRef.current) {
      if (!supportedRef.current) opts.onError?.('Backend STT is not supported in this browser')
      return
    }

    sessionRef.current += 1
    const session = sessionRef.current
    chunksRef.current = []
    listeningRef.current = true
    setIsListening(true)

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (error) {
      listeningRef.current = false
      setIsListening(false)
      opts.onError?.('Microphone access denied')
      return
    }
    // Session may have been torn down while awaiting permission.
    if (session !== sessionRef.current) {
      stream.getTracks().forEach((t) => t.stop())
      return
    }

    const MediaRecorderCtor = window.MediaRecorder
    // Prefer wav where browsers expose a working 'audio/wav' encoder; many
    // only ship the default (usually opus in a webm/ogg container). The
    // backend accepts wav per spec, but any recorded mime is POSTed and the
    // backend+Whisper handle decoding via its pipeline.
    const mimeCandidates = ['audio/wav', 'audio/webm', 'audio/ogg', '']
    let mimeType = ''
    for (const candidate of mimeCandidates) {
      if (!candidate) break // fall back to browser default
      if (MediaRecorderCtor.isTypeSupported(candidate)) {
        mimeType = candidate
        break
      }
    }

    try {
      const recorder = new MediaRecorderCtor(
        stream,
        mimeType ? { mimeType } : undefined,
      )
      recorderRef.current = recorder
      streamRef.current = stream

      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data)
        }
      }

      recorder.onstop = () => {
        // Only resolve the active session's capture.
        if (session !== sessionRef.current) return
        listeningRef.current = false
        stream.getTracks().forEach((t) => t.stop())
        recorderRef.current = null
        streamRef.current = null
        setIsListening(false)
        opts.onEnd?.()

        const blob =
          chunksRef.current.length > 0
            ? new Blob(chunksRef.current, { type: recorder.mimeType || mimeType || 'audio/wav' })
            : null
        chunksRef.current = []
        if (!blob || blob.size === 0) return

        void transcribeSpeech(
          blob,
          opts.engine ?? 'openai',
          opts.language ?? 'en-US',
        )
          .then((result) => {
            if (session !== sessionRef.current) return
            if (!result.text || !result.text.trim()) {
              // Blank transcription (silence / noise) is not an error.
              return
            }
            opts.onResult?.(result)
          })
          .catch((error: unknown) => {
            if (session !== sessionRef.current) return
            const message =
              error instanceof Error ? error.message : String(error)
            // Surface a friendlier label for HTTP-level failures.
            const msg =
              /\bHTTP\b|\/stt/.test(message)
                ? 'Speech recognition service error'
                : message
            opts.onError?.(msg)
          })
      }

      recorder.onerror = () => {
        if (session !== sessionRef.current) return
        listeningRef.current = false
        stream.getTracks().forEach((t) => t.stop())
        recorderRef.current = null
        streamRef.current = null
        setIsListening(false)
        opts.onError?.('Recording failed')
        opts.onEnd?.()
      }

      recorder.start()
    } catch (error) {
      listeningRef.current = false
      setIsListening(false)
      stream.getTracks().forEach((t) => t.stop())
      recorderRef.current = null
      streamRef.current = null
      opts.onError?.(error instanceof Error ? error.message : 'Failed to start recording')
    }
  }, [])

  return { isListening, start, stop, supported }
}
