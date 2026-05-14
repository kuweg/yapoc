import { useAppStore } from '../store/appStore'
import { useSpeechSynthesis } from '../hooks/useSpeech'
import { useSpeechRecognition } from '../hooks/useSpeech'

export function VoiceSettings() {
  const {
    voiceAutoSpeak, setVoiceAutoSpeak,
    voiceEnabled, setVoiceEnabled,
    selectedVoice, setSelectedVoice,
    voiceSpeed, setVoiceSpeed,
    voiceTtsMode, setVoiceTtsMode,
    voiceBackendEngine, setVoiceBackendEngine,
  } = useAppStore()

  const { voices, supported: ttsSupported } = useSpeechSynthesis({})
  const { supported: sttSupported } = useSpeechRecognition({})

  const browserVoiceUnavailable = !ttsSupported && !sttSupported

  return (
    <div className="p-4 space-y-4">
      <h3 className="text-sm font-semibold text-zinc-300">Voice Settings</h3>
      {browserVoiceUnavailable && (
        <p className="text-xs text-zinc-500">
          Browser speech APIs are unavailable. Backend TTS can still be used.
        </p>
      )}

      <label className="flex items-center justify-between">
        <span className="text-sm text-zinc-400">Voice Enabled</span>
        <input
          type="checkbox"
          checked={voiceEnabled}
          onChange={(e) => setVoiceEnabled(e.target.checked)}
          className="h-4 w-4 accent-[#FFB633]"
        />
      </label>

      {voiceEnabled && (
        <>
          <div>
            <label className="block text-sm text-zinc-400 mb-1">Playback Mode</label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setVoiceTtsMode('browser')}
                className={`rounded border px-2 py-1 text-xs ${
                  voiceTtsMode === 'browser'
                    ? 'border-[#FFB633] text-[#FFB633] bg-zinc-800'
                    : 'border-zinc-700 text-zinc-400 hover:border-zinc-500'
                }`}
              >
                Browser TTS
              </button>
              <button
                type="button"
                onClick={() => setVoiceTtsMode('backend')}
                className={`rounded border px-2 py-1 text-xs ${
                  voiceTtsMode === 'backend'
                    ? 'border-[#FFB633] text-[#FFB633] bg-zinc-800'
                    : 'border-zinc-700 text-zinc-400 hover:border-zinc-500'
                }`}
              >
                Backend TTS
              </button>
            </div>
            {voiceTtsMode === 'backend' && (
              <p className="mt-2 text-[11px] text-zinc-500">
                Backend mode requires `VOICE_ENABLED=true` on the API server.
              </p>
            )}
          </div>

          <label className="flex items-center justify-between">
            <span className="text-sm text-zinc-400">Auto-Speak Responses</span>
            <input
              type="checkbox"
              checked={voiceAutoSpeak}
              onChange={(e) => setVoiceAutoSpeak(e.target.checked)}
              className="h-4 w-4 accent-[#FFB633]"
            />
          </label>

          {voiceTtsMode === 'browser' && ttsSupported && (
            <div>
              <label className="block text-sm text-zinc-400 mb-1">Voice</label>
              <select
                value={selectedVoice}
                onChange={(e) => setSelectedVoice(e.target.value)}
                className="w-full rounded bg-zinc-800 px-2 py-1 text-sm text-zinc-300 border border-zinc-700"
              >
                <option value="">Browser Default</option>
                {voices.map((v) => (
                  <option key={v.name} value={v.name}>
                    {v.name} ({v.lang})
                  </option>
                ))}
              </select>
            </div>
          )}

          {voiceTtsMode === 'backend' && (
            <div>
              <label className="block text-sm text-zinc-400 mb-1">Engine</label>
              <select
                value={voiceBackendEngine}
                onChange={(e) => setVoiceBackendEngine(e.target.value as 'offline' | 'openai' | 'google')}
                className="w-full rounded bg-zinc-800 px-2 py-1 text-sm text-zinc-300 border border-zinc-700"
              >
                <option value="offline">offline</option>
                <option value="openai">openai</option>
                <option value="google">google</option>
              </select>
            </div>
          )}

          <div>
            <label className="block text-sm text-zinc-400 mb-1">
              Speed: {voiceSpeed.toFixed(1)}x
            </label>
            <input
              type="range"
              min="0.5"
              max="2.0"
              step="0.1"
              value={voiceSpeed}
              onChange={(e) => setVoiceSpeed(parseFloat(e.target.value))}
              className="w-full"
            />
          </div>
        </>
      )}

      {sttSupported && (
        <div>
          <span className="text-sm text-zinc-400">
            Mic input supported in browser
          </span>
        </div>
      )}
    </div>
  )
}
