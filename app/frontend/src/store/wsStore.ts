/**
 * WebSocket notification store — receives and dispatches real-time events.
 *
 * Events from the backend WebSocket:
 * - state_sync: initial task list on connect
 * - task_created / task_update / task_complete / task_error: task lifecycle
 * - session_event: agent thinking/tool/text events for a specific session
 * - approval_needed: CONFIRM-tier tool awaiting user decision (background tasks)
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

export interface PendingApproval {
  id: string
  agent: string
  tool: string
  input_json: string
  created_at: string
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
  pendingApprovals: PendingApproval[]
  lastSessionEvent: SessionEventEnvelope | null
  /** Notifications the user hasn't seen yet */
  unreadNotifications: BackgroundTask[]
  /** Most recent task_complete event (for ChatPanel to pick up) */
  lastCompletedTask: BackgroundTask | null

  setConnected: (v: boolean) => void
  handleEvent: (data: Record<string, unknown>) => void
  dismissNotification: (taskId: string) => void
  clearApproval: (id: string) => void
  clearLastCompletedTask: () => void
}

export const useWsStore = create<WsStore>((set) => ({
  connected: false,
  backgroundTasks: [],
  pendingApprovals: [],
  lastSessionEvent: null,
  unreadNotifications: [],
  lastCompletedTask: null,

  setConnected: (v) => set({ connected: v }),

  dismissNotification: (taskId) =>
    set((s) => ({
      unreadNotifications: s.unreadNotifications.filter((n) => n.task_id !== taskId),
    })),

  clearApproval: (id) =>
    set((s) => ({
      pendingApprovals: s.pendingApprovals.filter((a) => a.id !== id),
    })),

  clearLastCompletedTask: () => set({ lastCompletedTask: null }),

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
      // Initial batch of recent tasks + pending approvals on connect
      const tasks = (data.tasks ?? []) as BackgroundTask[]
      const approvals = (data.pending_approvals ?? []) as PendingApproval[]
      set({ backgroundTasks: tasks, pendingApprovals: approvals })
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

    if (type === 'approval_needed') {
      const approval = data as unknown as PendingApproval
      set((s) => ({
        pendingApprovals: [...s.pendingApprovals, approval],
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

    // pong, subscribed, unsubscribed — ignore silently
  },
}))
