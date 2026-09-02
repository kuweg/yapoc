import { create } from 'zustand'

export interface AgentLogWindow {
  id: string // unique window id (winsize-/split- persistence key)
  agentName: string
  state: string
}

interface WindowsStore {
  windows: AgentLogWindow[]
  openAgentLog: (agentName: string, state: string) => void
  closeWindow: (id: string) => void
}

/**
 * Registry of open floating windows. Rendered at the app root so a docked
 * window can reflow the whole body regardless of which tab is active.
 * One window per agent (re-opening focuses the existing one).
 */
export const useWindowsStore = create<WindowsStore>((set) => ({
  windows: [],
  openAgentLog: (agentName, state) =>
    set((s) =>
      s.windows.some((w) => w.agentName === agentName)
        ? s
        : { windows: [...s.windows, { id: `agentlog-${agentName}`, agentName, state }] },
    ),
  closeWindow: (id) => set((s) => ({ windows: s.windows.filter((w) => w.id !== id) })),
}))
