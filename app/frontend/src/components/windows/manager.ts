/**
 * Dynamic side-by-side window manager — imperative engine.
 *
 * Operates on a `.modal-content` element (the actual window). The React
 * `Window` component renders the DOM; `useDockableWindow` calls the attach*
 * functions here on mount and the returned cleanups on unmount.
 *
 * Desktop only: everything no-ops at <= MOBILE_BP (mobile uses the CSS
 * full-screen sheet fallback). All pointer interactions use setPointerCapture
 * and remove their listeners on release (hard rule #5). CSS var reads are
 * cached per gesture, not per frame (rule #5).
 */

export const MOBILE_BP = 768
export const SNAP_PX = 6 // top edge within this → fullscreen
export const UNSNAP_PX = 24 // drag this far down to leave fullscreen
export const DOCK_EDGE_PX = 60 // within this of L/R edge → dock
export const RESIZE_EDGE = 7 // px proximity to an edge to start a resize
export const MIN_W = 320
export const MIN_H = 200
export const MIN_CHAT_WIDTH = 380 // auto-collapse sidebar below this main width

export type DockSide = 'left' | 'right'

export const isMobile = () => window.innerWidth <= MOBILE_BP

interface PreDockSnapshot {
  rect: { left: number; top: number; width: number; height: number }
  style: {
    left: string; top: string; right: string; bottom: string
    width: string; height: string; position: string; borderRadius: string
  }
}

// Augment the element with our private state without polluting global types.
interface ManagedEl extends HTMLElement {
  _preDockSnapshot?: PreDockSnapshot
  _dockSide?: DockSide | null
  __cleanups?: Array<() => void>
}

// ── persistence ────────────────────────────────────────────────────────────
export function loadSize(id: string): { w: number; h: number } | null {
  try {
    const raw = localStorage.getItem('winsize-' + id)
    if (!raw) return null
    const o = JSON.parse(raw)
    if (typeof o?.w === 'number' && typeof o?.h === 'number') return o
  } catch { /* ignore */ }
  return null
}
export function saveSize(id: string, w: number, h: number): void {
  try { localStorage.setItem('winsize-' + id, JSON.stringify({ w: Math.round(w), h: Math.round(h) })) } catch { /* ignore */ }
}

// ── geometry helpers ─────────────────────────────────────────────────────────
function snapshot(el: ManagedEl): PreDockSnapshot {
  const r = el.getBoundingClientRect()
  const s = el.style
  return {
    rect: { left: r.left, top: r.top, width: r.width, height: r.height },
    style: {
      left: s.left, top: s.top, right: s.right, bottom: s.bottom,
      width: s.width, height: s.height, position: s.position, borderRadius: s.borderRadius,
    },
  }
}
function restore(el: ManagedEl, snap: PreDockSnapshot) {
  const s = el.style
  s.left = snap.style.left || snap.rect.left + 'px'
  s.top = snap.style.top || snap.rect.top + 'px'
  s.right = snap.style.right
  s.bottom = snap.style.bottom
  s.width = snap.style.width || snap.rect.width + 'px'
  s.height = snap.style.height || snap.rect.height + 'px'
  s.position = snap.style.position || 'fixed'
  s.borderRadius = snap.style.borderRadius
}

// ── edge docking (§1 — the core of side-by-side) ─────────────────────────────
export function applyEdgeDock(content: HTMLElement, side: DockSide): void {
  if (isMobile()) return
  const el = content as ManagedEl
  const modal = el.closest('.modal') as HTMLElement | null

  // Snapshot ONCE so undock restores the exact pre-dock window (gotcha #2).
  if (!el._preDockSnapshot) el._preDockSnapshot = snapshot(el)

  // Re-docking the other side: clear the old side first (keep the snapshot).
  if (el._dockSide && el._dockSide !== side) clearDockClasses(el, modal)

  el._dockSide = side
  el.classList.add(side === 'right' ? 'modal-right-docked' : 'modal-left-docked')
  modal?.classList.add(side === 'right' ? 'modal-right-docked' : 'modal-left-docked')

  // Pin full-height flush to the edge, square corners.
  Object.assign(el.style, { position: 'fixed', top: '0px', bottom: '0px', height: '100vh', borderRadius: '0px' })

  if (side === 'right') {
    // RIGHT pushes the main content (body padding) to make room.
    const w = Math.max(420, Math.min(Math.round(window.innerWidth * 0.38), 640))
    el.style.right = '0px'
    el.style.left = 'auto'
    el.style.width = w + 'px'
    document.body.classList.add('right-dock-active')
    document.body.style.setProperty('--right-dock-w', w + 'px')
  } else {
    // LEFT overlays flush at the (collapsed) sidebar rail edge and does NOT
    // push, so the right side stays free for a second pane. --left-dock-w
    // stays 0. We collapse the sidebar fully, so anchor at 0.
    const w = Math.max(420, Math.min(Math.round(window.innerWidth * 0.38), 640))
    document.body.classList.add('sidebar-railed') // collapse sidebar to a rail
    el.style.left = '0px'
    el.style.right = 'auto'
    el.style.width = w + 'px'
    document.body.classList.add('left-dock-active')
    document.body.style.setProperty('--left-dock-w', '0px')
  }
}

