import { useEffect, useRef, type ReactNode } from 'react'
import {
  makeWindowDraggable,
  makeWindowResizable,
  applyEdgeDock,
  undock,
  attachReflow,
  isDocked,
  isMobile,
  loadSize,
} from './windows/manager'
import { makeSplitSeam } from './windows/split'

interface WindowProps {
  id: string
  title: ReactNode
  /** Extra header controls (e.g. tab switcher) rendered before the dock buttons. */
  headerControls?: ReactNode
  onClose: () => void
  children: ReactNode
}

let cascade = 0

/**
 * Floating, draggable, dockable, resizable window (chat-animation § next:
 * dynamic side-by-side windows spec). Renders the spec's
 * .modal > .modal-content(.modal-header + .modal-body) structure and wires the
 * imperative engine via refs. Desktop only; at <= 768px the CSS turns it into a
 * full-screen sheet and the engine no-ops.
 */
export function Window({ id, title, headerControls, onClose, children }: WindowProps) {
  const contentRef = useRef<HTMLDivElement>(null)
  const headerRef = useRef<HTMLDivElement>(null)
  const seamRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const content = contentRef.current
    const header = headerRef.current
    const seam = seamRef.current
    if (!content || !header || !seam) return

    // Initial windowed geometry (skip on mobile — CSS sheet takes over).
    if (!isMobile()) {
      const saved = loadSize(id)
      const offset = (cascade++ % 6) * 28
      content.style.position = 'fixed'
      content.style.left = Math.round(window.innerWidth * 0.32 + offset) + 'px'
      content.style.top = 56 + offset + 'px'
      content.style.width = (saved?.w ?? 640) + 'px'
      content.style.height = (saved?.h ?? Math.round(window.innerHeight * 0.7)) + 'px'
    }

    const cleanups = [
      makeWindowDraggable(content, header),
      makeWindowResizable(content, id),
      makeSplitSeam(seam, content, id),
      attachReflow(),
    ]
    return () => {
      undock(content) // clear body reflow classes/vars this window owns
      cleanups.forEach((fn) => fn())
    }
  }, [id])

  const dock = (side: 'left' | 'right') => {
    const content = contentRef.current
    if (!content) return
    if (isDocked(content) && content.classList.contains(`modal-${side}-docked`)) undock(content)
    else applyEdgeDock(content, side)
  }

  return (
    <div className="modal">
      <div ref={contentRef} className="modal-content">
        <div ref={headerRef} className="modal-header">
          <div className="modal-title">{title}</div>
          {headerControls}
          <div className="modal-win-controls">
            <button title="Dock left" aria-label="Dock left" onClick={() => dock('left')}>⊣</button>
            <button title="Dock right" aria-label="Dock right" onClick={() => dock('right')}>⊢</button>
            <button title="Close" aria-label="Close" onClick={onClose}>×</button>
          </div>
        </div>
        {/* Split seam — visible only when right-docked (CSS) */}
        <div ref={seamRef} className="split-seam" aria-hidden />
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}
