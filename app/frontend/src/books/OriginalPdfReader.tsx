import {useEffect,useLayoutEffect,useRef,useState,type CSSProperties} from 'react'
import {getDocument,GlobalWorkerOptions,TextLayer,type PDFDocumentProxy,type PDFPageProxy,type RenderTask} from 'pdfjs-dist'
import worker_url from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type {Annotation} from './api'
import './originalPdf.css'

GlobalWorkerOptions.workerSrc=worker_url
const compact=(text:string)=>text.normalize('NFKC').replace(/[\s\u00ad]+/gu,'')

type Props={book_id:string;target:{number:number;offset:number;revision:number};annotations:Annotation[];onPosition:(number:number,offset:number)=>void}
export default function OriginalPdfReader({book_id,target,annotations,onPosition}:Props){
  const [pdf,setPdf]=useState<PDFDocumentProxy|null>(null),[error,setError]=useState(''),[retry,setRetry]=useState(0),[width,setWidth]=useState(700),[zoom,setZoom]=useState(1)
  const root=useRef<HTMLDivElement>(null),latest=useRef(onPosition),jump=useRef(true),previous=useRef(target),position=useRef({number:target.number,offset:target.offset})
  latest.current=onPosition
  if(previous.current!==target){previous.current=target;position.current={number:target.number,offset:target.offset};jump.current=true}
  useEffect(()=>{
    let disposed=false
    const task=getDocument({url:`/api/books/${book_id}/original`,cMapUrl:'/pdfjs-assets/cmaps/',cMapPacked:true,standardFontDataUrl:'/pdfjs-assets/standard_fonts/',wasmUrl:'/pdfjs-assets/wasm/'})
    setError('');setPdf(null)
    void task.promise.then(doc=>{if(!disposed)setPdf(doc)}).catch(()=>{if(!disposed)setError('Could not open this PDF. Retry or open it in your browser.')})
    return()=>{disposed=true;void task.destroy()}
  },[book_id,retry])
  useEffect(()=>{if(!root.current)return;const observer=new ResizeObserver(entries=>setWidth(Math.max(220,entries[0].contentRect.width-32)));observer.observe(root.current);return()=>observer.disconnect()},[])
  useLayoutEffect(()=>{
    if(!pdf||!jump.current)return
    const container=root.current,element=container?.querySelector<HTMLElement>(`[data-section="${target.number}"]`)
    if(container&&element){container.scrollTop+=element.getBoundingClientRect().top-container.getBoundingClientRect().top+target.offset*element.offsetHeight;jump.current=false}
  },[pdf,target])
  useLayoutEffect(()=>{
    if(!pdf||jump.current)return
    const container=root.current,location=position.current,element=container?.querySelector<HTMLElement>(`[data-section="${location.number}"]`)
    if(container&&element)container.scrollTop+=element.getBoundingClientRect().top-container.getBoundingClientRect().top+location.offset*element.offsetHeight
  },[width,zoom])
  const track=()=>{
    const container=root.current;if(!container||jump.current)return
    const top=container.getBoundingClientRect().top
    for(const el of container.querySelectorAll<HTMLElement>('[data-section]')){
      const rect=el.getBoundingClientRect();if(rect.bottom>top+16){position.current={number:Number(el.dataset.section),offset:Math.max(0,Math.min(1,(top-rect.top)/rect.height))};latest.current(position.current.number,position.current.offset);break}
    }
  }
  return <div className="original-pdf-reader">
    <div className="original-pdf-tools"><button aria-label="Zoom out PDF" disabled={zoom<=.5} onClick={()=>setZoom(z=>Math.max(.5,z-.25))}>−</button><button onClick={()=>setZoom(1)}>Fit width</button><span>{Math.round(zoom*100)}%</span><button aria-label="Zoom in PDF" disabled={zoom>=2} onClick={()=>setZoom(z=>Math.min(2,z+.25))}>+</button><a href={`/api/books/${book_id}/original`} target="_blank" rel="noreferrer">Open in browser ↗</a><small>Select text for book actions</small></div>
    {error&&<div role="alert" className="books-error">{error}<button onClick={()=>setRetry(x=>x+1)}>Retry PDF</button></div>}
    <div ref={root} className="original-pdf-scroll" onScroll={track} aria-label="Original PDF pages">
      {!pdf&&!error&&<p role="status">Opening PDF…</p>}
      {pdf&&Array.from({length:pdf.numPages},(_,i)=><PdfPage key={i+1} pdf={pdf} number={i+1} width={width*zoom} root={root} annotations={annotations} onResize={track}/>)}
    </div>
  </div>
}

