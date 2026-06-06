/** Agent activity event — chat-like message for the agent flow panel */
export interface AgentActivityLog {
  agent_name: string
  timestamp: string
  type: 'tool_call' | 'tool_result' | 'llm_output' | 'error' | 'system' | 'delegation' | 'thinking'
  content: string
  metadata?: Record<string, unknown>
}

/** Per-agent activity message type colors (left border accent) */
export const ACTIVITY_TYPE_COLORS: Record<AgentActivityLog['type'], string> = {
  tool_call: '#3b82f6',    // blue
  tool_result: '#22c55e',  // green
  llm_output: '#a855f7',   // purple
  error: '#ef4444',        // red
  system: '#6b7280',       // gray
  delegation: '#f97316',   // orange
  thinking: '#06b6d4',     // cyan
}

export const ACTIVITY_TYPE_LABELS: Record<AgentActivityLog['type'], string> = {
  tool_call: 'Tool Call',
  tool_result: 'Tool Result',
  llm_output: 'LLM Output',
  error: 'Error',
  system: 'System',
  delegation: 'Delegation',
  thinking: 'Thinking',
}

/** Per-agent name badge colors */
export const AGENT_NAME_COLORS: Record<string, string> = {
  builder: '#3b82f6',     // blue
  planning: '#22c55e',    // green
  keeper: '#f97316',      // orange
  evaluator: '#a855f7',   // purple
  doctor: '#ef4444',      // red
  cron: '#14b8a6',        // teal
  researcher: '#06b6d4',  // cyan
  librarian: '#eab308',   // gold
  master: '#8b5cf6',      // violet
  default: '#6b7280',     // gray fallback
}

export function getAgentColor(name: string): string {
  return AGENT_NAME_COLORS[name.toLowerCase()] ?? AGENT_NAME_COLORS.default
}
