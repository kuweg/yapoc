import type { TaskDetail as TaskDetailType } from '../../types'
import { TimestampCell } from '../shared/TimestampCell'

interface Props {
  task: TaskDetailType | null
}

export function TaskDetail({ task }: Props) {
  if (!task) {
    return (
      <div className="px-4 py-6 text-center text-sm text-[#484F58]">
        No active task
      </div>
    )
  }

  const statusColor = task.status === 'done'
    ? 'text-[#3FB950]'
    : task.status === 'error'
    ? 'text-[#F85149]'
    : task.status === 'in_progress'
    ? 'text-[#FFB633]'
    : 'text-[#8B949E]'

  return (
    <div className="space-y-3">
      {/* Metadata */}
      <div className="flex flex-wrap gap-3 text-xs">
        <span>
          <span className="text-[#484F58]">Status: </span>
          <span className={`font-medium ${statusColor}`}>{task.status}</span>
        </span>
        {task.assigned_by && (
          <span>
            <span className="text-[#484F58]">Assigned by: </span>
            <span className="text-[#8B949E] font-mono">{task.assigned_by}</span>
          </span>
        )}
        <span>
          <span className="text-[#484F58]">Assigned: </span>
          <TimestampCell timestamp={task.assigned_at} />
        </span>
        {task.completed_at && (
          <span>
            <span className="text-[#484F58]">Completed: </span>
            <TimestampCell timestamp={task.completed_at} />
          </span>
        )}
      </div>

      {/* Task text */}
      {task.task_text && (
        <div>
          <p className="text-[10px] uppercase tracking-widest text-[#484F58] mb-1">Task</p>
          <pre className="text-xs text-[#E6EDF3] bg-[#0D1117] border border-[#21262D] rounded p-3
            whitespace-pre-wrap break-words font-mono leading-relaxed">
            {task.task_text}
          </pre>
        </div>
      )}

      {/* Result */}
      {task.result_text && (
        <div>
          <p className="text-[10px] uppercase tracking-widest text-[#484F58] mb-1">Result</p>
          <pre className="text-xs text-[#3FB950] bg-[#0D1117] border border-[#1A3A2A] rounded p-3
            whitespace-pre-wrap break-words font-mono leading-relaxed max-h-48 overflow-y-auto">
            {task.result_text}
          </pre>
        </div>
      )}

      {/* Error */}
      {task.error_text && (
        <div>
          <p className="text-[10px] uppercase tracking-widest text-[#484F58] mb-1">Error</p>
          <pre className="text-xs text-[#F85149] bg-[#0D1117] border border-[#3D1A1A] rounded p-3
            whitespace-pre-wrap break-words font-mono leading-relaxed max-h-48 overflow-y-auto">
            {task.error_text}
          </pre>
        </div>
      )}
    </div>
  )
}
