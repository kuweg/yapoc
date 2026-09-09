import { Pin, X } from 'lucide-react'
import { useSessionStore } from '../store/session'
import { useAppStore } from '../store/appStore'
import { useNotesStore } from './store'

export function NoteContextBar() {
  const pins = useSessionStore(s => s.sessions.find(session => session.id === s.activeId)?.noteContext)
  if (!pins?.length) return null
  return <div className="note-context-bar" aria-label="Pinned note context"><Pin size={13} /><span>Context for this conversation</span>
    {pins.map(note => <span key={note.id} className="note-context-chip">
      <button title="Open note" onClick={() => { useNotesStore.getState().select(note.id); useAppStore.getState().setActiveTab('notes') }}>{note.title}</button>
      <button aria-label={`Unpin ${note.title}`} onClick={() => useSessionStore.getState().toggleNoteContext(note)}><X size={12} /></button>
    </span>)}
  </div>
}
