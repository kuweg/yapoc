import {useState} from 'react'
import {request} from './api'
import {useAppStore} from '../store/appStore'
import type {Board} from '../whiteboard/api'

type Draft={name:string;nodes:{key:string;title:string;body:string;number:number;excerpt:string}[];edges:{source:string;target:string;label:string}[]}
export function ReadingMap({book_id,start,end,spoilers,onClose,onBusy}:{book_id:string;start:number;end:number;spoilers:boolean;onClose:()=>void;onBusy:(busy:boolean)=>void}) {
  const [draft,setDraft]=useState<Draft|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('')
  async function generate(){setBusy(true);onBusy(true);setError('');try{setDraft(await request<Draft>(`/${book_id}/map/preview`,'POST',{start,end,avoid_spoilers:spoilers}))}catch(e){setError((e as Error).message)}finally{setBusy(false);onBusy(false)}}
  async function save(){setBusy(true);setError('');try{const board=await request<Board>(`/${book_id}/map`,'POST',draft);localStorage.setItem('yapoc-whiteboard-target',board.canvas.id);useAppStore.getState().setActiveTab('whiteboard');onClose()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  return <div className="reading-map-overlay"><section className="reading-map-dialog" role="dialog" aria-modal="true" aria-label="Book concept map"><header><h2>Book → Whiteboard</h2><button disabled={busy} aria-label="Close concept map" onClick={onClose}>×</button></header><p>Locations {start}–{end}{spoilers?' · spoiler boundary respected':''}. Review the concepts, then create a new editable canvas.</p><p>Long chapters may be sampled. Each concept keeps a link to its source.</p>
    {error&&<p role="alert">{error}</p>}
    {!draft?<button autoFocus disabled={busy} onClick={()=>void generate()}>{busy?'Finding connections…':'Generate preview'}</button>:<><label>Canvas name<input value={draft.name} maxLength={100} onChange={e=>setDraft({...draft,name:e.target.value})}/></label><div className="reading-map-preview">{draft.nodes.map(node=><article key={node.key}><strong>{node.title}</strong><p>{node.body}</p><details><summary>Source · location {node.number}</summary><blockquote>{node.excerpt}</blockquote></details></article>)}</div><ul>{draft.edges.map((edge,i)=><li key={i}>{draft.nodes.find(n=>n.key===edge.source)?.title} → {edge.label} → {draft.nodes.find(n=>n.key===edge.target)?.title}</li>)}</ul><button disabled={busy||!draft.name.trim()} onClick={()=>void save()}>{busy?'Saving…':'Create new Whiteboard'}</button><button disabled={busy} onClick={()=>void generate()}>Regenerate</button></>}
  </section></div>
}
