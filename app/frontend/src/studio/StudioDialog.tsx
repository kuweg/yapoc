import { useLayoutEffect, useRef, type ReactNode } from 'react'

/** Native dialogs supply focus containment, Escape handling and focus restoration. */
export function StudioDialog({ label, onClose, children }: { label: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null)
  useLayoutEffect(() => {
    const dialog = ref.current
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    dialog?.showModal()
    return () => {
      dialog?.close()
      if (opener?.isConnected) opener.focus()
    }
  }, [])
  return <dialog ref={ref} className="studio-dialog" aria-label={label}
    onCancel={event => { event.preventDefault(); onClose() }}>
    {children}
  </dialog>
}
