import {useEffect,useState} from 'react'
import {request} from './api'
import {createNote} from '../notes/api'
import {createBoard,createCard} from '../whiteboard/api'
import {useAppStore} from '../store/appStore'
import {openBookSource} from './readingNavigation'

type Entry={id:string;book_id:string;book_title:string;section:number;section_title:string;kind:string;quote:string;note:string;format:string}
export function KnowledgeShelf({onClose}:{onClose:()=>void}) {
  const [query,setQuery]=useState(''),[entries,setEntries]=useState<Entry[]>([]),[more,setMore]=useState(false),[offset,setOffset]=useState(0),[status,setStatus]=useState(''),[busy,setBusy]=useState(false),[tick,setTick]=useState(0)
  useEffect(()=>{
    let cancelled=false
    const timer=setTimeout(()=>{setBusy(true);void request<{items:Entry[];has_more:boolean}>(`/shelf?q=${encodeURIComponent(query)}&offset=${offset}`).then(r=>{if(!cancelled){setEntries(r.items);setMore(r.has_more)}}).catch(e=>{if(!cancelled)setStatus(e.message)}).finally(()=>{if(!cancelled)setBusy(false)})},200)
    return()=>{cancelled=true;clearTimeout(timer)}
  },[query,offset,tick])
  const source=(e:Entry)=>`@book:${e.book_id}:pages:${e.section}-${e.section}`
  async function send(e:Entry,destination:string){setBusy(true);try{
    if(destination==='notes'){await createNote(`${e.book_title.slice(0,60)} · ${e.section} · ${Date.now()}`,`${e.quote}\n\n${e.note}\n\n${source(e)}`);setStatus('Saved to Notes')}
    else {const board=await createBoard(`${e.book_title.slice(0,65)} · saved idea`);await createCard({board_id:board.id,kind:'note',title:e.section_title.slice(0,120),body:`${e.quote}\n\n${e.note}`.slice(0,4000),details:{book_id:e.book_id,source_location:e.section,source_reference:source(e)}});localStorage.setItem('yapoc-whiteboard-target',board.id);useAppStore.getState().setActiveTab('whiteboard');onClose()}
  }catch(error){setStatus((error as Error).message)}finally{setBusy(false)}}
  return <section className="knowledge-shelf" aria-label="Knowledge shelf"><header><div><span className="books-eyebrow">IDEAS WORTH KEEPING</span><h2>Your knowledge shelf</h2><p>Highlights, passages and your own explanations, across your library.</p></div><button onClick={onClose}>Back to library</button></header>
    <input aria-label="Search saved ideas" placeholder="Search books, passages and notes…" value={query} onChange={e=>{setQuery(e.target.value);setOffset(0)}}/>
    <p role="status">{busy?'Loading…':status}</p>
    {!entries.length&&!busy&&<p>Highlight a passage or save a reading note to start your shelf.</p>}
    <div className="knowledge-grid">{entries.map(e=><article key={e.id}><small>{e.book_title} · {e.format==='pdf'?'Page':'Chapter'} {e.section}</small><h3>{e.section_title}</h3>{e.quote&&<blockquote>{e.quote}</blockquote>}{e.note&&<p>{e.note}</p>}<footer><button onClick={()=>{onClose();openBookSource(e.book_id,e.section)}}>Read source ↗</button><button disabled={busy} onClick={()=>void send(e,'notes')}>To Notes</button><button disabled={busy} onClick={()=>void send(e,'whiteboard')}>To Whiteboard</button><button disabled={busy} onClick={()=>{if(window.confirm('Remove this saved highlight or note?'))void request(`/${e.book_id}/annotations/${e.id}`,'DELETE').then(()=>setTick(x=>x+1)).catch(error=>setStatus(error.message))}}>Remove</button></footer></article>)}</div>
    <div className="knowledge-pagination"><button disabled={offset===0||busy} onClick={()=>setOffset(Math.max(0,offset-50))}>Previous</button><button disabled={!more||busy} onClick={()=>setOffset(offset+50)}>More ideas</button></div>
  </section>
}