function PdfPage({pdf,number,width,root,annotations,onResize}:{pdf:PDFDocumentProxy;number:number;width:number;root:React.RefObject<HTMLDivElement|null>;annotations:Annotation[];onResize:()=>void}){
  const host=useRef<HTMLElement>(null),canvas=useRef<HTMLCanvasElement>(null),text=useRef<HTMLDivElement>(null),marks=useRef<HTMLDivElement>(null)
  const [near,setNear]=useState(false),[page,setPage]=useState<PDFPageProxy|null>(null),[ready,setReady]=useState(false),[hasText,setHasText]=useState(true),[error,setError]=useState(false),[retry,setRetry]=useState(0)
  useEffect(()=>{const observer=new IntersectionObserver(entries=>setNear(entries[0].isIntersecting),{root:root.current,rootMargin:'600px 0px'});if(host.current)observer.observe(host.current);return()=>observer.disconnect()},[])
  useEffect(()=>{if(!near||page)return;let cancelled=false;void pdf.getPage(number).then(p=>{if(!cancelled)setPage(p)}).catch(()=>{if(!cancelled)setError(true)});return()=>{cancelled=true}},[near,page,pdf,number,retry])
  const base=page?.getViewport({scale:1}),scale=width/(base?.width||612),height=width*(base?base.height/base.width:792/612)
  useEffect(()=>{
    if(!page||!near||!canvas.current||!text.current)return
    let cancelled=false,render:RenderTask|undefined,layer:TextLayer|undefined
    const target=text.current;target.replaceChildren();setReady(false);setError(false)
    const viewport=page.getViewport({scale}),pixelRatio=Math.min(window.devicePixelRatio||1,2)
    const el=canvas.current;el.width=Math.ceil(viewport.width*pixelRatio);el.height=Math.ceil(viewport.height*pixelRatio)
    render=page.render({canvas:el,viewport,transform:pixelRatio===1?undefined:[pixelRatio,0,0,pixelRatio,0,0]})
    void Promise.all([render.promise,page.getTextContent().then(async content=>{if(cancelled)return;setHasText(content.items.some(item=>'str' in item&&item.str.trim()));layer=new TextLayer({textContentSource:content,container:target,viewport});await layer.render()})]).then(()=>{if(!cancelled)setReady(true)}).catch(()=>{if(!cancelled)setError(true)})
    return()=>{cancelled=true;render?.cancel();layer?.cancel()}
  },[page,near,scale,retry])
  useEffect(()=>{if(page)onResize()},[page])
  useEffect(()=>{
    const container=text.current,overlay=marks.current;if(!container||!overlay)return;overlay.replaceChildren();if(!ready)return
    const positions:{node:Text;start:number;end:number}[]=[];let full=''
    const walker=document.createTreeWalker(container,NodeFilter.SHOW_TEXT)
    for(let node=walker.nextNode() as Text|null;node;node=walker.nextNode() as Text|null){for(let i=0;i<node.length;i++){const part=compact(node.data[i]);full+=part;for(let j=0;j<part.length;j++)positions.push({node,start:i,end:i+1})}}
    for(const a of annotations.filter(a=>a.section===number&&a.kind==='highlight'&&a.quote)){
      const needle=compact(a.quote),at=needle?full.indexOf(needle):-1;if(at<0)continue
      const first=positions[at],last=positions[at+needle.length-1];if(!first||!last)continue
      const range=document.createRange();range.setStart(first.node,first.start);range.setEnd(last.node,last.end)
      const origin=container.getBoundingClientRect()
      for(const rect of range.getClientRects()){const mark=document.createElement('span');Object.assign(mark.style,{left:`${rect.left-origin.left}px`,top:`${rect.top-origin.top}px`,width:`${rect.width}px`,height:`${rect.height}px`});overlay.append(mark)}
    }
  },[annotations,ready,scale,number])
  return <article ref={host} className="original-pdf-page" data-section={number} aria-label={`PDF page ${number}`} style={{width,height,'--total-scale-factor':scale} as CSSProperties}>
    {near&&<><canvas ref={canvas} aria-label={`Rendered PDF page ${number}`}/><div ref={text} className="pdf-text-layer"/><div ref={marks} className="pdf-highlight-layer" aria-hidden="true"/></>}
    {ready&&!hasText&&<span className="pdf-page-status">Image-only page · text actions require OCR</span>}
    {!ready&&<span className="pdf-page-status">{error?<button onClick={()=>{setError(false);setRetry(n=>n+1)}}>Retry page {number}</button>:`Page ${number}${near?' · rendering…':''}`}</span>}
  </article>
}