function railRightEdge(): number {
  // Anchor a left-dock at the right edge of the (railed) sidebar, if any.
  const aside = document.querySelector('aside')
  if (!aside) return 0
  const r = aside.getBoundingClientRect()
  return Math.max(0, r.right)
}

function clearDockClasses(el: ManagedEl, modal: HTMLElement | null) {
  if (el._dockSide === 'right') {
    el.classList.remove('modal-right-docked')
    modal?.classList.remove('modal-right-docked')
    document.body.classList.remove('right-dock-active')
    document.body.style.removeProperty('--right-dock-w')
  } else if (el._dockSide === 'left') {
    el.classList.remove('modal-left-docked')
    modal?.classList.remove('modal-left-docked')
    document.body.classList.remove('left-dock-active')
    document.body.classList.remove('sidebar-railed')
    document.body.style.removeProperty('--left-dock-w')
  }
}

export function undock(content: HTMLElement): void {
  const el = content as ManagedEl
  if (!el._dockSide) return
  const modal = el.closest('.modal') as HTMLElement | null
  clearDockClasses(el, modal)
  el._dockSide = null
  if (el._preDockSnapshot) {
    restore(el, el._preDockSnapshot)
    el._preDockSnapshot = undefined
  }
}

export function isDocked(content: HTMLElement): boolean {
  return !!(content as ManagedEl)._dockSide
}

// ── fullscreen (top-edge snap, §2/§3) ────────────────────────────────────────
export function applyFullscreen(content: HTMLElement): void {
  if (isMobile()) return
  const el = content as ManagedEl
  if (!el._preDockSnapshot) el._preDockSnapshot = snapshot(el)
  el.classList.add('modal-fullscreen')
  Object.assign(el.style, { position: 'fixed', left: '0px', top: '0px', right: '0px', bottom: '0px', width: 'auto', height: 'auto', borderRadius: '0px' })
}
export function clearFullscreen(content: HTMLElement): void {
  const el = content as ManagedEl
  if (!el.classList.contains('modal-fullscreen')) return
  el.classList.remove('modal-fullscreen')
  if (el._preDockSnapshot) { restore(el, el._preDockSnapshot); el._preDockSnapshot = undefined }
}

// ── tile ghost preview (§3) ──────────────────────────────────────────────────
function ghost(): HTMLElement {
  let g = document.getElementById('tile-ghost')
  if (!g) {
    g = document.createElement('div')
    g.id = 'tile-ghost'
    document.body.appendChild(g)
  }
  return g
}
function showGhost(rect: { left: number; top: number; width: number; height: number }) {
  const g = ghost()
  Object.assign(g.style, { left: rect.left + 'px', top: rect.top + 'px', width: rect.width + 'px', height: rect.height + 'px' })
  g.classList.add('visible')
}
function hideGhost() { document.getElementById('tile-ghost')?.classList.remove('visible') }

type Zone = 'fullscreen' | 'left-dock' | 'right-dock' | null
function zoneRect(zone: Zone): { left: number; top: number; width: number; height: number } | null {
  const W = window.innerWidth, H = window.innerHeight
  const dockW = Math.max(420, Math.min(Math.round(W * 0.38), 640))
  switch (zone) {
    case 'fullscreen': return { left: 0, top: 0, width: W, height: H }
    case 'right-dock': return { left: W - dockW, top: 0, width: dockW, height: H }
    case 'left-dock': return { left: railRightEdge(), top: 0, width: dockW, height: H }
    default: return null
  }
}
function detectZone(x: number, y: number): Zone {
  const W = window.innerWidth
  if (y <= SNAP_PX) return 'fullscreen'
  if (x >= W - DOCK_EDGE_PX) return 'right-dock'
  if (x <= DOCK_EDGE_PX + railRightEdge()) return 'left-dock'
  return null
}

