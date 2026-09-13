import {useState} from 'react'
import {useProjects} from './store'
import {useSessionStore} from '../store/session'
import {useAppStore} from '../store/appStore'
import {readNote} from '../notes/api'
function Inspect({detail,note}:{detail:string;note?:string}){
 const [preview,setPreview]=useState(''),[loaded,setLoaded]=useState(false)
 return <details onToggle={e=>{if(e.currentTarget.open&&note&&!loaded){setLoaded(true);setPreview('Loading included excerpt…');void readNote(note).then(n=>setPreview(`${n.content.slice(0,4000)}\n\nRevision: ${n.revision}${n.content.length>4000?' · shortened excerpt':''}`)).catch(()=>setPreview('Note unavailable. Exclude it or update the project sources.'))}}}><summary>Inspect</summary><pre>{detail}{preview&&`\n\n${preview}`}</pre></details>
}
export function ProjectContext(){
 const session=useSessionStore(s=>s.activeId),{projects,excluded,toggle}=useProjects()
 const p=projects.find(p=>session&&p.sessions.includes(session));if(!p||!session)return null
 const keys=[...(p.brief?[{key:'__brief__',label:'Project brief',detail:p.brief,note:undefined}]:[]),...p.sources.map(s=>({key:`${s.kind}:${s.target}`,label:`${s.label} · ${s.always?'included excerpt':'available reference'}`,detail:`${s.kind}: ${s.target}`,note:s.kind==='note'&&s.always?s.target:undefined}))]
 return <details className="project-context"><summary>Project: {p.name} · {keys.filter(k=>!(excluded[session]||[]).includes(k.key)).length} context items</summary><p>Uncheck to exclude from this message. Explicit mentions and pinned notes still apply.</p>{keys.map(k=><div key={k.key}><label><input type="checkbox" checked={!(excluded[session]||[]).includes(k.key)} onChange={()=>toggle(session,k.key)}/>{k.label}</label><Inspect detail={k.detail} note={k.note}/></div>)}<button type="button" onClick={()=>{useProjects.setState({activeId:p.id});useAppStore.getState().setActiveTab('projects')}}>Edit project sources</button></details>
}
