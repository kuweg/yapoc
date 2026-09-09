import { create } from 'zustand'

interface AgentChatStore {
  /** Currently selected agent for the chat flow side panel (null = closed) */
  selectedLogAgent: string | null
  openLogAgents: string[]
  focusVersion: number
  closeLogAgent: (name: string) => void
  setSelectedLogAgent: (name: string | null) => void
}

export const useAgentChatStore = create<AgentChatStore>((set) => ({
  selectedLogAgent: null,
  openLogAgents: [],
  focusVersion: 0,
  setSelectedLogAgent: (name: string | null) => set(state => ({
    selectedLogAgent: name,
    openLogAgents: name === null ? [] : state.openLogAgents.includes(name) ? state.openLogAgents : [...state.openLogAgents, name],
    focusVersion: state.focusVersion + 1,
  })),
  closeLogAgent: name => set(state => {
    const remaining = state.openLogAgents.filter(agent => agent !== name)
    return { openLogAgents: remaining, selectedLogAgent: state.selectedLogAgent === name ? remaining[remaining.length - 1] ?? null : state.selectedLogAgent }
  }),
}))
