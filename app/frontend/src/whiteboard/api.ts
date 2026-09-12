export type CardKind = 'note' | 'decision' | 'question' | 'task' | 'link' | 'artifact'
export type CardColor = 'amber' | 'mint' | 'blue' | 'rose' | 'violet'
export interface BoardCard { id: string; kind: CardKind; title: string; body: string; color: CardColor; x: number; y: number; created_by: string; created_at: string; updated_at: string; revision: number }
export interface BoardEdge { id: string; source_id: string; target_id: string; label: string; created_by: string; created_at: string }
export interface Board { revision: number; updated_at: string | null; cards: BoardCard[]; edges: BoardEdge[] }

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(body?.detail || `Request failed (${response.status})`) }
  return response.status === 204 ? undefined as T : response.json()
}
export const getBoard = (signal?: AbortSignal) => fetch('/api/whiteboard', { signal }).then(json<Board>)
export const createCard = (card: Partial<BoardCard> & Pick<BoardCard, 'title'>) => fetch('/api/whiteboard/cards', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(card) }).then(json<BoardCard>)
export const updateCard = (card: BoardCard, changes: Partial<BoardCard>) => fetch(`/api/whiteboard/cards/${card.id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ ...changes, revision: card.revision }) }).then(json<BoardCard>)
export const deleteCard = (id: string) => fetch(`/api/whiteboard/cards/${id}`, { method: 'DELETE' }).then(json<void>)
export const createEdge = (source_id: string, target_id: string) => fetch('/api/whiteboard/edges', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ source_id, target_id }) }).then(json<BoardEdge>)
export const deleteEdge = (id: string) => fetch(`/api/whiteboard/edges/${id}`, { method: 'DELETE' }).then(json<void>)
