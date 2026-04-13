import { create } from 'zustand'

export type AppTab = 'chat' | 'agents' | 'dashboard' | 'graph' | 'vault'

interface AppStore {
  activeTab: AppTab
  setActiveTab: (tab: AppTab) => void
}

export const useAppStore = create<AppStore>((set) => ({
  activeTab: 'chat',
  setActiveTab: (tab) => set({ activeTab: tab }),
}))
