import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type AppTab = 'chat' | 'agents' | 'observability' | 'graph' | 'vault' | 'sessions' | 'concilium' | 'channels' | 'tasks' | 'insights' | 'skills' | 'mcp' | 'plugins' | 'notes' | 'cron' | 'drive' | 'github'
export type VoiceTTSMode = 'browser' | 'backend'
export type VoiceBackendEngine = 'offline' | 'openai' | 'google'

interface AppStore {
  activeTab: AppTab
  setActiveTab: (tab: AppTab) => void
  voiceEnabled: boolean
  setVoiceEnabled: (v: boolean) => void
  voiceAutoSpeak: boolean
  setVoiceAutoSpeak: (v: boolean) => void
  selectedVoice: string
  setSelectedVoice: (v: string) => void
  voiceSpeed: number
  setVoiceSpeed: (v: number) => void
  voiceTtsMode: VoiceTTSMode
  setVoiceTtsMode: (mode: VoiceTTSMode) => void
  voiceBackendEngine: VoiceBackendEngine
  setVoiceBackendEngine: (engine: VoiceBackendEngine) => void
  // Runtime-only speaking indicator (not persisted via partialize)
  agentSpeaking: boolean
  setAgentSpeaking: (v: boolean) => void
  // Runtime-only mic-listening indicator (not persisted via partialize)
  agentListening: boolean
  setAgentListening: (v: boolean) => void
}

export const useAppStore = create<AppStore>()(
  persist(
    (set) => ({
      activeTab: 'chat',
      setActiveTab: (tab) => set({ activeTab: tab }),
      voiceEnabled: true,
      setVoiceEnabled: (v) => set({ voiceEnabled: v }),
      voiceAutoSpeak: true,
      setVoiceAutoSpeak: (v) => set({ voiceAutoSpeak: v }),
      selectedVoice: '',
      setSelectedVoice: (v) => set({ selectedVoice: v }),
      voiceSpeed: 1.0,
      setVoiceSpeed: (v) => set({ voiceSpeed: v }),
      voiceTtsMode: 'backend',
      setVoiceTtsMode: (mode) => set({ voiceTtsMode: mode }),
      voiceBackendEngine: 'openai',
      setVoiceBackendEngine: (engine) => set({ voiceBackendEngine: engine }),
      agentSpeaking: false,
      setAgentSpeaking: (v) => set({ agentSpeaking: v }),
      agentListening: false,
      setAgentListening: (v) => set({ agentListening: v }),
    }),
    {
      name: 'yapoc-voice-settings',
      partialize: (state) => ({
        voiceEnabled: state.voiceEnabled,
        voiceAutoSpeak: state.voiceAutoSpeak,
        selectedVoice: state.selectedVoice,
        voiceSpeed: state.voiceSpeed,
        voiceTtsMode: state.voiceTtsMode,
        voiceBackendEngine: state.voiceBackendEngine,
      }),
    },
  ),
)
