import { useCallback, useEffect, useRef, useState } from 'react'
import { GitBranch, Link2, Plus, RefreshCw, Trash2, X } from 'lucide-react'
import { createCard, createEdge, deleteCard, deleteEdge, getBoard, updateCard, type Board, type BoardCard, type CardColor, type CardKind } from './api'

const EMPTY: Board = { revision: 0, updated_at: null, cards: [], edges: [] }
const cardKinds: CardKind[] = ['note', 'decision', 'question', 'task', 'link', 'artifact']
const colors: CardColor[] = ['amber', 'mint', 'blue', 'rose', 'violet']

function CardEditor({ card, position, onClose, onSave }: { card?: BoardCard; position?: {x:number;y:number}; onClose:()=>void; onSave:(value: {title:string;body:string;kind:CardKind;color:CardColor;x:number;y:number})=>Promise<void> }) {
  const [title, setTitle] = useState(card?.title || '')
  const [body, setBody] = useState(card?.body || '')
  const [kind, setKind] = useState<CardKind>(card?.kind || 'note')
  const [color, setColor] = useState<CardColor>(card?.color || 'amber')
  const [busy, setBusy] = useState(false)
  return <div className="whiteboard-modal" role="presentation" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}><form className="whiteboard-editor" onSubmit={async e => { e.preventDefault(); setBusy(true); try { await onSave({ title, body, kind, color, x: position?.x ?? card?.x ?? 80, y: position?.y ?? card?.y ?? 80 }); onClose() } finally { setBusy(false) } }}>
    <header><div><strong>{card ? 'Edit card' : 'Add to the board'}</strong><span>Visible to you and your agents</span></div><button type="button" onClick={onClose} aria-label="Close"><X size={16}/></button></header>
    <label>Title<input autoFocus required maxLength={120} value={title} onChange={e => setTitle(e.target.value)} placeholder="A clear, short thought"/></label>
    <label>Details<textarea maxLength={4000} rows={6} value={body} onChange={e => setBody(e.target.value)} placeholder="Context, a URL, acceptance criteria…"/></label>
    <div className="whiteboard-editor-row"><label>Type<select value={kind} onChange={e => setKind(e.target.value as CardKind)}>{cardKinds.map(x => <option key={x}>{x}</option>)}</select></label><fieldset><legend>Color</legend><div>{colors.map(x => <button key={x} type="button" className={`board-color is-${x}`} aria-label={x} aria-pressed={color === x} onClick={() => setColor(x)}/>)}</div></fieldset></div>
    <footer><button type="button" onClick={onClose}>Cancel</button><button className="is-primary" disabled={busy || !title.trim()}>{busy ? 'Saving…' : 'Save card'}</button></footer>
  </form></div>
}

