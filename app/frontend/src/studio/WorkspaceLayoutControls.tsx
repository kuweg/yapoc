import {useAppStore} from '../store/appStore'
import {WORKSPACE_LAYOUTS,useWorkspaceLayout,type WorkspaceLayout} from './workspaceLayout'
const names:Record<string,string>={books:'Book',notes:'Notes',whiteboard:'Whiteboard',chat:'Chat',artifacts:'Artifacts'}
export function WorkspaceLayoutControls(){
  const tab=useAppStore(s=>s.activeTab),setTab=useAppStore(s=>s.setActiveTab)
  const {layout,setLayout,mobilePane,setPane}=useWorkspaceLayout()
  const pair=WORKSPACE_LAYOUTS[layout].tabs,split=pair.includes(tab)
  return <div className="workspace-layout-controls"><label>Workspace<select aria-label="Workspace layout" value={split?layout:'single'} onChange={e=>{const next=e.target.value as WorkspaceLayout;setLayout(next);if(next!=='single')setTab(WORKSPACE_LAYOUTS[next].tabs[0])}}>{Object.entries(WORKSPACE_LAYOUTS).map(([key,value])=><option key={key} value={key}>{value.label}</option>)}</select></label>
    {split&&<><div className="workspace-pane-tabs" role="group" aria-label="Visible workspace pane">{pair.map((pane,i)=><button key={pane} aria-pressed={mobilePane===i} onClick={()=>{setPane(i as 0|1);setTab(pane)}}>{names[pane]}</button>)}</div><button className="workspace-close-split" onClick={()=>setLayout('single')}>Single view</button></>}
  </div>
}
export function WorkspaceDivider(){
  const {ratio,setRatio}=useWorkspaceLayout()
  return <div className="workspace-divider" role="separator" aria-label="Resize workspace panes" aria-orientation="vertical" aria-valuemin={30} aria-valuemax={70} aria-valuenow={Math.round(ratio)} tabIndex={0}
    onDoubleClick={()=>setRatio(50)} onKeyDown={e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();setRatio(e.key==='Home'?30:e.key==='End'?70:ratio+(e.key==='ArrowLeft'?-2:2))}}}
    onPointerDown={e=>{e.currentTarget.setPointerCapture(e.pointerId)}} onPointerMove={e=>{if(!e.currentTarget.hasPointerCapture(e.pointerId))return;const rect=e.currentTarget.parentElement!.getBoundingClientRect();setRatio((e.clientX-rect.left)/rect.width*100)}} onPointerUp={e=>{if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId)}}><span/></div>
}
