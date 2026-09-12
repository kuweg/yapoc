import {useEffect,useState} from 'react'
import {useAppStore} from '../store/appStore'

export function StudyDesk({busy}:{busy:boolean}) {
  const active=useAppStore(state=>state.activeTab==='books')
  const [awake,setAwake]=useState(true)
  const [visible,setVisible]=useState(!document.hidden)
  useEffect(()=>{
    let timer:ReturnType<typeof setTimeout>
    const wake=()=>{setAwake(true);clearTimeout(timer);timer=setTimeout(()=>setAwake(false),45000)}
    const visibility=()=>setVisible(!document.hidden)
    wake();window.addEventListener('pointerdown',wake);window.addEventListener('keydown',wake);window.addEventListener('wheel',wake,{passive:true});document.addEventListener('visibilitychange',visibility)
    return()=>{clearTimeout(timer);window.removeEventListener('pointerdown',wake);window.removeEventListener('keydown',wake);window.removeEventListener('wheel',wake);document.removeEventListener('visibilitychange',visibility)}
  },[])
  const state=!visible||!active?'sleeping':busy?'typing':awake?'reading':'sleeping'
  return <div className={`study-desk is-${state}`} role="img" aria-label={`Pixel study desk: companion ${state}, cat resting beside the desk`}>
    <div className="study-window"><i/><i/><b>✦</b></div><div className="study-shelf"><i/><i/><i/><i/></div>
    <div className="study-lamp"/><div className="study-person"><i className="study-hair"/><i className="study-face"/><i className="study-shirt"/><i className="study-hands"/></div>
    <div className="study-table"/><div className="study-book"/><div className="study-mug"/><div className="study-cat"><i/><b>z</b></div>
    <span className="study-caption">{state==='typing'?'Thinking through your passage…':state==='sleeping'?'A quiet pause. Your place is safe.':'A little company for the next chapter.'}</span>
  </div>
}
