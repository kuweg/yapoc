import { useRef, useCallback, useEffect, useState } from 'react'

interface SpeechRecognitionEvent extends Event {
  resultIndex: number
  results: SpeechRecognitionResultList
}

interface SpeechRecognitionResultList {
  length: number
  [index: number]: SpeechRecognitionResult
}

interface SpeechRecognitionResult {
  isFinal: boolean
  length: number
  [index: number]: SpeechRecognitionAlternative
}

interface SpeechRecognitionAlternative {
  transcript: string
  confidence: number
}

interface SpeechRecognitionErrorEvent extends Event {
  error: string
  message: string
}

interface SpeechRecognition extends EventTarget {
  lang: string
  interimResults: boolean
  continuous: boolean
  maxAlternatives: number
  onresult: ((event: SpeechRecognitionEvent) => void) | null
  onend: (() => void) | null
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null
  onstart: (() => void) | null
  start(): void
  stop(): void
  abort(): void
}

declare var SpeechRecognition: {
  new (): SpeechRecognition
}

declare global {
  interface Window {
    SpeechRecognition: typeof SpeechRecognition
    webkitSpeechRecognition: typeof SpeechRecognition
  }
}

interface UseSpeechRecognitionOptions {
  onResult?: (text: string, isFinal: boolean) => void
  onEnd?: () => void
  onError?: (error: string) => void
  language?: string
}

interface UseSpeechRecognitionReturn {
  isListening: boolean
  start: () => void
  stop: () => void
  supported: boolean
}

export function useSpeechRecognition(
  options: UseSpeechRecognitionOptions = {},
): UseSpeechRecognitionReturn {
  const [isListening, setIsListening] = useState(false)
  const recognitionRef = useRef<SpeechRecognition | null>(null)
  const optionsRef = useRef(options)
  optionsRef.current = options

  const supported = !!(
    typeof window !== 'undefined' &&
    (window.SpeechRecognition || window.webkitSpeechRecognition)
  )

  const start = useCallback(() => {
    if (!supported) return

    const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRecognitionAPI) return

    const recognition = new SpeechRecognitionAPI()
    recognition.lang = optionsRef.current.language || 'en-US'
    recognition.interimResults = true
    recognition.continuous = false
    recognition.maxAlternatives = 1

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let transcript = ''
      let isFinal = false
      for (let i = event.resultIndex; i < event.results.length; i++) {
        transcript += event.results[i][0].transcript
        if (event.results[i].isFinal) {
          isFinal = true
        }
      }
      optionsRef.current.onResult?.(transcript, isFinal)
    }

    recognition.onend = () => {
      setIsListening(false)
      optionsRef.current.onEnd?.()
    }

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      setIsListening(false)
      if (event.error !== 'no-speech') {
        optionsRef.current.onError?.(event.error)
      }
      optionsRef.current.onEnd?.()
    }

    recognitionRef.current = recognition
    recognition.start()
    setIsListening(true)
  }, [supported])

  const stop = useCallback(() => {
    recognitionRef.current?.stop()
    setIsListening(false)
  }, [])

  return { isListening, start, stop, supported }
}

interface UseSpeechSynthesisOptions {
  voice?: string
  rate?: number
  pitch?: number
  onStart?: () => void
  onEnd?: () => void
  onError?: (error: string) => void
}

interface UseSpeechSynthesisReturn {
  speak: (text: string) => void
  stop: () => void
  isSpeaking: boolean
  supported: boolean
  voices: SpeechSynthesisVoice[]
}

export function useSpeechSynthesis(
  options: UseSpeechSynthesisOptions = {},
): UseSpeechSynthesisReturn {
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([])
  const optionsRef = useRef(options)
  optionsRef.current = options

  const supported = !!(
    typeof window !== 'undefined' && window.speechSynthesis
  )

  const loadVoices = useCallback(() => {
    if (!supported) return
    const all = window.speechSynthesis.getVoices()
    if (all.length > 0) {
      setVoices(all)
    }
  }, [supported])

  useEffect(() => {
    if (!supported) return
    loadVoices()
    const syn = window.speechSynthesis
    const handleVoicesChanged = () => loadVoices()
    syn.addEventListener('voiceschanged', handleVoicesChanged)
    return () => syn.removeEventListener('voiceschanged', handleVoicesChanged)
  }, [supported, loadVoices])

  const speak = useCallback(
    (text: string) => {
      if (!supported || !text.trim()) return

      window.speechSynthesis.cancel()

      const utterance = new SpeechSynthesisUtterance(text)
      const opts = optionsRef.current

      if (opts.voice && voices.length > 0) {
        const selected = voices.find((v) => v.name === opts.voice)
        if (selected) utterance.voice = selected
      }
      if (opts.rate != null) utterance.rate = opts.rate
      if (opts.pitch != null) utterance.pitch = opts.pitch

      utterance.onstart = () => {
        setIsSpeaking(true)
        opts.onStart?.()
      }
      utterance.onend = () => {
        setIsSpeaking(false)
        opts.onEnd?.()
      }
      utterance.onerror = (e) => {
        setIsSpeaking(false)
        if (e.error !== 'canceled') {
          opts.onError?.(e.error)
        }
        opts.onEnd?.()
      }

      window.speechSynthesis.speak(utterance)
    },
    [supported, voices],
  )

  const stop = useCallback(() => {
    if (supported) {
      window.speechSynthesis.cancel()
      setIsSpeaking(false)
    }
  }, [supported])

  return { speak, stop, isSpeaking, supported, voices }
}
