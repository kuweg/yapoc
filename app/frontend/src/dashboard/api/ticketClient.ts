import type { Ticket, TicketStatus } from '../types'

const BASE = '/api/tickets'

export async function getTickets(): Promise<Ticket[]> {
  const res = await fetch(BASE)
  if (!res.ok) throw new Error(`tickets ${res.status}`)
  return res.json()
}

export async function createTicket(data: {
  title: string
  description?: string
  requirements?: string
}): Promise<Ticket> {
  const res = await fetch(BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`create ticket ${res.status}`)
  return res.json()
}

export async function updateTicket(
  id: string,
  data: { title?: string; description?: string; requirements?: string; status?: TicketStatus }
): Promise<Ticket> {
  const res = await fetch(`${BASE}/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`update ticket ${res.status}`)
  return res.json()
}

export async function deleteTicket(id: string): Promise<void> {
  const res = await fetch(`${BASE}/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`delete ticket ${res.status}`)
}

export async function addTrace(id: string, note: string, agent?: string): Promise<Ticket> {
  const res = await fetch(`${BASE}/${id}/trace`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ note, agent: agent ?? null }),
  })
  if (!res.ok) throw new Error(`add trace ${res.status}`)
  return res.json()
}

export async function assignTicket(id: string, agentName: string): Promise<Ticket> {
  const res = await fetch(`${BASE}/${id}/assign`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent_name: agentName }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `assign ticket ${res.status}`)
  }
  return res.json()
}
