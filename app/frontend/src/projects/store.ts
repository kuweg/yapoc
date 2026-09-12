import {create} from 'zustand'
import {persist} from 'zustand/middleware'
import {useNotesStore} from '../notes/store'
import {openBookSource} from '../books/readingNavigation'
import {useSessionStore} from '../store/session'
import {useAppStore,type AppTab} from '../store/appStore'
import {useWorkspaceLayout,type WorkspaceLayout} from '../studio/workspaceLayout'

export interface Source {kind:'book'|'note'|'whiteboard'|'artifact'|'file'|'link';target:string;label:string;always:boolean}
export interface Project {id:string;name:string;description:string;brief:string;sources:Source[];sessions:string[];revision:number;updated_at:string}
interface Snapshot {layout:WorkspaceLayout;ratio:number;tab:AppTab;session:string|null;book?:string|null;note?:string|null;board?:string|null}
export async function api<T>(path='',method='GET',body?:unknown):Promise<T>{
  const r=await fetch(`/api/projects${path}`,{method,headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})})
  if(r.status===204)return undefined as T
  const value=await r.json();if(!r.ok)throw new Error(typeof value.detail==='string'?value.detail:'Project request failed');return value
}
interface Store {projects:Project[];activeId:string|null;error:string;excluded:Record<string,string[]>;snapshots:Record<string,Snapshot>;refresh:()=>Promise<void>;save:(p:Partial<Project>)=>Promise<Project>;remove:(p:Project)=>Promise<void>;activate:(p:Project)=>void;toggle:(session:string,key:string)=>void}
export const useProjects=create<Store>()(persist((set,get)=>({
  projects:[],activeId:null,error:'',excluded:{},snapshots:{},
  refresh:async()=>{try{set({projects:await api<Project[]>(),error:''})}catch(e){set({error:(e as Error).message});throw e}},
  save:async p=>{const value=await api<Project>(p.id?`/${p.id}`:'',p.id?'PUT':'POST',p);set(s=>({projects:[value,...s.projects.filter(x=>x.id!==value.id)]}));return value},
  remove:async p=>{await api(`/${p.id}?revision=${p.revision}`,'DELETE');set(s=>({projects:s.projects.filter(x=>x.id!==p.id),activeId:s.activeId===p.id?null:s.activeId}))},
  activate:p=>{
    const state=get(),workspace=useWorkspaceLayout.getState(),tab=useAppStore.getState().activeTab
    const snapshots={...state.snapshots}
    if(state.activeId&&tab!=='projects')snapshots[state.activeId]={layout:workspace.layout,ratio:workspace.ratio,tab,session:useSessionStore.getState().activeId,book:localStorage.getItem('yapoc-current-book'),note:useNotesStore.getState().selectedId,board:localStorage.getItem('yapoc-whiteboard')}
    set({activeId:p.id,snapshots})
    const saved=snapshots[p.id],session=saved?.session&&p.sessions.includes(saved.session)?saved.session:p.sessions[p.sessions.length-1]
    if(session&&useSessionStore.getState().sessions.some(s=>s.id===session))useSessionStore.getState().loadSession(session)
    if(saved?.note)useNotesStore.getState().select(saved.note)
    if(saved?.board)localStorage.setItem('yapoc-whiteboard-target',saved.board)
    if(saved?.book)openBookSource(saved.book)
    workspace.setLayout(saved?.layout||'single');workspace.setRatio(saved?.ratio||55)
    useAppStore.getState().setActiveTab(saved?.tab||'projects')
  },
  toggle:(session,key)=>set(s=>({excluded:{...s.excluded,[session]:(s.excluded[session]||[]).includes(key)?s.excluded[session].filter(k=>k!==key):[...(s.excluded[session]||[]),key]}})),
}),{name:'yapoc-projects',partialize:s=>({activeId:s.activeId,snapshots:s.snapshots,excluded:s.excluded,projects:s.projects})}))
// Save per-project layout when navigating, without backend writes or polling.
useAppStore.subscribe((state,previous)=>{
  const p=useProjects.getState(),w=useWorkspaceLayout.getState()
  if(p.activeId&&previous.activeTab!=='projects'&&state.activeTab==='projects')useProjects.setState({snapshots:{...p.snapshots,[p.activeId]:{layout:w.layout,ratio:w.ratio,tab:previous.activeTab,session:useSessionStore.getState().activeId,book:localStorage.getItem('yapoc-current-book'),note:useNotesStore.getState().selectedId,board:localStorage.getItem('yapoc-whiteboard')}}})
})
export function projectSubmission(session:string|null){
  const state=useProjects.getState(),project=state.projects.find(p=>session&&p.sessions.includes(session))
  return project?{project_id:project.id,project_excluded:state.excluded[session!]||[]}:{}
}