// ── drag → dock / fullscreen (§2) ────────────────────────────────────────────
export function makeWindowDraggable(content: HTMLElement, handle: HTMLElement): () => void {
  const el = content as ManagedEl

  function onPointerDown(e: PointerEvent) {
    if (isMobile()) return
    const t = e.target as HTMLElement
    if (t.closest('button,input,select,textarea,a')) return // don't drag from controls
    e.preventDefault()
    handle.setPointerCapture(e.pointerId)

    // Leaving a docked/fullscreen state by dragging: restore windowed geometry
    // anchored under the cursor before tracking.
    if (el._dockSide) undock(el)
    if (el.classList.contains('modal-fullscreen')) clearFullscreen(el)

    const rect = el.getBoundingClientRect()
    const offX = e.clientX - rect.left
    const offY = e.clientY - rect.top
    el.classList.add('modal-dragging')
    Object.assign(el.style, { position: 'fixed', right: 'auto', bottom: 'auto', width: rect.width + 'px', height: rect.height + 'px' })
    let zone: Zone = null

    const onMove = (ev: PointerEvent) => {
      el.style.left = (ev.clientX - offX) + 'px'
      el.style.top = Math.max(0, ev.clientY - offY) + 'px'
      zone = detectZone(ev.clientX, ev.clientY)
      const r = zoneRect(zone)
      if (r) showGhost(r); else hideGhost()
    }
    const onUp = (ev: PointerEvent) => {
      handle.releasePointerCapture(ev.pointerId)
      handle.removeEventListener('pointermove', onMove)
      handle.removeEventListener('pointerup', onUp)
      handle.removeEventListener('pointercancel', onUp)
      el.classList.remove('modal-dragging')
      hideGhost()
      if (zone === 'fullscreen') applyFullscreen(el)
      else if (zone === 'right-dock') applyEdgeDock(el, 'right')
      else if (zone === 'left-dock') applyEdgeDock(el, 'left')
    }
    handle.addEventListener('pointermove', onMove)
    handle.addEventListener('pointerup', onUp)
    handle.addEventListener('pointercancel', onUp)
  }

  handle.addEventListener('pointerdown', onPointerDown)
  return () => handle.removeEventListener('pointerdown', onPointerDown)
}

// ── edge / corner resize (§4) ────────────────────────────────────────────────
type ResizeDir = '' | 'e' | 'w' | 'n' | 's' | 'ne' | 'nw' | 'se' | 'sw'
function dirAt(el: HTMLElement, e: PointerEvent): ResizeDir {
  const r = el.getBoundingClientRect()
  const nearL = e.clientX - r.left <= RESIZE_EDGE
  const nearR = r.right - e.clientX <= RESIZE_EDGE
  const nearT = e.clientY - r.top <= RESIZE_EDGE
  const nearB = r.bottom - e.clientY <= RESIZE_EDGE
  return ((nearT ? 'n' : nearB ? 's' : '') + (nearL ? 'w' : nearR ? 'e' : '')) as ResizeDir
}
const CURSOR: Record<string, string> = { e: 'ew-resize', w: 'ew-resize', n: 'ns-resize', s: 'ns-resize', ne: 'nesw-resize', sw: 'nesw-resize', nw: 'nwse-resize', se: 'nwse-resize' }

