import {type Annotation, type Section} from './api'

export function ReadingTimeline({total, page, contents, annotations, onGo}: {
  total:number; page:number; contents:Section[]; annotations:Annotation[]; onGo:(n:number)=>void
}) {
  const location = (n:number) => total>1 ? (n-1)/(total-1)*100 : 0
  const marked = [...new Set(annotations.map(a=>a.section))]
  return <nav className="reading-timeline" aria-label="Reading timeline">
    <div className="reading-timeline-label"><span>{contents.find(s=>s.number===page)?.title||`Location ${page}`}</span><small>{Math.round(page/total*100)}% · {marked.length} annotated locations</small></div>
    <div className="reading-timeline-track">
      <div className="reading-timeline-ticks" aria-hidden="true">{contents.filter((_,i)=>i%Math.max(1,Math.ceil(total/100))===0).map(s=><i key={s.number} style={{left:`${location(s.number)}%`}}/>)}</div>
      <input aria-label="Jump through book" type="range" min={1} max={Math.max(1,total)} value={page} onChange={e=>onGo(Number(e.target.value))}/>
    </div>
    {marked.length>0&&<div className="reading-timeline-markers">{marked.sort((a,b)=>a-b).map(n=><button key={n} title={annotations.filter(a=>a.section===n).map(a=>a.note||a.quote||a.kind).join(' · ').slice(0,240)} aria-label={`Open annotated location ${n}`} onClick={()=>onGo(n)}>◆ {n}</button>)}</div>}
  </nav>
}
