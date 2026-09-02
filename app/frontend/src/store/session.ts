import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import type { StorageValue } from 'zustand/middleware'
import type { Session, Message, TaskPart, Attachment } from '../api/types'

// Persistence budget. Counting messages alone was not enough: 50 sessions ×
// 200 messages is 10,000 messages of *unbounded* text, and a handful of long
// agent replies push that past the ~5MB quota — which is what produced
// "Setting the value of 'yapoc-sessions' exceeded the quota".
//
// Three limits now apply together: fewer sessions, fewer messages each, a hard
// cap on any single message's text, and a total byte budget enforced by
// dropping the oldest sessions until the payload fits.
const MAX_PERSISTED_MESSAGES = 100
const MAX_PERSISTED_SESSIONS = 25
/** Longest single message text kept in localStorage; the in-memory copy is untouched. */
const MAX_MESSAGE_CHARS = 8_000
/** Stay well under the ~5MB browser quota, leaving room for other yapoc keys. */
const MAX_PERSIST_BYTES = 2_500_000

const TRUNCATION_NOTE = '\n\n_[truncated in local history]_'

function slimContent(content: unknown): string {
  const text = typeof content === 'string' ? content : ''
  return text.length > MAX_MESSAGE_CHARS
    ? text.slice(0, MAX_MESSAGE_CHARS) + TRUNCATION_NOTE
    : text
}

/**
 * Drop whole sessions, oldest first, until the serialized payload fits the
 * budget. The active session is always kept — losing the chat you are looking
 * at to make room is never the right trade.
 */
function fitToBudget<T extends { sessions: Array<{ id: string }>; activeId: string | null }>(
  payload: T,
): T {
  let sessions = payload.sessions
  // Cheap guard: only pay for serialization when the payload is plausibly big.
  for (let guard = 0; guard < 100; guard++) {
    const size = JSON.stringify({ ...payload, sessions }).length
    if (size <= MAX_PERSIST_BYTES || sessions.length <= 1) break
    const dropIdx = sessions.findIndex((s) => s.id !== payload.activeId)
    if (dropIdx === -1) break
    sessions = [...sessions.slice(0, dropIdx), ...sessions.slice(dropIdx + 1)]
  }
  return sessions === payload.sessions ? payload : { ...payload, sessions }
}

// A persistent store that never throws on quota exhaustion. zustand's default
// storage calls setItem synchronously per write; once localStorage is over ~5MB
// the browser raises QuotaExceededError and the write is silently dropped by
// the middleware, which is what lost trailing assistant messages on reload.
// This wrapper catches that, warns, self-heals (drops stale oversized keys) and
// retries the write once with the already-capped partialized value.
const resilientStorage = <S>() => {
  // createJSONStorage can return undefined per its typings; localStorage is
  // always available in the browser so assert it here.
  const storage = createJSONStorage<S>(() => localStorage)!
  return {
    getItem: (name: string) => storage.getItem(name),
    setItem: (name: string, value: StorageValue<S>) => {
      try {
        storage.setItem(name, value)
      } catch (err) {
        console.warn(
          '[session] localStorage write failed (quota exceeded); clearing stale keys and retrying once.',
          err,
        )
        try {
          // Drop legacy/oversized keys that share the yapoc namespace so the
          // retry below has room.
          const stale: string[] = []
          for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i)
            if (k && k.startsWith('yapoc-sessions')) stale.push(k)
          }
          stale.forEach((k) => localStorage.removeItem(k))
          storage.setItem(name, value)
        } catch (retryErr) {
          console.error('[session] localStorage write still failing after self-heal.', retryErr)
          // Swallow — never crash the app because persistence failed.
        }
      }
    },
    removeItem: (name: string) => storage.removeItem(name),
  }
}

interface SessionStore {
  sessions: Session[]
  activeId: string | null
  history: Message[]
  pendingChatInput: string | null
  newSession: () => void
  loadSession: (id: string) => void
  appendMessage: (role: 'user' | 'assistant', content: string, parts?: TaskPart[], attachments?: Attachment[], sessionId?: string | null, taskCompletion?: import('../api/types').TaskCompletionMeta) => void
  deleteSession: (id: string) => void
  deleteMessage: (index: number) => void
  setPendingChatInput: (text: string) => void
  clearPendingChatInput: () => void
}

// The exact shape that gets persisted to localStorage. Distinguishing it from
// the full SessionStore lets migrate/partialize/onRehydrateStorage be typed
// consistently by zustand v5 (persist<S, Mps, Mcs, U>).
type PersistedState = {
  sessions: Array<{
    id: string
    name: string
    createdAt: string
    source?: string
    history: Array<Record<string, unknown>>
  }>
  activeId: string | null
}

