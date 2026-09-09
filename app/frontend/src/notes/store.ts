import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface NotesStore {
  selectedId: string | null
  select: (id: string | null) => void
  capture: { content: string; title: string } | null
  setCapture: (capture: NotesStore['capture']) => void
  drafts: Record<string, { content: string; revision: string }>
  setDraft: (id: string, content: string, revision: string) => void
  clearDraft: (id: string) => void
}
export const useNotesStore = create<NotesStore>()(persist((set) => ({
  selectedId: null, select: selectedId => set({ selectedId }),
  capture: null, setCapture: capture => set({ capture }),
  drafts: {},
  setDraft: (id, content, revision) => set(s => ({ drafts: { ...s.drafts, [id]: { content, revision } } })),
  clearDraft: id => set(s => { const drafts = { ...s.drafts }; delete drafts[id]; return { drafts } }),
}), { name: 'yapoc-notes', partialize: s => ({ selectedId: s.selectedId, drafts: s.drafts }) }))
