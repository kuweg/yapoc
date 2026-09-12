import {useMemo,useRef,useState} from 'react'
import {tokenizeChatText} from '../lib/chatTokens'
import {type MentionKind} from '../lib/mentions'
import {ensureMentionSource,mentionEntities} from '../lib/mentionSources'
import {request,type Book,type Section} from '../books/api'
import {listBoards,getBoard} from '../whiteboard/api'
import {listNotes,readNote} from '../notes/api'
import {StudioDialog} from './StudioDialog'

type Reference={start:number;end:number;raw:string;kind:MentionKind;target?:string}
export function contextReferences(text:string):Reference[]{
  let offset=0;const refs:Reference[]=[]
  for(const token of tokenizeChatText(text)){
    if(token.kind==='mention'&&!(token.target===undefined&&text[offset+token.text.length]===':')){
      const range=token.subsystem.kind==='book'?text.slice(offset+token.text.length).match(/^:pages:\d+-\d+/)?.[0]||'':''
      const raw=token.text+range
      refs.push({start:offset,end:offset+raw.length,raw,kind:token.subsystem.kind,target:token.target})
    }
    offset+=token.text.length
  }
  return refs
}
async function preview(ref:Reference):Promise<string>{
  if(!ref.target)return `This references the ${ref.kind} system. It asks the agent to use that subsystem; it does not attach every entry.`
  const target=ref.target.replace(/:pages:\d+-\d+$/,'')
  const norm=(s:string)=>s.trim().toLowerCase().replace(/[\s_-]+/g,' ')
  if(ref.kind==='book'){
    const books=await request<Book[]>()
    const matches=books.filter(b=>b.id===target||norm(b.title)===norm(target))
    if(matches.length!==1)throw new Error(matches.length?'This book name is ambiguous. Use its ID.':'Book not found. Check the mention.')
    const book=matches[0],range=ref.raw.match(/:pages:(\d+)-(\d+)$/),first=range?Number(range[1]):1,last=range?Number(range[2]):book.position
    if(first<1||last<first||last>book.total)throw new Error('This page range is outside the book.')
    const section=await request<Section>(`/${book.id}/sections/${first}`)
    return `${book.title}\n${book.format==='pdf'?'Pages':'Chapters'} ${first}–${last}\n\nPreview of location ${first}:\n${section.text.slice(0,1800)}\n\nThis preview is shortened. Source passages are resolved when you send the message.`
  }
  if(ref.kind==='whiteboard'){
    const boards=await listBoards(),matches=boards.filter(b=>b.id===target||norm(b.name)===norm(target))
    if(matches.length!==1)throw new Error('Canvas not found or ambiguous. Use an exact canvas name or ID.')
    const board=await getBoard(matches[0].id)
    return `${board.canvas.name}\n${board.cards.length} nodes · ${board.edges.length} connections · revision ${board.revision}\n\n${board.cards.slice(0,8).map(c=>`${c.kind}: ${c.title}\n${c.body.slice(0,200)}`).join('\n\n')}\n\nPreview only. The canvas is resolved when sent.`
  }
  if(ref.kind==='note'){
    const {notes}=await listNotes(),found=notes.find(n=>n.id===target||norm(n.title)===norm(target))
    if(!found)throw new Error('Note not found. Check the mention.')
    const note=await readNote(found.id)
    return `${note.title}\nRevision ${note.revision}\n\n${note.content.slice(0,2400)}\n\nPreview only. The note is resolved when sent.`
  }
  await ensureMentionSource(ref.kind)
  const rows=mentionEntities(ref.kind,target)
  return rows.length?rows.map(r=>`${r.label}\n${r.desc}`).join('\n\n'):'No matching entry is available in the current source list. Check the reference before sending.'
}
export function ContextTray({text,onRemove}:{text:string;onRemove:(start:number,end:number)=>void}){
  const refs=useMemo(()=>contextReferences(text),[text])
  const [selected,setSelected]=useState<Reference|null>(null),[content,setContent]=useState(''),[error,setError]=useState('')
  const version=useRef(0)
  const close=()=>{version.current++;setSelected(null)}
  async function inspect(ref:Reference){const current=++version.current;setSelected(ref);setContent('Loading source preview…');setError('');try{const value=await preview(ref);if(current===version.current)setContent(value)}catch(e){if(current===version.current){setContent('');setError((e as Error).message)}}}
  if(!refs.length&&!selected)return null
  return <div className="context-tray" aria-label="Message context"><div className="context-tray-label">Referenced context <small>Click to inspect · × removes the mention</small></div><div className="context-chips">{refs.map(ref=><span key={`${ref.start}:${ref.raw}`}><button type="button" aria-label={`Inspect ${ref.raw}`} onClick={()=>void inspect(ref)}>{ref.raw}</button><button type="button" aria-label={`Remove ${ref.raw}`} onClick={()=>onRemove(ref.start,ref.end)}>×</button></span>)}</div>
    {selected&&<StudioDialog label="Inspect context" onClose={close}><section className="context-preview"><header><h2>{selected.raw}</h2><button type="button" onClick={close} aria-label="Close context preview">×</button></header>{error?<p role="alert">{error}</p>:<pre>{content}</pre>}<p>These chips reflect mentions in your message. Your session’s pinned notes and conversation history may also provide context.</p></section></StudioDialog>}
  </div>
}
