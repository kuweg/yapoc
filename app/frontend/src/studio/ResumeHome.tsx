import {useEffect,useState} from 'react'
import {BookOpen,MessageSquare,GitBranch,FileText,ArrowRight,RefreshCw} from 'lucide-react'
import {request,type Book} from '../books/api'
import {openBookSource} from '../books/readingNavigation'
import {listBoards,type CanvasInfo} from '../whiteboard/api'
import {listNotes,type NoteSummary} from '../notes/api'
import {useNotesStore} from '../notes/store'
import {useSessionStore} from '../store/session'
import {useWsStore} from '../store/wsStore'
import {useAppStore} from '../store/appStore'
import {useWorkspaceLayout,WORKSPACE_LAYOUTS} from './workspaceLayout'

export function ResumeHome({active}:{active:boolean}){
  const [books,setBooks]=useState<Book[]>([]),[boards,setBoards]=useState<CanvasInfo[]>([]),[notes,setNotes]=useState<NoteSummary[]>([]),[error,setError]=useState(''),[loading,setLoading]=useState(false),[tick,setTick]=useState(0)
  const sessions=useSessionStore(s=>s.sessions),activeId=useSessionStore(s=>s.activeId),notifications=useWsStore(s=>s.unreadNotifications)
  const {lastTab,layout}=useWorkspaceLayout(),setTab=useAppStore(s=>s.setActiveTab)
  useEffect(()=>{if(!active)return;let cancelled=false;setLoading(true);setError('');void Promise.allSettled([request<Book[]>(),listBoards(),listNotes()]).then(results=>{
    if(cancelled)return
    const [b,w,n]=results
    if(b.status==='fulfilled')setBooks(b.value);else setBooks([])
    if(w.status==='fulfilled')setBoards(w.value.sort((a,b)=>b.updated_at.localeCompare(a.updated_at)));else setBoards([])
    if(n.status==='fulfilled')setNotes(n.value.notes.sort((a,b)=>b.updated_at.localeCompare(a.updated_at)));else setNotes([])
    if(results.some(r=>r.status==='rejected'))setError('Some saved work is unavailable. Retry when the backend is connected.')
    setLoading(false)
  });return()=>{cancelled=true}},[active,tick])
  const session=sessions.find(s=>s.id===activeId)||sessions[0],book=books.find(b=>!b.finished)||books[0],board=boards.find(b=>b.id===localStorage.getItem('yapoc-whiteboard'))||boards[0],note=notes.find(n=>n.id===useNotesStore.getState().selectedId)||notes[0]
  const openSession=(id:string)=>{useSessionStore.getState().loadSession(id);setTab('chat')}
  return <section className="resume-home"><header><div><span className="studio-eyebrow">YOUR WORK, READY WHEN YOU ARE</span><h1>Pick up the thread.</h1><p>Your reading, ideas and conversations, where you left them.</p></div><button aria-label="Refresh resume home" onClick={()=>setTick(n=>n+1)}><RefreshCw size={16}/></button></header>
    <button className="resume-banner" onClick={()=>setTab(lastTab==='home'?'chat':lastTab)}><span><small>RETURN TO YOUR WORKSPACE</small><strong>{WORKSPACE_LAYOUTS[layout].tabs.includes(lastTab)?WORKSPACE_LAYOUTS[layout].label:`Continue in ${lastTab==='chat'?'Conversation':lastTab}`}</strong></span><ArrowRight/></button>
    {loading&&<p role="status">Finding your saved work…</p>}{error&&<p role="alert">{error}</p>}
    <div className="resume-grid">
      <article><BookOpen/><small>READING</small><h2>{book?.title||'Your next book'}</h2><p>{book?`${book.format==='pdf'?'Page':'Chapter'} ${book.position} of ${book.total}`:'Upload a book and keep your place.'}</p><button onClick={()=>book?openBookSource(book.id):setTab('books')}>{book?'Continue reading':'Open Books'} <ArrowRight size={14}/></button></article>
      <article><GitBranch/><small>DESIGNING</small><h2>{board?.name||'A place for your ideas'}</h2><p>{board?`${board.card_count||0} design nodes · saved canvas`:'Sketch a system with agents.'}</p><button onClick={()=>{if(board)localStorage.setItem('yapoc-whiteboard-target',board.id);setTab('whiteboard')}}>Continue designing <ArrowRight size={14}/></button></article>
      <article><MessageSquare/><small>CONVERSATION</small><h2>{session?.name||'Start a conversation'}</h2><p>{session?`${session.history.length} saved messages`:'Talk through an idea or delegate a task.'}</p><button onClick={()=>session?openSession(session.id):setTab('chat')}>Continue conversation <ArrowRight size={14}/></button></article>
      <article><FileText/><small>NOTES</small><h2>{note?.title||'Capture a thought'}</h2><p>{note?.excerpt?.slice(0,140)||'Your own notes and explanations.'}</p><button onClick={()=>{if(note)useNotesStore.getState().select(note.id);setTab('notes')}}>Continue writing <ArrowRight size={14}/></button></article>
    </div>
    <section className="resume-results"><h2>Results to review</h2><p>Unread task notifications. Opening a result does not approve or apply changes.</p>{notifications.filter(n=>['done','completed','error','failed'].includes(n.status)).length===0&&<p>No unread results right now.</p>}{notifications.filter(n=>['done','completed','error','failed'].includes(n.status)).slice(0,8).map(task=><article key={task.task_id}><div><small>{task.agent||'Agent'} · {task.status}</small><strong>{task.prompt||'Task result'}</strong></div><button onClick={()=>task.session_id&&sessions.some(s=>s.id===task.session_id)?openSession(task.session_id):setTab('tasks')}>Review</button><button onClick={()=>useWsStore.getState().dismissNotification(task.task_id)}>Mark seen</button></article>)}</section>
  </section>
}