export function WhiteboardTab({ active }: { active: boolean }) {
  const [board, setBoard] = useState<Board>(EMPTY)
  const [error, setError] = useState('')
  const [editor, setEditor] = useState<{card?: BoardCard; position?: {x:number;y:number}} | null>(null)
  const [connecting, setConnecting] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const viewport = useRef<HTMLDivElement>(null)
  const dragging = useRef<{ id:string; dx:number; dy:number; original:BoardCard } | null>(null)

  const refresh = useCallback(async (quiet = false) => {
    try { const next = await getBoard(); if (!dragging.current) setBoard(current => next.revision >= current.revision ? next : current); setError('') }
    catch (e) { if (!quiet) setError(e instanceof Error ? e.message : 'Whiteboard unavailable') }
  }, [])
  useEffect(() => { if (!active) return; void refresh(); const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void refresh(true) }, 4000); return () => window.clearInterval(timer) }, [active, refresh])

  const saveEditor = async (value: {title:string;body:string;kind:CardKind;color:CardColor;x:number;y:number}) => {
    try {
      if (editor?.card) { const saved = await updateCard(editor.card, value); setBoard(b => ({ ...b, cards: b.cards.map(c => c.id === saved.id ? saved : c) })) }
      else { const saved = await createCard(value); setBoard(b => ({ ...b, cards: [...b.cards, saved] })) }
      await refresh(true)
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to save card'); throw e }
  }
  const chooseCard = async (card: BoardCard) => {
    if (!connecting) { setEditor({ card }); return }
    if (connecting === card.id) { setConnecting(null); return }
    try { await createEdge(connecting, card.id); setConnecting(null); await refresh() } catch (e) { setError(e instanceof Error ? e.message : 'Unable to connect cards') }
  }
  const startDrag = (e: React.PointerEvent, card: BoardCard) => {
    if ((e.target as HTMLElement).closest('button,a')) return
    const rect = viewport.current?.getBoundingClientRect(); if (!rect) return
    dragging.current = { id: card.id, dx: e.clientX - rect.left + (viewport.current?.scrollLeft || 0) - card.x, dy: e.clientY - rect.top + (viewport.current?.scrollTop || 0) - card.y, original: card }
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }
  const moveDrag = (e: React.PointerEvent) => {
    const drag = dragging.current; const rect = viewport.current?.getBoundingClientRect(); if (!drag || !rect) return
    const x = Math.max(12, Math.min(1660, e.clientX - rect.left + (viewport.current?.scrollLeft || 0) - drag.dx))
    const y = Math.max(12, Math.min(980, e.clientY - rect.top + (viewport.current?.scrollTop || 0) - drag.dy))
    setBoard(b => ({...b, cards:b.cards.map(c => c.id === drag.id ? {...c,x,y} : c)}))
  }
  const endDrag = async () => {
    const drag = dragging.current; if (!drag) return
    const moved = board.cards.find(c => c.id === drag.id); dragging.current = null
    if (!moved || (moved.x === drag.original.x && moved.y === drag.original.y)) return
    try { const saved = await updateCard(drag.original, {x:moved.x,y:moved.y}); setBoard(b => ({...b,cards:b.cards.map(c=>c.id===saved.id?saved:c)})) }
    catch (e) { setError(e instanceof Error ? e.message : 'Unable to move card'); await refresh(true) }
  }
  const addAtCenter = () => { const el=viewport.current; setEditor({ position:{x:(el?.scrollLeft||0)+(el?.clientWidth||700)/2-115,y:(el?.scrollTop||0)+(el?.clientHeight||500)/2-80} }) }

  return <section className="whiteboard-tab">
    <header className="whiteboard-header"><div><h1>Collaborative whiteboard</h1><p>A shared thinking space for you and every agent.</p></div><div className="whiteboard-presence"><span className="presence-dot"/><strong>{new Set(board.cards.map(c => c.created_by)).size || 1}</strong> collaborators</div><button onClick={() => void refresh()} title="Refresh board" aria-label="Refresh board"><RefreshCw size={15}/></button><button className="is-primary" onClick={addAtCenter}><Plus size={15}/> Add card</button></header>
    {error && <div className="whiteboard-error" role="alert">{error}<button onClick={() => setError('')}>Dismiss</button></div>}
    {connecting && <div className="whiteboard-connect-banner"><GitBranch size={14}/> Select another card to connect <button onClick={() => setConnecting(null)}>Cancel</button></div>}
    <div className="whiteboard-viewport" ref={viewport} onDoubleClick={e => { if (e.target !== e.currentTarget) return; const rect=e.currentTarget.getBoundingClientRect(); setEditor({position:{x:e.clientX-rect.left+e.currentTarget.scrollLeft,y:e.clientY-rect.top+e.currentTarget.scrollTop}}) }}>
      <div className="whiteboard-canvas">
        <svg className="whiteboard-edges" aria-hidden="true">{board.edges.map(edge => { const a=board.cards.find(c=>c.id===edge.source_id), b=board.cards.find(c=>c.id===edge.target_id); if(!a||!b)return null; return <g key={edge.id}><line x1={a.x+115} y1={a.y+85} x2={b.x+115} y2={b.y+85}/></g> })}</svg>
        {board.cards.map(card => <article key={card.id} className={`board-card is-${card.color} ${connecting === card.id ? 'is-connecting' : ''}`} style={{left:card.x,top:card.y}} onPointerDown={e=>startDrag(e,card)} onPointerMove={moveDrag} onPointerUp={() => void endDrag()} onPointerCancel={() => void endDrag()}>
          <header><span>{card.kind}</span><div><button onClick={e=>{e.stopPropagation();setConnecting(card.id)}} title="Connect card" aria-label={`Connect ${card.title}`}><Link2 size={13}/></button><button onClick={e=>{e.stopPropagation();setConfirmDelete(card.id)}} title="Delete card" aria-label={`Delete ${card.title}`}><Trash2 size={13}/></button></div></header>
          <button className="board-card-content" onClick={() => void chooseCard(card)}><strong>{card.title}</strong>{card.body && <p>{card.body}</p>}</button>
          <footer><span className="board-avatar">{card.created_by.slice(0,2).toUpperCase()}</span><span>{card.created_by}</span><time>{new Date(card.updated_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</time></footer>
          {confirmDelete === card.id && <div className="board-delete-confirm"><span>Delete this card?</span><button onClick={async()=>{await deleteCard(card.id);setConfirmDelete(null);await refresh()}}>Delete</button><button onClick={()=>setConfirmDelete(null)}>Keep</button></div>}
        </article>)}
        {!board.cards.length && <button className="whiteboard-empty" onClick={addAtCenter}><Plus size={24}/><strong>Start the board</strong><span>Add a thought, question, task, or decision</span></button>}
        {board.edges.map(edge => <button key={edge.id} className="board-edge-delete" style={{left:Math.max(0,((board.cards.find(c=>c.id===edge.source_id)?.x||0)+(board.cards.find(c=>c.id===edge.target_id)?.x||0))/2+105),top:Math.max(0,((board.cards.find(c=>c.id===edge.source_id)?.y||0)+(board.cards.find(c=>c.id===edge.target_id)?.y||0))/2+75)}} onClick={async()=>{await deleteEdge(edge.id);await refresh()}} title="Remove connection" aria-label="Remove connection">×</button>)}
      </div>
    </div>
    {editor && <CardEditor card={editor.card} position={editor.position} onClose={()=>setEditor(null)} onSave={saveEditor}/>}
  </section>
}
