import { create } from 'zustand'

export type Theme = 'dark' | 'light'

interface ThemeStore {
  theme: Theme
  toggleTheme: () => void
  setTheme: (theme: Theme) => void
}

function applyTheme(theme: Theme) {
  document.documentElement.setAttribute('data-theme', theme)
  localStorage.setItem('yapoc-theme', theme)
}

const savedTheme = (localStorage.getItem('yapoc-theme') as Theme | null) ?? 'dark'
applyTheme(savedTheme)

export const useThemeStore = create<ThemeStore>((set) => ({
  theme: savedTheme,
  toggleTheme: () =>
    set((state) => {
      const next: Theme = state.theme === 'dark' ? 'light' : 'dark'
      applyTheme(next)
      return { theme: next }
    }),
  setTheme: (theme) => {
    applyTheme(theme)
    set({ theme })
  },
}))
