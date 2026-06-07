import { useRef, useState } from 'react'
import { AgentChatFlowPanel } from './AgentChatFlowPanel'

const KEY = 'yapoc-agentflow-width'
const MIN_FLOW = 300 // agent-flow pane min width
const MIN_CHAT = 360 // keep the chat usable

function loadWidth(): number {
  const v = parseInt(localStorage.getItem(KEY) || '')
  return Number.isFinite(v) ? v : 460
}

/**
 * Tiled agent-flow pane: sits to the RIGHT of the chat in the chat-tab row and
 * tiles with it — the chat (flex-1) shrinks to make room, and the border
 * between them is a draggable seam that sets the ratio (persisted). On mobile
 * the panel falls back to a full-screen overlay (CSS) and the seam is hidden.
 */
export function AgentFlowPane({ agentName, onClose }: { agentName: string; onClose: () => void }) {
  const [width, setWidth] = useState(loadWidth)
  const dividerRef = useRef<HTMLDivElement>(null)

  const onPointerDown = (e: React.PointerEvent) => {
    const divider = dividerRef.current
    const main = divider?.parentElement
    if (!divider || !main) return
    e.preventDefault()
    divider.setPointerCapture(e.pointerId)
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
    divider.classList.add('flow-divider-active')
    let current = width

    const onMove = (ev: PointerEvent) => {
      const rect = main.getBoundingClientRect()
      let w = rect.right - ev.clientX
      w = Math.max(MIN_FLOW, Math.min(w, rect.width - MIN_CHAT))
      current = w
      setWidth(w)
    }
    const onUp = (ev: PointerEvent) => {
      divider.releasePointerCapture(ev.pointerId)
      divider.removeEventListener('pointermove', onMove)
      divider.removeEventListener('pointerup', onUp)
      divider.removeEventListener('pointercancel', onUp)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
      divider.classList.remove('flow-divider-active')
      try { localStorage.setItem(KEY, String(Math.round(current))) } catch { /* ignore */ }
    }
    divider.addEventListener('pointermove', onMove)
    divider.addEventListener('pointerup', onUp)
    divider.addEventListener('pointercancel', onUp)
  }

  return (
    <>
      <div
        ref={dividerRef}
        onPointerDown={onPointerDown}
        className="flow-divider"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize agent flow panel"
      />
      <div style={{ width }} className="flow-pane flex-shrink-0 min-w-0 h-full">
        <AgentChatFlowPanel agentName={agentName} onClose={onClose} />
      </div>
    </>
  )
}
