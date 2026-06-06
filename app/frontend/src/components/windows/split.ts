/**
 * Split seam (§5) — the draggable divider between the main content and a
 * right-docked pane, so the two panes share the row and the user drags the
 * split point. Realized as a grip on the left edge of the docked window that
 * resizes the dock width (and the body padding via --right-dock-w).
 *
 * Persisted to `<app>-split-width` so the chosen split survives reloads.
 */
import { isMobile, isDocked } from './manager'

export const MIN_LEFT = 300 // main pane min (spec: 260–340)
export const MIN_RIGHT = 300 // docked pane min (spec: 260–360)
const SPLIT_KEY = 'yapoc-split-width'

function loadSplit(id: string): number | null {
  try {
    const raw = localStorage.getItem(`${SPLIT_KEY}-${id}`)
    const n = raw ? parseInt(raw) : NaN
    return Number.isFinite(n) ? n : null
  } catch { return null }
}
function saveSplit(id: string, w: number): void {
  try { localStorage.setItem(`${SPLIT_KEY}-${id}`, String(Math.round(w))) } catch { /* ignore */ }
}

function setDockWidth(content: HTMLElement, w: number): void {
  content.style.width = w + 'px'
  document.body.style.setProperty('--right-dock-w', w + 'px')
}

/**
 * Wire a seam grip (on the docked window's left edge) to resize the dock.
 * Active only while the content is right-docked on desktop.
 */
export function makeSplitSeam(seam: HTMLElement, content: HTMLElement, id: string): () => void {
  // Restore a persisted split once docked.
  const persisted = loadSplit(id)
  if (persisted && isDocked(content)) setDockWidth(content, persisted)

  function onPointerDown(e: PointerEvent) {
    if (isMobile() || !isDocked(content)) return
    e.preventDefault()
    e.stopPropagation()
    seam.setPointerCapture(e.pointerId)
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
    seam.classList.add('split-active')
    let current = content.getBoundingClientRect().width

    const onMove = (ev: PointerEvent) => {
      let w = window.innerWidth - ev.clientX
      const max = window.innerWidth - MIN_LEFT
      w = Math.max(MIN_RIGHT, Math.min(w, max))
      current = w
      setDockWidth(content, w)
    }
    const onUp = (ev: PointerEvent) => {
      seam.releasePointerCapture(ev.pointerId)
      seam.removeEventListener('pointermove', onMove)
      seam.removeEventListener('pointerup', onUp)
      seam.removeEventListener('pointercancel', onUp)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
      seam.classList.remove('split-active')
      saveSplit(id, current)
    }
    seam.addEventListener('pointermove', onMove)
    seam.addEventListener('pointerup', onUp)
    seam.addEventListener('pointercancel', onUp)
  }

  seam.addEventListener('pointerdown', onPointerDown)
  return () => seam.removeEventListener('pointerdown', onPointerDown)
}
