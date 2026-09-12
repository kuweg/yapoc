import {useEffect,useMemo,useState,type CSSProperties} from 'react'
import type {AgentStatus} from '../api/types'
import {getTasks,type QueuedTask} from '../api/client'
import {listArtifacts} from '../artifacts/api'
import type {Artifact} from '../artifacts/types'
import {useSessionStore} from '../store/session'
import {useWsStore} from '../store/wsStore'
import {useFileViewerStore} from '../store/fileViewerStore'
import {useAppStore} from '../store/appStore'
import {getAgentColor} from '../lib/agentIdentity'
import {Resident} from '../components/AgentOffice'

export function SharedAgentRoom({agents,disconnected,onOpen}:{agents:AgentStatus[];disconnected:boolean;onOpen:(agent:AgentStatus)=>void}){
  const sessionId=useSessionStore(s=>s.activeId),sessionName=useSessionStore(s=>s.sessions.find(session=>session.id===s.activeId)?.name)
  const connected=useWsStore(s=>s.connected)
  const live=useWsStore(s=>s.backgroundTasks),completed=useWsStore(s=>s.lastCompletedTask?.task_id)
  const [tasks,setTasks]=useState<QueuedTask[]>([]),[artifacts,setArtifacts]=useState<Artifact[]>([]),[error,setError]=useState(false),[tick,setTick]=useState(0),[open,setOpen]=useState(true)
  useEffect(()=>{let cancelled=false;setTasks([]);setArtifacts([]);setError(false);if(!sessionId)return;void Promise.all([getTasks(100),listArtifacts()]).then(([tasks,artifacts])=>{if(!cancelled){setTasks(tasks);setArtifacts(artifacts)}}).catch(()=>{if(!cancelled)setError(true)});return()=>{cancelled=true}},[sessionId,completed,tick,connected])
  const sessionTasks=useMemo(()=>{
    const merged=new Map(tasks.map(t=>[t.id,t]))
    for(const t of live)merged.set(t.task_id,{...merged.get(t.task_id),id:t.task_id,prompt:t.prompt||'',status:t.status,session_id:t.session_id||merged.get(t.task_id)?.session_id,assigned_agent:t.agent||merged.get(t.task_id)?.assigned_agent})
    return [...merged.values()].filter(t=>t.session_id===sessionId)
  },[tasks,live,sessionId])
  const current=sessionTasks.filter(t=>['running','waiting','blocked'].includes(t.status))
  const names=new Set(current.flatMap(t=>[t.assigned_agent||'master',...(t.progress?.waiting_on||[])]))
  const residents=agents.filter(a=>names.has(a.name))
  const taskIds=new Set(sessionTasks.map(t=>t.id))
  const files=artifacts.filter(a=>Boolean(sessionId)&&(a.source_session===sessionId||Boolean(a.source_task&&taskIds.has(a.source_task)))).sort((a,b)=>b.updated_at.localeCompare(a.updated_at)).slice(0,6)
  return <section className="shared-agent-room" aria-label="Conversation shared room"><button className="shared-room-heading" aria-expanded={open} onClick={()=>setOpen(!open)}><span>COMMON ROOM</span><span>{open?'−':'+'}</span></button>{open&&<><p title={sessionName}>{sessionName||'Start a conversation to fill this room'}</p><div className={`shared-room-scene ${disconnected?'is-offline':''}`}><div className="shared-room-window" aria-hidden="true">✦</div><div className="shared-room-table" aria-hidden="true"/><div className="shared-room-residents">{residents.map(agent=><div key={agent.name} style={{'--resident-color':getAgentColor(agent.name)} as CSSProperties}><Resident agent={agent} disconnected={disconnected||!connected} onOpen={onOpen}/></div>)}</div>{!residents.length&&<span className="shared-room-rest">{disconnected?'Connection unavailable':current.length?'Waiting for assigned agents':'The table is quiet.'}</span>}</div><small>{disconnected||!connected||error?'Live room data unavailable':`${current.length} active tasks · ${files.length} recent deliveries`}</small><div className="shared-room-deliveries">{files.map(file=><button key={file.id} title={`${file.source_agent} · ${file.name}`} onClick={()=>{useFileViewerStore.getState().selectFile({path:file.path,name:file.name});useAppStore.getState().setActiveTab('artifacts')}}><span aria-hidden="true">▣</span>{file.name}<small>{file.source_agent}</small></button>)}</div>{!files.length&&<small>Artifacts linked to this conversation arrive here.</small>}<button className="shared-room-refresh" onClick={()=>setTick(n=>n+1)}>Refresh room</button></>}</section>
}
