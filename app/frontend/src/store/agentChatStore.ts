import { create } from 'zustand'

interface AgentChatStore {
  /** Currently selected agent for the chat flow side panel (null = closed) */
  selectedLogAgent: string | null
  setSelectedLogAgent: (name: string | null) => void
}

export const useAgentChatStore = create<AgentChatStore>((set) => ({
  selectedLogAgent: null,
  setSelectedLogAgent: (name: string | null) => set({ selectedLogAgent: name }),
}))
