import { useAppStore } from '../store/appStore'

/**
 * Animated "speaking sphere" indicator for the header.
 *
 * Pure presentational component: reads the shared `agentSpeaking` and
 * `agentListening` flags from the store and renders a small orb. Three states,
 * in priority order:
 *   - listening (mic active) → cyan orb with an expanding ring
 *   - speaking (TTS playback) → warm amber orb that pulsates + ripple ring
 *   - idle → small calm orb with a subtle breathing motion
 *
 * Conversation flows through a shared store so the sphere reacts to the same
 * speaking/listening state ChatPanel already tracks.
 */
export default function SpeakingSphere() {
  const agentSpeaking = useAppStore((s) => s.agentSpeaking)
  const agentListening = useAppStore((s) => s.agentListening)

  const state = agentListening ? 'listening' : agentSpeaking ? 'speaking' : 'idle'

  const label =
    state === 'listening'
      ? 'Listening'
      : state === 'speaking'
        ? 'Agent speaking'
        : 'Idle'

  return (
    <div
      className="relative flex-shrink-0 flex items-center justify-center"
      data-testid="speaking-sphere"
      title={label}
      aria-label={label}
      aria-live="polite"
      style={{ width: 24, height: 24 }}
    >
      {/* Expanding ripple ring — shown while listening or speaking */}
      <div
        className={
          state !== 'idle' ? 'sphere-ring is-visible' : 'sphere-ring'
        }
        aria-hidden="true"
      />
      {/* The sphere itself */}
      <span
        className={`sphere sphere-${state}`}
        aria-hidden="true"
      />
    </div>
  )
}
