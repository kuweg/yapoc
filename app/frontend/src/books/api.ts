export interface Book {id:string;title:string;author:string;format:'pdf'|'epub';status:string;total:number;position:number;offset:number;finished:boolean;updated_at:string;preferences:Record<string,unknown>}
export interface Section {number:number;label:string;title:string;text:string}
export interface Annotation {id:string;section:number;kind:string;quote:string;note:string;color:string}
export interface Turn {id:string;question:string;answer:string;scope:{start:number;end:number;action:string};citations:{id:string;number:number;label:string;excerpt:string}[]}
export async function request<T>(path='',method='GET',body?:unknown):Promise<T>{
  const response=await fetch(`/api/books${path}`,{method,...(body?{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})})
  if(response.status===204)return undefined as T
  const value=await response.json()
  if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'Book request failed')
  return value
}
export async function uploadBook(file:File):Promise<Book>{const data=new FormData();data.append('file',file);const r=await fetch('/api/books',{method:'POST',body:data});const b=await r.json();if(!r.ok)throw new Error(b.detail||'Upload failed');return b}
