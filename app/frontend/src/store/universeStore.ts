import { create } from 'zustand'
export const useUniverseStore = create<{
  open: boolean; missionId: string | null; draft: string;
  setup: (draft?: string) => void; compare: (id: string) => void; close: () => void
}>(set => ({
  open: false, missionId: null, draft: '',
  setup: (draft = '') => set({ open: true, missionId: null, draft }),
  compare: missionId => set({ open: true, missionId }),
  close: () => set({ open: false }),
}))
