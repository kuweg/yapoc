export interface NoteSummary {
  id: string
  title: string
  path: string
  revision: string
  updated_at: string
  links: string[]
  excerpt: string
}
export interface Note extends NoteSummary { content: string }
async function request<T>(path = '', init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/notes${path}`, init)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Notes request failed (${response.status})`)
  return body as T
}
const json = (method: string, body: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
export const listNotes = () => request<{ notes: NoteSummary[]; skipped: string[] }>()
export const readNote = (id: string) => request<Note>(`/${encodeURIComponent(id)}`)
export const createNote = (title: string, content?: string) => request<Note>('', json('POST', { title, content }))
export const saveNote = (id: string, content: string, revision: string) => request<Note>(`/${encodeURIComponent(id)}`, json('PUT', { content, revision }))
export const trashNote = (id: string, revision: string) => request(`/${encodeURIComponent(id)}/trash`, json('POST', { revision }))
export const noteTarget = (target: string) => target.split('#')[0].replace(/^\.\//, '').replace(/\.md$/i, '').trim().toLocaleLowerCase()
export const findNote = (notes: NoteSummary[], target: string) => notes.find(note => noteTarget(note.id) === noteTarget(target))
