import {create} from 'zustand'
import {persist} from 'zustand/middleware'
import type {AppTab} from '../store/appStore'

export const WORKSPACE_LAYOUTS = {
  single: {label:'Single view', tabs:[] as AppTab[]},
  reading: {label:'Reading · Book + Notes', tabs:['books','notes'] as AppTab[]},
  designing: {label:'Designing · Whiteboard + Chat', tabs:['whiteboard','chat'] as AppTab[]},
  reviewing: {label:'Reviewing · Artifacts + Chat', tabs:['artifacts','chat'] as AppTab[]},
}
export type WorkspaceLayout=keyof typeof WORKSPACE_LAYOUTS
interface LayoutStore {
  layout:WorkspaceLayout; ratio:number; mobilePane:0|1; lastTab:AppTab
  setLayout:(layout:WorkspaceLayout)=>void; setRatio:(ratio:number)=>void; setPane:(pane:0|1)=>void; visit:(tab:AppTab)=>void
}
export const useWorkspaceLayout=create<LayoutStore>()(persist(set=>({
  layout:'single',ratio:55,mobilePane:0,lastTab:'chat',
  setLayout:layout=>set({layout,mobilePane:0}),setRatio:ratio=>set({ratio:Math.max(30,Math.min(70,ratio))}),setPane:mobilePane=>set({mobilePane}),visit:lastTab=>set({lastTab}),
}),{name:'yapoc-workspace-layout',partialize:s=>({layout:s.layout,ratio:s.ratio,lastTab:s.lastTab}),merge:(saved,current)=>{
  const value=saved as Partial<LayoutStore>|undefined
  return {...current,...value,layout:value?.layout&&value.layout in WORKSPACE_LAYOUTS?value.layout:'single',ratio:Number.isFinite(value?.ratio)?Math.max(30,Math.min(70,value!.ratio!)):55,mobilePane:0,lastTab:typeof value?.lastTab==='string'&&['chat','books','notes','whiteboard','artifacts','agents','tasks','graph','vault','sessions','concilium','channels','insights','skills','mcp','plugins','cron','drive','github','observability'].includes(value.lastTab)?value.lastTab:'chat'}
}}))
