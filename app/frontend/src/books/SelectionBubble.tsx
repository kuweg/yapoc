import {useEffect,useState} from 'react'

export function SelectionBubble({text,busy,onSelect,onAction,onClose,onVisibility}:{text:string;busy:boolean;onSelect:(text:string,number:number)=>void;onAction:(action:string)=>void;onClose:()=>void;onVisibility:(visible:boolean)=>void}) {
  const [position,setPosition]=useState<{x:number;y:number}|null>(null)
  useEffect(()=>{onVisibility(Boolean(text&&position))},[text,position,onVisibility])
  useEffect(()=>{
    const capture=()=>{
      const selection=window.getSelection()
      if(!selection?.rangeCount||selection.isCollapsed)return
      const a=selection.anchorNode?.parentElement?.closest<HTMLElement>('.reading-page[data-section],.original-pdf-page[data-section]')
      const b=selection.focusNode?.parentElement?.closest<HTMLElement>('.reading-page[data-section],.original-pdf-page[data-section]')
      if(!a||a!==b)return
      const value=selection.toString().slice(0,10000)
      if(!value.trim())return
      const rect=selection.getRangeAt(0).getBoundingClientRect()
      setPosition({x:Math.max(8,Math.min(rect.left,window.innerWidth-Math.min(420,window.innerWidth-16)-8)),y:Math.max(8,Math.min(rect.bottom+8,window.innerHeight-130))})
      onSelect(value,Number(a.dataset.section))
      return true
    }
    const context=(event:MouseEvent)=>{if((event.target as HTMLElement).closest('.reading-page,.original-pdf-page')&&capture())event.preventDefault()}
    const hide=()=>setPosition(null)
    const key=(e:KeyboardEvent)=>{if(e.key==='Escape'){setPosition(null);onClose()}else if(e.shiftKey)capture()}
    document.addEventListener('contextmenu',context)
    document.addEventListener('pointerup',capture)
    document.addEventListener('keyup',key)
    document.addEventListener('scroll',hide,true)
    window.addEventListener('resize',hide)
    return()=>{document.removeEventListener('contextmenu',context);document.removeEventListener('pointerup',capture);document.removeEventListener('keyup',key);document.removeEventListener('scroll',hide,true);window.removeEventListener('resize',hide)}
  },[onSelect,onClose])
  if(!text||!position)return null
  return <div className="reading-selection-bubble" role="toolbar" aria-label="Passage actions" style={{left:position.x,top:position.y}} onMouseDown={e=>e.preventDefault()}>
    {['Explain','Translate','Example','Highlight','Ask','Save'].map(action=><button key={action} disabled={busy} onClick={()=>{onAction(action.toLowerCase());setPosition(null)}}>{action}</button>)}
    <button aria-label="Dismiss passage actions" onClick={()=>{onClose();setPosition(null)}}>×</button>
  </div>
}
