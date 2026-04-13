import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Session, Message } from '../api/types'

interface SessionStore {
  sessions: Session[]
  activeId: string | null
  history: Message[]
  pendingChatInput: string | null
  newSession: () => void
  loadSession: (id: string) => void
  appendMessage: (role: 'user' | 'assistant', content: string) => void
  deleteSession: (id: string) => void
  setPendingChatInput: (text: string) => void
  clearPendingChatInput: () => void
}

export const useSessionStore = create<SessionStore>()(
  persist(
    (set, get) => ({
      sessions: [],
      activeId: null,
      history: [],
      pendingChatInput: null,
      setPendingChatInput: (text) => set({ pendingChatInput: text }),
      clearPendingChatInput: () => set({ pendingChatInput: null }),

      newSession() {
        const id = crypto.randomUUID()
        const session: Session = {
          id,
          name: `Session ${new Date().toLocaleString()}`,
          createdAt: new Date().toISOString(),
          history: [],
        }
        set((s) => ({
          sessions: [session, ...s.sessions].slice(0, 50),
          activeId: id,
          history: [],
        }))
      },

      loadSession(id) {
        const session = get().sessions.find((s) => s.id === id)
        if (!session) return
        set({ activeId: id, history: session.history })
      },

      appendMessage(role, content) {
        const msg: Message = { role, content }
        const { activeId, sessions } = get()

        if (!activeId) {
          // auto-create session on first message
          const id = crypto.randomUUID()
          const session: Session = {
            id,
            name: `Session ${new Date().toLocaleString()}`,
            createdAt: new Date().toISOString(),
            history: [msg],
          }
          set((s) => ({
            sessions: [session, ...s.sessions].slice(0, 50),
            activeId: id,
            history: [msg],
          }))
          return
        }

        set(() => {
          const updated = sessions.map((sess) =>
            sess.id === activeId ? { ...sess, history: [...sess.history, msg] } : sess,
          )
          const currentHistory = updated.find((s) => s.id === activeId)?.history ?? []
          return { sessions: updated, history: currentHistory }
        })
      },

      deleteSession(id) {
        set((s) => {
          const sessions = s.sessions.filter((sess) => sess.id !== id)
          const activeId = s.activeId === id ? (sessions[0]?.id ?? null) : s.activeId
          const history = activeId
            ? (sessions.find((sess) => sess.id === activeId)?.history ?? [])
            : []
          return { sessions, activeId, history }
        })
      },
    }),
    { name: 'yapoc-sessions' },
  ),
)
