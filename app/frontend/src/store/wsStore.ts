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

interface WsStore {
  connected: boolean
  backgroundTasks: BackgroundTask[]
  pendingApprovals: PendingApproval[]
  /** Notifications the user hasn't seen yet */
  unreadNotifications: BackgroundTask[]
  /** Most recent task_complete event (for ChatPanel to pick up) */
  lastCompletedTask: BackgroundTask | null

  setConnected: (v: boolean) => void
  handleEvent: (data: Record<string, unknown>) => void
  dismissNotification: (taskId: string) => void
  clearApproval: (id: string) => void
}

export const useWsStore = create<WsStore>((set) => ({
  connected: false,
  backgroundTasks: [],
  pendingApprovals: [],
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

  handleEvent: (data) => {
    const type = data.type as string

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
      set((s) => ({
        backgroundTasks: s.backgroundTasks.map((t) =>
          t.task_id === taskId ? { ...t, ...data, task_id: taskId } : t,
        ),
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
      }
      set((s) => ({
        backgroundTasks: s.backgroundTasks.map((t) =>
          t.task_id === taskId ? { ...t, ...completed } : t,
        ),
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
      }
      set((s) => ({
        backgroundTasks: s.backgroundTasks.map((t) =>
          t.task_id === taskId ? { ...t, ...errTask } : t,
        ),
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

    // pong, subscribed, unsubscribed — ignore silently
  },
}))
