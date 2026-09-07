import { create } from 'zustand'

interface WorkspaceStore {
  open: boolean
  pendingInsertion: string | null
  toggle: () => void
  setOpen: (open: boolean) => void
  close: () => void
  setPendingInsertion: (text: string) => void
  consumePendingInsertion: () => string | null
}

export const useWorkspaceStore = create<WorkspaceStore>((set, get) => ({
  open: false,
  pendingInsertion: null,
  toggle: () => set((state) => ({ open: !state.open })),
  setOpen: (open) => set({ open }),
  close: () => set({ open: false }),
  setPendingInsertion: (text) => set({ pendingInsertion: text }),
  consumePendingInsertion: () => {
    const pendingInsertion = get().pendingInsertion
    set({ pendingInsertion: null })
    return pendingInsertion
  },
}))
