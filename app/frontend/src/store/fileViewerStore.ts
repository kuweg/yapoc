import { create } from 'zustand'

export interface SelectedFile {
  path: string
  name?: string
}

interface FileViewerStore {
  selectedFile: SelectedFile | null
  selectFile: (file: SelectedFile) => void
  closeFile: () => void
}

export const useFileViewerStore = create<FileViewerStore>((set) => ({
  selectedFile: null,
  selectFile: (file) => set({ selectedFile: file }),
  closeFile: () => set({ selectedFile: null }),
}))
