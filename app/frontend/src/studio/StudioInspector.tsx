import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { ArrowLeft } from 'lucide-react'

export interface InspectorPanel {
  id: string
  label: string
  identity: unknown
  content: ReactNode
  close: () => void
  group?: 'flow'
}

/** Open tools share one bounded column, rather than each taking width from chat. */
export function StudioInspector({ panels, focusId, focusVersion }: { panels: InspectorPanel[]; focusId?: string; focusVersion?: number }) {
  const [selected, setSelected] = useState('')
  const previous = useRef(new Map<string, unknown>())
  const [width, setWidth] = useState(() => {
    const saved = Number(localStorage.getItem('yapoc-agentflow-width'))
    return Number.isFinite(saved) && saved >= 320 ? saved : 460
  })
  const active = panels.find(panel => panel.id === selected) ?? panels[panels.length - 1]
  useLayoutEffect(() => {
    // A newly opened tool/file takes focus; merely rerendering does not reset tabs.
    const opened = panels.filter(panel => !previous.current.has(panel.id) || previous.current.get(panel.id) !== panel.identity)
    if (opened.length) setSelected(opened[opened.length - 1].id)
    previous.current = new Map(panels.map(panel => [panel.id, panel.identity]))
  }, [panels])
  useLayoutEffect(() => {
    if (focusId) setSelected(focusId)
  }, [focusId, focusVersion])
  useLayoutEffect(() => {
    if (active?.group === 'flow') document.getElementById(`inspector-panel-${active.id}`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [active?.id, focusVersion])

  if (!active) return null

  const resize = (next: number, available: number) => {
    const bounded = Math.max(320, Math.min(next, available - 440))
    setWidth(bounded)
    try { localStorage.setItem('yapoc-agentflow-width', String(Math.round(bounded))) } catch { /* storage may be unavailable */ }
  }
  const flows = panels.filter(panel => panel.group === 'flow')
  const comparing = active.group === 'flow' && flows.length > 1
  return <section className="studio-inspector" aria-label="Conversation inspector" style={{ '--inspector-width': `${comparing ? Math.max(width, flows.length * 360) : width}px` } as CSSProperties}>
    <div className="studio-inspector-resize" role="separator" aria-label="Resize inspector" aria-orientation="vertical"
      tabIndex={0} aria-valuemin={320} aria-valuenow={width}
      onKeyDown={event => {
        if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return
        event.preventDefault()
        resize(width + (event.key === 'ArrowLeft' ? 32 : -32), event.currentTarget.parentElement!.parentElement!.clientWidth)
      }}
      onPointerDown={event => { event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId) }}
      onPointerMove={event => {
        if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
        const rect = event.currentTarget.parentElement!.parentElement!.getBoundingClientRect()
        resize(rect.right - event.clientX, rect.width)
      }}
      onPointerUp={event => event.currentTarget.releasePointerCapture(event.pointerId)} />
    <div className="studio-inspector-toolbar">
      <button className="studio-inspector-back" onClick={() => panels.forEach(panel => panel.close())}><ArrowLeft size={16} />Back to conversation</button>
      <div className="studio-inspector-tabs" role="tablist" aria-label="Open inspectors">
        {panels.map((panel, index) => <button key={panel.id} role="tab" id={`inspector-tab-${panel.id}`}
          aria-controls={`inspector-panel-${panel.id}`} aria-selected={active.id === panel.id} tabIndex={active.id === panel.id ? 0 : -1}
          onClick={() => setSelected(panel.id)} onKeyDown={event => {
            let next = index
            if (event.key === 'ArrowRight') next = (index + 1) % panels.length
            else if (event.key === 'ArrowLeft') next = (index - 1 + panels.length) % panels.length
            else if (event.key === 'Home') next = 0
            else if (event.key === 'End') next = panels.length - 1
            else return
            event.preventDefault()
            setSelected(panels[next].id)
            document.getElementById(`inspector-tab-${panels[next].id}`)?.focus()
          }}>{panel.label}</button>)}
      </div>
    </div>
    <div className={`studio-inspector-panels ${comparing ? 'studio-inspector-compare' : ''}`}>
    {panels.map(panel => <div key={panel.id} id={`inspector-panel-${panel.id}`} role="tabpanel"
      aria-labelledby={`inspector-tab-${panel.id}`} hidden={active.id !== panel.id && !(comparing && panel.group === 'flow')} className="studio-inspector-content">
      {panel.content}
    </div>)}
    </div>
  </section>
}
