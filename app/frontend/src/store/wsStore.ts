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
  agent?: string
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

export interface AgentEvent {
  type: string
  agent: string
  timestamp: string
  [key: string]: unknown
}

/** Per-agent ring buffer cap — mirrors the backend's relay buffer. */
export const AGENT_EVENTS_MAX = 500

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
  /** Per-agent live event buffer (bounded — see AGENT_EVENTS_MAX). */
  agentEvents: Record<string, AgentEvent[]>
  /** Agents the UI has asked to subscribe to. The useWebSocket hook
   *  reconciles this against the open WS by sending subscribe_agent /
   *  unsubscribe_agent frames. */
  subscribedAgents: string[]

  setConnected: (v: boolean) => void
  handleEvent: (data: Record<string, unknown>) => void
  dismissNotification: (taskId: string) => void
  clearLastCompletedTask: () => void
  clearLastOrphanNotification: () => void
  /** Replace the buffer with a fresh snapshot (used after HTTP hydration). */
  setAgentEvents: (agent: string, events: AgentEvent[]) => void
  /** Drop everything we have for an agent. */
  clearAgentEvents: (agent: string) => void
  subscribeAgent: (agent: string) => void
  unsubscribeAgent: (agent: string) => void
}

/** Recover a completion that may have landed while the WebSocket was down
 *  (e.g. during a backend restart/reconnect gap). The state_sync batch is
 *  newest-first, so scanning for the first meaningful completed task yields
 *  the most recent recoverable completion. Only returns tasks that are
 *  "done" with a non-empty result, or in an error-ish terminal state. */
const RECOVER_WINDOW_MS = 10 * 60 * 1000 // 10 minutes

// Completions already surfaced to the UI. state_sync replays recent tasks on
// EVERY reconnect, so without this the same finished task is appended to the
// chat again after each blip — visible as old results reappearing in a fresh
// conversation.
const surfacedCompletions = new Set<string>()

function findRecoverableCompletion(tasks: BackgroundTask[]): BackgroundTask | null {
  const now = Date.now()
  for (const task of tasks ?? []) {
    const id = task.task_id ?? (task as BackgroundTask & { id?: string }).id
    if (id && surfacedCompletions.has(id)) continue
    const status = (task.status ?? '').toLowerCase()
    const isError = status === 'error' || status === 'failed'
    const isDone = status === 'done'
    const hasMeaningfulResult = isDone && !!task.result && task.result.trim().length > 0
    if (!isError && !hasMeaningfulResult) continue

    // Recency guard — avoid surfacing stale historical completions on every
    // page load. Missing/unparseable timestamps default to "recent".
    const rawTs = task.completed_at ?? task.created_at
    if (rawTs) {
      const ms = Date.parse(rawTs)
      if (!Number.isNaN(ms) && now - ms > RECOVER_WINDOW_MS) continue
    }

    if (id) surfacedCompletions.add(id)
    return {
      task_id: task.task_id,
      status: task.status,
      result: task.result,
      error: task.error,
      source: task.source,
      prompt: task.prompt,
      agent: task.agent,
      session_id: task.session_id,
      completed_at: task.completed_at,
    }
  }
  return null
}

export const useWsStore = create<WsStore>((set) => ({
  connected: false,
  backgroundTasks: [],
  lastSessionEvent: null,
  unreadNotifications: [],
  lastCompletedTask: null,
  lastOrphanNotification: null,
  agentEvents: {},
  subscribedAgents: [],

  setConnected: (v) => set({ connected: v }),

  dismissNotification: (taskId) =>
    set((s) => ({
      unreadNotifications: s.unreadNotifications.filter((n) => n.task_id !== taskId),
    })),

  clearLastCompletedTask: () => set({ lastCompletedTask: null }),

  clearLastOrphanNotification: () => set({ lastOrphanNotification: null }),

  setAgentEvents: (agent, events) =>
    set((s) => ({
      agentEvents: {
        ...s.agentEvents,
        [agent]: events.slice(-AGENT_EVENTS_MAX),
      },
    })),

  clearAgentEvents: (agent) =>
    set((s) => {
      if (!(agent in s.agentEvents)) return s
      const { [agent]: _drop, ...rest } = s.agentEvents
      return { agentEvents: rest }
    }),

  subscribeAgent: (agent) =>
    set((s) =>
      s.subscribedAgents.includes(agent)
        ? s
        : { subscribedAgents: [...s.subscribedAgents, agent] }
    ),

  unsubscribeAgent: (agent) =>
    set((s) =>
      s.subscribedAgents.includes(agent)
        ? { subscribedAgents: s.subscribedAgents.filter((a) => a !== agent) }
        : s
    ),

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
      // Initial batch of recent tasks on connect.
      // These come straight from the task_queue table, which names the primary
      // key `id` — every live event uses `task_id`. Without normalising, a
      // synced row can never be matched by a later task_update/task_complete
      // upsert, so a task that finishes just after connect stays "running"
      // forever, and React sees a list of undefined keys.
      const tasks = ((data.tasks ?? []) as Array<BackgroundTask & { id?: string }>).map((t) => ({
        ...t,
        task_id: t.task_id ?? t.id ?? '',
      })) as BackgroundTask[]
      // A completion may have landed during a reconnect gap (e.g. server
      // restart) and thus never fired a live task_complete WS event. Surface
      // the most recent meaningful completion so ChatPanel still renders it.
      const completedTask = findRecoverableCompletion(tasks)
      set(
        completedTask
          ? { backgroundTasks: tasks, lastCompletedTask: completedTask }
          : { backgroundTasks: tasks }
      )
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
        prompt: data.prompt as string | undefined,
        agent: data.agent as string | undefined,
        session_id: data.session_id as string | undefined,
      }
      // Record it as surfaced. Without this, only findRecoverableCompletion
      // marked ids, so a task shown live was still "unseen" to the state_sync
      // replay that runs on EVERY reconnect — and reappeared as a second (and
      // third) completion card.
      if (taskId) surfacedCompletions.add(taskId)
      set((s) => ({
        backgroundTasks: upsertTask(s.backgroundTasks, completed),
        unreadNotifications: [completed, ...s.unreadNotifications],
        lastCompletedTask: completed,
      }))
      return
    }

    if (type === 'task_error') {
      const taskId = data.task_id as string
      const rawError = data.error as string | undefined
      // Normalize "unknown" / empty errors so the task group still completes
      const cleanedError = rawError?.trim() && rawError !== 'unknown' ? rawError.trim() : 'Task failed — check agent health logs'
      const errTask: BackgroundTask = {
        task_id: taskId,
        status: data.status as string ?? 'error',
        error: cleanedError,
        completed_at: data.completed_at as string | undefined,
        source: data.source as string | undefined,
        prompt: data.prompt as string | undefined,
        agent: data.agent as string | undefined,
        session_id: data.session_id as string | undefined,
      }
      set((s) => ({
        backgroundTasks: upsertTask(s.backgroundTasks, errTask),
        unreadNotifications: [errTask, ...s.unreadNotifications],
        lastCompletedTask: errTask,
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

    if (type === 'agent_event') {
      const agent = String(data.agent ?? '')
      const event = (data.event ?? null) as AgentEvent | null
      if (!agent || !event) return
      set((s) => {
        const existing = s.agentEvents[agent] ?? []
        const next = [...existing, event]
        if (next.length > AGENT_EVENTS_MAX) next.splice(0, next.length - AGENT_EVENTS_MAX)
        return { agentEvents: { ...s.agentEvents, [agent]: next } }
      })
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
