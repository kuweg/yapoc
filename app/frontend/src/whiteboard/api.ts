export type CardKind = 'note'|'decision'|'question'|'task'|'link'|'artifact'|'actor'|'component'|'service'|'api'|'database'|'queue'|'event'|'interface'|'module'|'boundary'|'external'
export type CardColor = 'amber'|'mint'|'blue'|'rose'|'violet'
export type Relationship = 'related'|'depends_on'|'calls'|'reads'|'writes'|'emits'|'subscribes'|'contains'|'implements'|'extends'|'blocks'|'flows_to'
export type EdgeStyle = 'solid'|'dashed'|'dotted'
export interface CanvasInfo { id:string; name:string; description:string; created_by:string; created_at:string; updated_at:string; revision?:number; card_count?:number }
export interface BoardCard { id:string; board_id:string; kind:CardKind; title:string; body:string; color:CardColor; x:number; y:number; width:number; height:number; details:Record<string,unknown>; created_by:string; created_at:string; updated_at:string; revision:number }
export interface BoardEdge { id:string; board_id:string; source_id:string; target_id:string; relationship:Relationship; style:EdgeStyle; label:string; created_by:string; created_at:string }
export interface Board { canvas:CanvasInfo; revision:number; updated_at:string|null; cards:BoardCard[]; edges:BoardEdge[] }
export interface ExportResult { destination:string; filename?:string; mime?:string; content?:string; path?:string; reference?:string; artifact_id?:string }

async function json<T>(response:Response):Promise<T>{if(!response.ok){const body=await response.json().catch(()=>null);throw new Error(body?.detail||`Request failed (${response.status})`)}return response.status===204?undefined as T:response.json()}
export const listBoards=()=>fetch('/api/whiteboard/boards').then(json<{boards:CanvasInfo[]}>).then(x=>x.boards)
export const getBoard=(boardId='main',signal?:AbortSignal)=>fetch(`/api/whiteboard/boards/${encodeURIComponent(boardId)}`,{signal}).then(json<Board>)
export const createBoard=(name:string,description='')=>fetch('/api/whiteboard/boards',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,description})}).then(json<CanvasInfo>)
export const renameBoard=(id:string,name:string,description:string)=>fetch(`/api/whiteboard/boards/${encodeURIComponent(id)}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,description})}).then(json<CanvasInfo>)
export const deleteBoard=(id:string)=>fetch(`/api/whiteboard/boards/${encodeURIComponent(id)}`,{method:'DELETE'}).then(json<void>)
export const createCard=(card:Partial<BoardCard>&Pick<BoardCard,'title'>)=>fetch('/api/whiteboard/cards',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(card)}).then(json<BoardCard>)
export const updateCard=(card:BoardCard,changes:Partial<BoardCard>)=>fetch(`/api/whiteboard/cards/${card.id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({...changes,revision:card.revision})}).then(json<BoardCard>)
export const deleteCard=(id:string)=>fetch(`/api/whiteboard/cards/${id}`,{method:'DELETE'}).then(json<void>)
export const createEdge=(edge:Pick<BoardEdge,'board_id'|'source_id'|'target_id'|'relationship'|'style'|'label'>)=>fetch('/api/whiteboard/edges',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(edge)}).then(json<BoardEdge>)
export const deleteEdge=(id:string)=>fetch(`/api/whiteboard/edges/${id}`,{method:'DELETE'}).then(json<void>)
export const exportBoard=(id:string,format:'markdown'|'mermaid'|'json',destination:'download'|'notes'|'workspace'|'artifact')=>fetch(`/api/whiteboard/boards/${encodeURIComponent(id)}/export`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({format,destination})}).then(json<ExportResult>)
