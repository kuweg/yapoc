/**
 * WebSocket notification store — receives and dispatches real-time events.
 *
 * Events from the backend WebSocket:
 * - state_sync: initial task list on connect
 * - task_created / task_update / task_complete / task_error: task lifecycle
 * - session_event: agent thinking/tool/text events for a specific session
 */
import { create } from 'zustand'

export interface BackgroundTask {
  task_id: string
  status: string
  prompt?: string
  result?: string
  error?: string
  source?: string
  session_id?: string
  created_at?: string
  started_at?: string
  completed_at?: string
}

export interface SessionEvent {
  type: string
  agent: string
  timestamp: string
  [key: string]: unknown
}

export interface SessionEventEnvelope {
  session_id: string
  event: SessionEvent
}

interface WsStore {
  connected: boolean
  backgroundTasks: BackgroundTask[]
  lastSessionEvent: SessionEventEnvelope | null
  /** Notifications the user hasn't seen yet */
  unreadNotifications: BackgroundTask[]
  /** Most recent task_complete event (for ChatPanel to pick up) */
  lastCompletedTask: BackgroundTask | null
  /** Orphan notification result — fired when the backend couldn't route to a
   * specific session because session_id was lost upstream. ChatPanel falls
   * back to showing this in the active chat when awaiting a notification. */
  lastOrphanNotification: { text: string } | null

  setConnected: (v: boolean) => void
  handleEvent: (data: Record<string, unknown>) => void
  dismissNotification: (taskId: string) => void
  clearLastCompletedTask: () => void
  clearLastOrphanNotification: () => void
}

export const useWsStore = create<WsStore>((set) => ({
  connected: false,
  backgroundTasks: [],
  lastSessionEvent: null,
  unreadNotifications: [],
  lastCompletedTask: null,
  lastOrphanNotification: null,

  setConnected: (v) => set({ connected: v }),

  dismissNotification: (taskId) =>
    set((s) => ({
      unreadNotifications: s.unreadNotifications.filter((n) => n.task_id !== taskId),
    })),

  clearLastCompletedTask: () => set({ lastCompletedTask: null }),

  clearLastOrphanNotification: () => set({ lastOrphanNotification: null }),

  handleEvent: (data) => {
    const type = data.type as string

    const upsertTask = (tasks: BackgroundTask[], next: BackgroundTask): BackgroundTask[] => {
      const idx = tasks.findIndex((t) => t.task_id === next.task_id)
      if (idx >= 0) {
        const updated = [...tasks]
        updated[idx] = { ...updated[idx], ...next }
        return updated
      }
      return [next, ...tasks].slice(0, 100)
    }

    if (type === 'state_sync') {
      // Initial batch of recent tasks on connect
      const tasks = (data.tasks ?? []) as BackgroundTask[]
      set({ backgroundTasks: tasks })
      return
    }

    if (type === 'task_created') {
      const task = (data.task ?? data) as BackgroundTask
      if (!task.task_id && data.task_id) {
        task.task_id = data.task_id as string
      }
      set((s) => ({
        backgroundTasks: [task, ...s.backgroundTasks].slice(0, 100),
      }))
      return
    }

    if (type === 'task_update') {
      const taskId = data.task_id as string
      const patch: BackgroundTask = {
        ...(data as unknown as BackgroundTask),
        task_id: taskId,
      }
      set((s) => ({
        backgroundTasks: upsertTask(s.backgroundTasks, patch),
      }))
      return
    }

    if (type === 'task_complete') {
      const taskId = data.task_id as string
      const completed: BackgroundTask = {
        task_id: taskId,
        status: 'done',
        result: data.result as string | undefined,
        completed_at: data.completed_at as string | undefined,
        source: data.source as string | undefined,
        session_id: data.session_id as string | undefined,
      }
      set((s) => ({
        backgroundTasks: upsertTask(s.backgroundTasks, completed),
        unreadNotifications: [completed, ...s.unreadNotifications],
        lastCompletedTask: completed,
      }))
      return
    }

    if (type === 'task_error') {
      const taskId = data.task_id as string
      const errTask: BackgroundTask = {
        task_id: taskId,
        status: data.status as string ?? 'error',
        error: data.error as string | undefined,
        completed_at: data.completed_at as string | undefined,
        source: data.source as string | undefined,
        session_id: data.session_id as string | undefined,
      }
      set((s) => ({
        backgroundTasks: upsertTask(s.backgroundTasks, errTask),
        unreadNotifications: [errTask, ...s.unreadNotifications],
      }))
      return
    }

    if (type === 'session_event') {
      const sessionId = String(data.session_id ?? '')
      const event = (data.event ?? null) as SessionEvent | null
      if (!sessionId || !event) return
      set({ lastSessionEvent: { session_id: sessionId, event } })
      return
    }

    if (type === 'notification_result') {
      // Top-level broadcast from the master notification watcher when the
      // result couldn't be scoped to a specific session (session_id was
      // lost somewhere up the agent chain). ChatPanel will surface this.
      const text = String(data.text ?? '').trim()
      if (text) set({ lastOrphanNotification: { text } })
      return
    }

    // pong, subscribed, unsubscribed — ignore silently
  },
}))
