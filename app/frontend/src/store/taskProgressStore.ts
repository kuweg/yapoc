import { create } from 'zustand'
import type { QueuedTask } from '../api/client'

type Progress = NonNullable<QueuedTask['progress']>
export const useTaskProgressStore = create<{ byId: Record<string, Progress>; ingest: (tasks: QueuedTask[]) => void }>(set => ({
  byId: {},
  ingest: tasks => set(current => {
    const next = { ...current.byId }
    for (const task of tasks) if (task.progress) next[task.id] = task.progress
    return { byId: Object.fromEntries(Object.entries(next).slice(-200)) }
  }),
}))
