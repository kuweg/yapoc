import type { TaskPart } from '../api/types'

/**
 * Pre-process a TaskPart[] to group consecutive tool calls with the same name.
 * This is a render-time transform — does not mutate the original array.
 *
 * Example: [tool(file_read), tool(file_read), tool(file_read), tool(file_write), tool(file_read)]
 *   → [grouped(file_read ×3), tool(file_write), tool(file_read)]
 */
export interface ToolCallGroup {
  kind: 'tool_group'
  name: string
  calls: Array<{
    id: string
    input: Record<string, unknown>
    result?: string
    isError?: boolean
    done: boolean
  }>
}

export type GroupedPart = TaskPart | ToolCallGroup

export function groupParts(parts: TaskPart[]): GroupedPart[] {
  const result: GroupedPart[] = []

  let i = 0
  while (i < parts.length) {
    const part = parts[i]

    // Only group tool parts
    if (part.kind !== 'tool') {
      result.push(part)
      i++
      continue
    }

    // Narrow the type — we know part.kind === 'tool' at this point
    const tool = part as Extract<TaskPart, { kind: 'tool' }>

    // Check if consecutive parts have the same tool name
    const groupCalls: typeof result[number] & { kind: 'tool_group' } = {
      kind: 'tool_group',
      name: tool.name,
      calls: [
        {
          id: tool.id,
          input: tool.input,
          result: tool.result,
          isError: tool.isError,
          done: tool.done,
        },
      ],
    }

    i++
    while (i < parts.length && parts[i].kind === 'tool' && (parts[i] as Extract<TaskPart, { kind: 'tool' }>).name === groupCalls.name) {
      const next = parts[i] as Extract<TaskPart, { kind: 'tool' }>
      groupCalls.calls.push({
        id: next.id,
        input: next.input,
        result: next.result,
        isError: next.isError,
        done: next.done,
      })
      i++
    }

    // Only group if there are 2+ consecutive same-name calls
    if (groupCalls.calls.length >= 2) {
      result.push(groupCalls)
    } else {
      // Single tool call — push as individual
      result.push(part)
    }
  }

  return result
}
