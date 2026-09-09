import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts'
import { useThemeStore } from '../store/themeStore'
import { findNote, type NoteSummary } from './api'

export function NotesGraph({ notes, selectedId, onNavigate }: { notes: NoteSummary[]; selectedId: string | null; onNavigate: (target: string) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const action = useRef(onNavigate)
  action.current = onNavigate
  const theme = useThemeStore(s => s.theme)
  const [local, setLocal] = useState(false)
  useEffect(() => {
    if (!ref.current) return
    const selected = notes.find(n => n.id === selectedId)
    const related = new Set([selectedId, ...(selected?.links.map(link => findNote(notes, link)?.id) ?? []),
      ...notes.filter(n => n.links.some(link => findNote(notes, link)?.id === selectedId)).map(n => n.id)])
    const visible = (local && selected ? notes.filter(n => related.has(n.id)) : notes).slice(0, 250)
    const css = getComputedStyle(ref.current)
    const accent = css.getPropertyValue('--color-accent').trim()
    const muted = css.getPropertyValue('--color-text-muted').trim()
    const nodes = visible.map(note => ({ id: note.id, name: note.title, value: note.id, symbolSize: note.id === selectedId ? 24 : 14,
      itemStyle: { color: note.id === selectedId ? accent : muted }, label: { show: true, color: muted } }))
    const edges: Array<{ source: string; target: string }> = []
    for (const note of visible) for (const link of note.links) {
      const target = findNote(notes, link)
      if (target && visible.some(n => n.id === target.id)) edges.push({ source: note.id, target: target.id })
    }
    const chart = echarts.init(ref.current, undefined, { renderer: 'svg' })
    chart.setOption({ animation: false, tooltip: { renderMode: 'richText' },
      aria: { enabled: true, description: 'Note links graph. Notes are nodes; wikilinks connect them. Use the note list for keyboard navigation.' },
      series: [{ type: 'graph', layout: 'force', data: nodes, links: edges, roam: true, draggable: true,
        force: { repulsion: 260, edgeLength: 130, gravity: 0.08, layoutAnimation: !matchMedia('(prefers-reduced-motion: reduce)').matches },
        label: { position: 'bottom', fontSize: 12 }, lineStyle: { color: muted, opacity: 0.4, curveness: 0.1 },
        emphasis: { focus: 'adjacency', lineStyle: { width: 3, color: accent } }, scaleLimit: { min: 0.3, max: 4 } }],
    })
    chart.on('click', params => { const data = params.data as { id?: string }; if (data?.id) action.current(data.id) })
    const resize = new ResizeObserver(() => chart.resize())
    resize.observe(ref.current)
    return () => { resize.disconnect(); chart.dispose() }
  }, [notes, selectedId, local, theme])
  return <div className="notes-graph">
    <div className="notes-graph-toolbar"><span>Drag to pan · scroll to zoom · click a note to open</span><button className="studio-secondary-button" onClick={() => setLocal(!local)} aria-pressed={local}>Linked notes only</button></div>
    {notes.length > 250 && <p className="notes-muted">Showing the first 250 notes. Select a note and use Linked notes only to explore its neighborhood.</p>}
    <div ref={ref} className="notes-graph-canvas" aria-label="Note links graph" />
    {!notes.length && <p className="notes-graph-empty">Create notes and connect them with [[wikilinks]] to build your graph.</p>}
  </div>
}
