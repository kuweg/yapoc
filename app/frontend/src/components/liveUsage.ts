import type { StreamEvent, UsageEvent } from '../api/types'

export type LiveUsage = UsageEvent & { estimated?: boolean; inputKnown?: boolean }

/** Display-only estimates; never used for billing or budget enforcement. */
export function createLiveUsage(previous?: LiveUsage | null) {
  let chars = 0
  let started = 0
  let newResponse = true
  let current: LiveUsage = previous ?? {
    type: 'usage_stats', input_tokens: 0, output_tokens: 0,
    tokens_per_second: 0, context_window: 0, estimated: true, inputKnown: false,
  }
  return (event: StreamEvent | { type: 'turn_start' }, now = performance.now()): LiveUsage | null => {
    if (event.type === 'turn_start') {
      newResponse = true
      current = { ...current, output_tokens: 0, tokens_per_second: 0, estimated: true }
    } else if (event.type === 'usage_stats') {
      current = { ...event, estimated: false, inputKnown: true }
      newResponse = true
    } else if (event.type === 'text' || event.type === 'thinking') {
      if (newResponse) {
        chars = 0
        started = now
        newResponse = false
      }
      chars += Array.from(event.text).length
      const output = Math.ceil(chars / 4)
      current = { ...current, output_tokens: output, estimated: true,
        tokens_per_second: (now - started) >= 250 ? output / ((now - started) / 1000) : 0 }
    } else if (event.type === 'compact') {
      current = { ...current, input_tokens: event.tokens_after, inputKnown: true, estimated: true }
    } else if (event.type === 'tool_start' || event.type === 'status') {
      current = { ...current, tokens_per_second: 0 }
    } else {
      return null
    }
    return current
  }
}
