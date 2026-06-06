import { useState } from 'react'
import { MessageBubble } from './MessageBubble'
import { ThinkingBlock } from './ThinkingBlock'
import { ToolCallBlock } from './ToolCallBlock'
import { GroupedToolCallBlock } from './GroupedToolCallBlock'
import { groupParts } from './groupParts'
import type { TaskPart } from '../api/types'

export type { TaskPart }
export interface TaskGroup {
  id: string
  parts: TaskPart[]
  finalText: string
  status: 'running' | 'done' | 'error'
}

interface TaskGroupBubbleProps {
  group: TaskGroup
  masterModel?: string
}

export function TaskGroupBubble({ group, masterModel }: TaskGroupBubbleProps) {
  const [expanded, setExpanded] = useState(true)

  const stepCount = group.parts.length
  const statusLabel =
    group.status === 'running'
      ? 'Running'
      : group.status === 'error'
        ? 'Failed'
        : 'Complete'

  return (
    <div className="rounded-xl border border-zinc-700 bg-zinc-900/60 my-2 overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-2 w-full px-4 py-2.5 text-left hover:bg-zinc-800/60 transition-colors"
      >
        {group.status === 'running' ? (
          <span className="animate-spin inline-block text-xs">⟳</span>
        ) : group.status === 'error' ? (
          <span className="text-red-400 text-xs">⚠</span>
        ) : (
          <span className="text-green-400 text-xs">✓</span>
        )}
        <span className="text-sm font-medium text-zinc-200">
          Task {statusLabel.toLowerCase()}
        </span>
        <span className="text-xs text-zinc-500 ml-1">({stepCount} steps)</span>
        <span className="ml-auto text-zinc-500 text-xs">{expanded ? '▲' : '▼'}</span>
      </button>

      {expanded && (
        <div className="px-4 pb-3 space-y-1 border-t border-zinc-700/50 pt-2">
          {(() => {
            const grouped = groupParts(group.parts)
            return grouped.map((part, i) => {
              if (part.kind === 'tool_group') {
                return <GroupedToolCallBlock key={`tg-${group.id}-grp-${i}`} name={part.name} calls={part.calls} />
              }
              if (part.kind === 'text') {
                return (
                  <MessageBubble
                    key={`tg-${group.id}-t-${i}`}
                    role="assistant"
                    content={part.text}
                    agentName="master"
                    agentModel={masterModel}
                  />
                )
              }
              if (part.kind === 'thinking') {
                return <ThinkingBlock key={part.id} text={part.text} done={part.done} />
              }
              return (
                <ToolCallBlock
                  key={part.id}
                  id={part.id}
                  name={part.name}
                  input={part.input}
                  result={part.result}
                  isError={part.isError}
                  done={part.done}
                />
              )
            })
          })()}

          {group.status === 'running' && (
            <div className="flex items-center gap-2 text-zinc-500 text-xs pl-1 py-1">
              <span className="animate-spin inline-block">⟳</span>
              <span>Waiting for background agents to finish…</span>
            </div>
          )}

          {group.finalText && group.status !== 'running' && (
            <div className="pt-2 border-t border-zinc-700/30 mt-2">
              <MessageBubble
                role="assistant"
                content={group.finalText}
                agentName="master"
                agentModel={masterModel}
              />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
