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

// Per-agent name colors are canonical in lib/agentIdentity (single source of
// truth). Re-export so existing importers get the consolidated palette + the
// stable hash fallback for dynamic agents.
export { getAgentColor } from '../lib/agentIdentity'
