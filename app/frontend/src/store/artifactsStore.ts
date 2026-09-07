import { create } from 'zustand'

interface ArtifactsStore {
  open: boolean
  toggle: () => void
  setOpen: (open: boolean) => void
  close: () => void
}

export const useArtifactsStore = create<ArtifactsStore>((set) => ({
  open: false,
  toggle: () => set((state) => ({ open: !state.open })),
  setOpen: (open) => set({ open }),
  close: () => set({ open: false }),
}))
