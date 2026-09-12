import {useEffect, useLayoutEffect, useRef, useState} from 'react'
import {request, type Annotation, type Section} from './api'

type Props = {
  book_id: string; title: string; total: number; unit: string; font: number
  target: {number: number; offset: number; revision: number}
  annotations: Annotation[]
  onPosition: (section: Section, offset: number) => void
  onSelection: (text: string, section: Section) => void
}

/** Text is fetched near the viewport; distant sections remain lightweight placeholders. */
export function ContinuousReader(props: Props) {
  const root = useRef<HTMLDivElement>(null)
  const cache = useRef(new Map<number, Section>())
  const pending = useRef(new Set<number>())
  const latest = useRef(props)
  latest.current = props
  const [sections, setSections] = useState(new Map<number, Section>())
  const [errors, setErrors] = useState(new Set<number>())
  const navigating = useRef(true)
  const lastTarget = useRef(props.target)
  if (lastTarget.current !== props.target) {
    lastTarget.current = props.target
    navigating.current = true
  }
  const anchor = useRef<{number: number; top: number} | null>(null)

  useLayoutEffect(() => {
    const container = root.current
    if (container && anchor.current && !navigating.current) {
      const element = container.querySelector<HTMLElement>(`[data-section="${anchor.current.number}"]`)
      if (element) container.scrollTop += element.getBoundingClientRect().top - anchor.current.top
    }
    anchor.current = null
    if (!navigating.current) track()
  }, [sections])

  async function load(number: number) {
    if (cache.current.has(number) || pending.current.has(number)) return
    pending.current.add(number)
    try {
      const section = await request<Section>(`/${props.book_id}/sections/${number}`)
      cache.current.set(number, section)
      if (!navigating.current && !anchor.current && root.current) {
        const top = root.current.getBoundingClientRect().top
        const element = Array.from(root.current.querySelectorAll<HTMLElement>('[data-section]')).find(el => el.getBoundingClientRect().bottom > top + 1)
        if (element) anchor.current = {number: Number(element.dataset.section), top: element.getBoundingClientRect().top}
      }
      setSections(new Map(cache.current))
      setErrors(previous => { const next = new Set(previous); next.delete(number); return next })
    } catch {
      setErrors(previous => new Set(previous).add(number))
    } finally { pending.current.delete(number) }
  }

  useEffect(() => {
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) void load(Number((entry.target as HTMLElement).dataset.section))
    }, {root: root.current, rootMargin: '600px 0px'})
    root.current?.querySelectorAll('[data-section]').forEach(element => observer.observe(element))
    return () => observer.disconnect()
  }, [props.book_id])

  useEffect(() => {
    void load(props.target.number)
  }, [props.target])

  useLayoutEffect(() => {
    if (!navigating.current || !sections.has(props.target.number)) return
    const container = root.current
    const element = container?.querySelector<HTMLElement>(`[data-section="${props.target.number}"]`)
    if (!container || !element) return
    container.scrollTop += element.getBoundingClientRect().top - container.getBoundingClientRect().top + props.target.offset * element.offsetHeight
    navigating.current = false
    latest.current.onPosition(sections.get(props.target.number)!, props.target.offset)
  }, [sections, props.target])

  function track() {
    const container = root.current
    if (!container || navigating.current) return
    const top = container.getBoundingClientRect().top
    const elements = container.querySelectorAll<HTMLElement>('[data-section]')
    for (const element of elements) {
      const rect = element.getBoundingClientRect()
      if (rect.bottom > top + 1) {
        const section = cache.current.get(Number(element.dataset.section))
        if (section) latest.current.onPosition(section, Math.max(0, Math.min(1, (top - rect.top) / rect.height)))
        break
      }
    }
  }

  return <div className="reading-scroll reading-continuous" ref={root} onScroll={track} onPointerUp={() => {
    const selected = window.getSelection()
    const start = selected?.anchorNode?.parentElement?.closest<HTMLElement>('[data-section]')
    const end = selected?.focusNode?.parentElement?.closest<HTMLElement>('[data-section]')
    if (!start || start !== end || !root.current?.contains(start)) return
    const section = cache.current.get(Number(start.dataset.section))
    if (section) props.onSelection(selected!.toString().slice(0, 10000), section)
  }}>
    {Array.from({length: props.total}, (_, i) => i + 1).map(number => {
      const section = sections.get(number)
      const quotes = props.annotations.filter(a => a.section === number && a.kind === 'highlight' && a.quote).map(a => a.quote)
      return <article className={`reading-page ${section ? '' : 'reading-placeholder'}`} data-section={number} key={number} style={{fontSize: props.font}}>
        <small>{props.title} / {props.unit} {number}</small>
        {section ? <><h2>{section.title}</h2>{section.text ? section.text.split(/\n\s*\n/).map((paragraph, index) => {
          const quote = quotes.find(q => paragraph.includes(q))
          const at = quote ? paragraph.indexOf(quote) : -1
          return <p key={index}>{quote ? <>{paragraph.slice(0, at)}<mark>{quote}</mark>{paragraph.slice(at + quote.length)}</> : paragraph}</p>
        }) : <p>No extractable text. For scanned PDF pages, use Original PDF.</p>}</> : errors.has(number) ? <button onClick={() => void load(number)}>Could not load {props.unit.toLowerCase()} {number} · Retry</button> : <p role="status">Loading {props.unit.toLowerCase()}…</p>}
      </article>
    })}
  </div>
}
