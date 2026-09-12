import { useEffect, useMemo, useRef, useState } from 'react'
import { ExternalLink } from 'lucide-react'
import './messageResources.css'

export function resourceLinks(text: string) {
  const source = text.replace(/```[\s\S]*?```/g, '')
  const links = new Map<string, string>()
  for (const match of source.matchAll(/\[([^\]]+)\]\(([^\s)]+)\)|(https?:\/\/[^\s<>\])]+)/g)) {
    const href = (match[2] || match[3]).replace(/[.,;!]+$/, '')
    if (/^https?:\/\//i.test(href)) links.set(href, match[1] || '')
  }
  return [...links].slice(0, 6)
}

function ResourceCard({ href, label }: { href: string; label: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)
  const [data, setData] = useState<{ title?: string; description?: string; image?: string; name?: string; size?: number; kind?: string }>({})
  const [failedImage, setFailedImage] = useState(false)
  let url: URL | null = null
  try { url = new URL(href) } catch { /* unusable link */ }
  useEffect(() => {
    const observer = new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) { setVisible(true); observer.disconnect() } })
    if (ref.current) observer.observe(ref.current)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    if (!visible) return
    const controller = new AbortController()
    fetch(`/api/link-previews?url=${encodeURIComponent(href)}`, { signal: controller.signal }).then(r => r.ok ? r.json() : {}).then(value => { if (!controller.signal.aborted) setData(value) }).catch(() => {})
    return () => controller.abort()
  }, [visible, href])
  if (!url || url.username || url.password) return null
  const name = data.title || label || url.hostname
  const thumbnail = data.image ? `/api/link-previews/image?url=${encodeURIComponent(data.image)}` : ''
  return <div ref={ref} className="message-resource">
    {thumbnail && !failedImage && <img src={thumbnail} alt="" loading="lazy" onError={() => setFailedImage(true)} />}
    <div className="message-resource-body"><small>{url.hostname}</small>
      <strong>{name}</strong>{data.description && <p>{data.description}</p>}
      <a href={href} target="_blank" rel="noopener noreferrer"><ExternalLink size={13} />Open link</a>
    </div>
  </div>
}

export function MessageResources({ content }: { content: string }) {
  const links = useMemo(() => resourceLinks(content), [content])
  return links.length ? <div className="message-resources" aria-label="Links and files">{links.map(([href, label]) => <ResourceCard key={href} href={href} label={label} />)}</div> : null
}
