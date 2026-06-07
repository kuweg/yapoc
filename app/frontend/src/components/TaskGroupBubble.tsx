import { useState } from 'react'
import { MessageBubble } from './MessageBubble'
import { ThinkingBlock } from './ThinkingBlock'
import { ToolCallBlock } from './ToolCallBlock'
import { GroupedToolCallBlock } from './GroupedToolCallBlock'
import { groupParts } from './groupParts'
import { AgentAvatar, getAgentColor, getAgentDisplayName, withAlpha } from '../lib/agentIdentity'
import { CompactionMarker } from './ContextGauge'
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

interface Delegation {
  agent: string
  task: string
  result?: string
  isError?: boolean
  done: boolean
}

/** Pull the A→B handoffs out of a task group's parts (spawn_agent calls). */
function extractDelegations(parts: TaskPart[]): Delegation[] {
  const out: Delegation[] = []
  for (const p of parts) {
    if (p.kind === 'tool' && p.name === 'spawn_agent') {
      const input = (p.input || {}) as Record<string, unknown>
      out.push({
        agent: String(input.agent_name ?? input.name ?? '?'),
        task: String(input.task ?? input.prompt ?? ''),
        result: p.result,
        isError: p.isError,
        done: p.done,
      })
    }
  }
  return out
}

/** One child agent in the delegation tree: identity + task + threaded result. */
function DelegationNode({ d, idx }: { d: Delegation; idx: number }) {
  const [open, setOpen] = useState(false)
  const color = getAgentColor(d.agent)
  return (
    <div className="pl-3 ml-1 border-l-2" style={{ borderColor: withAlpha(color, 0.4) }}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 w-full text-left py-1 px-1 rounded hover:bg-zinc-800/40 transition-colors"
      >
        <span className="text-zinc-600 text-xs flex-shrink-0">↳</span>
        <AgentAvatar name={d.agent} size={16} />
        <span className="text-xs font-semibold flex-shrink-0" style={{ color }}>{getAgentDisplayName(d.agent)}</span>
        <span className="text-xs text-zinc-400 truncate flex-1">{d.task}</span>
        {!d.done ? (
          <span className="animate-spin inline-block text-xs flex-shrink-0">⟳</span>
        ) : d.isError ? (
          <span className="text-red-400 text-xs flex-shrink-0">⚠</span>
        ) : (
          <span className="text-green-400 text-xs flex-shrink-0">✓</span>
        )}
        <span className="text-zinc-600 text-[10px] flex-shrink-0">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="pl-6 pb-2 pr-1 text-xs whitespace-pre-wrap break-words" key={`del-body-${idx}`}>
          {d.task && (
            <div className="mb-1 text-zinc-400"><span className="text-zinc-600">task: </span>{d.task}</div>
          )}
          {d.result ? (
            <div className={d.isError ? 'text-red-300' : 'text-zinc-300'}>
              <span className="text-zinc-600">result: </span>{d.result}
            </div>
          ) : (
            <div className="text-zinc-600 italic">awaiting result…</div>
          )}
        </div>
      )}
    </div>
  )
}

export function TaskGroupBubble({ group, masterModel }: TaskGroupBubbleProps) {
  const [expanded, setExpanded] = useState(true)

  const stepCount = group.parts.length
  const delegations = extractDelegations(group.parts)
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
        {delegations.length > 0 && (
          <span className="flex items-center -space-x-1 ml-1" title={`Delegated to ${delegations.map((d) => d.agent).join(', ')}`}>
            {delegations.slice(0, 4).map((d, i) => (
              <AgentAvatar key={`hdr-${group.id}-${i}`} name={d.agent} size={15} />
            ))}
            {delegations.length > 4 && <span className="text-[10px] text-zinc-500 pl-1.5">+{delegations.length - 4}</span>}
          </span>
        )}
        <span className="text-xs text-zinc-500 ml-1">({stepCount} steps)</span>
        <span className="ml-auto text-zinc-500 text-xs">{expanded ? '▲' : '▼'}</span>
      </button>

      {expanded && (
        <div className="px-4 pb-3 space-y-1 border-t border-zinc-700/50 pt-2">
          {delegations.length > 0 && (
            <div className="mb-2 rounded-lg bg-zinc-900/50 border border-zinc-800 p-1.5">
              <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-0.5 pl-1">
                Delegated to {delegations.length} agent{delegations.length > 1 ? 's' : ''}
              </div>
              {delegations.map((d, i) => (
                <DelegationNode key={`del-${group.id}-${i}`} d={d} idx={i} />
              ))}
            </div>
          )}
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
              if (part.kind === 'compact') {
                return <CompactionMarker key={part.id} tokensBefore={part.tokensBefore} tokensAfter={part.tokensAfter} reason={part.reason} />
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