export function makeWindowResizable(content: HTMLElement, id: string): () => void {
  const el = content as ManagedEl

  const restoreSize = loadSize(id)
  if (restoreSize) { el.style.width = restoreSize.w + 'px'; el.style.height = restoreSize.h + 'px' }

  function locked() { return el._dockSide || el.classList.contains('modal-fullscreen') || isMobile() }

  function onHover(e: PointerEvent) {
    if (locked()) { el.style.cursor = ''; return }
    const d = dirAt(el, e)
    el.style.cursor = d ? CURSOR[d] : ''
  }

  function onPointerDown(e: PointerEvent) {
    if (locked()) return
    const dir = dirAt(el, e)
    if (!dir) return
    e.preventDefault(); e.stopPropagation()
    el.setPointerCapture(e.pointerId)
    const r = el.getBoundingClientRect()
    const start = { x: e.clientX, y: e.clientY, w: r.width, h: r.height, left: r.left, top: r.top }
    document.body.style.userSelect = 'none'

    const onMove = (ev: PointerEvent) => {
      const dx = ev.clientX - start.x, dy = ev.clientY - start.y
      let w = start.w, h = start.h, left = start.left, top = start.top
      if (dir.includes('e')) w = start.w + dx
      if (dir.includes('s')) h = start.h + dy
      if (dir.includes('w')) { w = start.w - dx; left = start.left + dx }
      if (dir.includes('n')) { h = start.h - dy; top = start.top + dy }
      // Clamp min, anchoring the opposite edge.
      if (w < MIN_W) { if (dir.includes('w')) left = start.left + (start.w - MIN_W); w = MIN_W }
      if (h < MIN_H) { if (dir.includes('n')) top = start.top + (start.h - MIN_H); h = MIN_H }
      // Clamp to viewport.
      left = Math.max(0, Math.min(left, window.innerWidth - w))
      top = Math.max(0, Math.min(top, window.innerHeight - h))
      Object.assign(el.style, { position: 'fixed', width: w + 'px', height: h + 'px', left: left + 'px', top: top + 'px', right: 'auto', bottom: 'auto' })
    }
    const onUp = (ev: PointerEvent) => {
      el.releasePointerCapture(ev.pointerId)
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerup', onUp)
      el.removeEventListener('pointercancel', onUp)
      document.body.style.userSelect = ''
      const r2 = el.getBoundingClientRect()
      saveSize(id, r2.width, r2.height)
    }
    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerup', onUp)
    el.addEventListener('pointercancel', onUp)
  }

  el.addEventListener('pointermove', onHover)
  el.addEventListener('pointerdown', onPointerDown)
  return () => {
    el.removeEventListener('pointermove', onHover)
    el.removeEventListener('pointerdown', onPointerDown)
  }
}

// ── reflow / re-clamp (§6) ───────────────────────────────────────────────────
let reflowRefs = 0
let reflowCleanup: (() => void) | null = null

function reclampAll() {
  if (isMobile()) {
    // Mobile: drop dock side-effects; CSS sheet fallback takes over.
    document.body.classList.remove('right-dock-active', 'left-dock-active', 'sidebar-railed')
    return
  }
  // Re-derive right-dock width on viewport change.
  document.querySelectorAll<HTMLElement>('.modal-content.modal-right-docked').forEach((el) => {
    const w = Math.max(420, Math.min(Math.round(window.innerWidth * 0.38), 640))
    el.style.width = w + 'px'
    document.body.style.setProperty('--right-dock-w', w + 'px')
  })
  document.querySelectorAll<HTMLElement>('.modal-content.modal-left-docked').forEach((el) => {
    el.style.left = '0px'
  })
  // Auto-collapse the sidebar when the main area gets too tight.
  const railed = document.body.classList.contains('left-dock-active')
  if (!railed) {
    const padR = parseInt(getComputedStyle(document.body).paddingRight) || 0
    const mainW = window.innerWidth - padR - railRightEdge()
    if (mainW < MIN_CHAT_WIDTH) document.body.classList.add('sidebar-auto-railed')
    else document.body.classList.remove('sidebar-auto-railed')
  }
}

export function attachReflow(): () => void {
  reflowRefs++
  if (!reflowCleanup) {
    const onResize = () => reclampAll()
    window.addEventListener('resize', onResize)
    // Watch the sidebar's class for toggles.
    const aside = document.querySelector('aside')
    const mo = aside
      ? new MutationObserver(() => reclampAll())
      : null
    if (aside && mo) mo.observe(aside, { attributes: true, attributeFilter: ['class'] })
    reflowCleanup = () => {
      window.removeEventListener('resize', onResize)
      mo?.disconnect()
    }
  }
  reclampAll()
  return () => {
    reflowRefs--
    if (reflowRefs <= 0 && reflowCleanup) { reflowCleanup(); reflowCleanup = null }
  }
}
