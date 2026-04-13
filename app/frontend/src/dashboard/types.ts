export type TicketStatus = 'backlog' | 'in_progress' | 'done' | 'error'
export type TicketType = 'user' | 'agent'

export interface TraceEntry {
  ts: string
  note: string
  agent: string | null
}

export interface Ticket {
  id: string
  type: TicketType
  title: string
  description: string
  requirements: string
  status: TicketStatus
  assigned_agent: string | null
  parent_agent: string | null   // which agent spawned this task
  created_at: string
  updated_at: string
  trace: TraceEntry[]
  // Agent-task-only fields
  agent_name?: string
  task_text?: string
  result_text?: string
  error_text?: string
}

export interface FileNode {
  name: string
  path: string
  is_dir: boolean
  children?: FileNode[]
}

export interface ColumnDef {
  id: TicketStatus
  label: string
  accent: string
}

export const COLUMNS: ColumnDef[] = [
  { id: 'backlog',     label: 'Backlog',      accent: '#8B949E' },
  { id: 'in_progress', label: 'In Progress',  accent: '#D29922' },
  { id: 'done',        label: 'Done',         accent: '#3FB950' },
  { id: 'error',       label: 'Error',        accent: '#F85149' },
]