export const useSessionStore = create<SessionStore>()(
  persist<SessionStore, [], [], PersistedState>(
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

      appendMessage(role, content, parts, attachments, sessionId, taskCompletion) {
        const msg: Message = { role, content }
        if (parts) msg.parts = parts
        if (attachments && attachments.length) msg.attachments = attachments
        if (taskCompletion && typeof taskCompletion === 'object' && Object.keys(taskCompletion).length > 0) msg.taskCompletion = taskCompletion
        const { activeId, sessions } = get()

        // A message belongs to the session that produced it. Late arrivals
        // (a stream finishing, a delegation result) must land there even if
        // the user has since switched sessions — otherwise they bleed into
        // whatever chat happens to be open, including a brand-new one.
        if (sessionId && sessionId !== activeId) {
          if (!sessions.some((sess) => sess.id === sessionId)) return
          set((s) => ({
            sessions: s.sessions.map((sess) =>
              sess.id === sessionId
                ? { ...sess, history: [...sess.history, msg] }
                : sess,
            ),
          }))
          return
        }

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

      deleteMessage(index) {
        const { activeId, sessions } = get()
        if (!activeId) return
        set(() => {
          const updated = sessions.map((sess) =>
            sess.id === activeId
              ? { ...sess, history: sess.history.filter((_, i) => i !== index) }
              : sess,
          )
          const currentHistory = updated.find((s) => s.id === activeId)?.history ?? []
          return { sessions: updated, history: currentHistory }
        })
      },
    }),
    {
      name: 'yapoc-sessions',
      version: 2,
      // Drop any stale/bloated/corrupt persisted payload from older schemas.
      // We never try to salvaged giant histories — a clean default is safer
      // and guarantees the quota-error loop can't resurrect itself.
      migrate: (persistedState) => {
        const state = persistedState as Partial<SessionStore> | null | undefined
        if (
          !state ||
          typeof state !== 'object' ||
          !Array.isArray(state.sessions)
        ) {
          return { sessions: [], activeId: null }
        }
        // Sanitize each restored session to the slim shape; drop heavy parts
        // and previewUrl so a re-save can't re-bloat past quota.
        return {
          sessions: (state.sessions as unknown as Session[]).map((s) => ({
            id: s?.id ?? crypto.randomUUID(),
            name: s?.name ?? 'Session',
            createdAt: s?.createdAt ?? new Date().toISOString(),
            ...(s?.source ? { source: s.source } : {}),
            history: (Array.isArray(s?.history) ? s.history : [])
              .map((m) => {
                const slim: Record<string, unknown> = {
                  role: m?.role ?? 'assistant',
                  content: slimContent(m?.content),
                }
                if (Array.isArray(m?.attachments) && m.attachments.length) {
                  slim.attachments = m.attachments.map(({ previewUrl: _pv, ...a }) => a)
                }
                return slim
              })
              .slice(-MAX_PERSISTED_MESSAGES),
          })).slice(0, MAX_PERSISTED_SESSIONS),
          activeId: typeof state.activeId === 'string' ? state.activeId : null,
        }
      },
      // Persist only a lightweight projection: all 50 sessions' metadata and
      // message TEXT (content) plus attachments metadata, but NOT the heavy
      // execution-trace `parts` (tool inputs/results can be KBs), NOT the
      // `previewUrl` object-URLs (which are session-only blobs), and NOT more
      // than MAX_PERSISTED_MESSAGES messages per session. This caps localStorage
      // below the ~5MB quota even with sustained chat volume.
      partialize: (state) =>
        fitToBudget({
          sessions: state.sessions.slice(0, MAX_PERSISTED_SESSIONS).map((s) => ({
            id: s.id,
            name: s.name,
            createdAt: s.createdAt,
            ...(s.source ? { source: s.source } : {}),
            history: s.history.slice(-MAX_PERSISTED_MESSAGES).map((m) => {
              const slim: Record<string, unknown> = {
                role: m.role,
                content: slimContent(m.content),
              }
              if (m.attachments && m.attachments.length) {
                slim.attachments = m.attachments.map(({ previewUrl: _pv, ...a }) => a)
              }
              return slim
            }),
          })),
          activeId: state.activeId,
        }),
      storage: resilientStorage<PersistedState>(),
      // After hydration, re-derive top-level `history` from the restored active
      // session (previously it was persisted redundantly; now it is computed)
      // and drop any stale pendingChatInput.
      onRehydrateStorage: () => (state) => {
        if (!state) return
        if (state.activeId) {
          const s = state.sessions.find((x) => x.id === state.activeId)
          state.history = s ? s.history : []
        }
        state.pendingChatInput = null
      },
    },
  ),
)
