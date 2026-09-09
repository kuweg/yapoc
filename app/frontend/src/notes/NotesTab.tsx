import { useCallback, useEffect, useRef, useState } from 'react'
import { BookOpen, Code2, Columns2, Download, FilePlus2, GitBranch, Link2, MessageSquarePlus, Pin, RefreshCw, Save, Search, Trash2, Upload } from 'lucide-react'
import { StudioDialog } from '../studio/StudioDialog'
import { useAppStore } from '../store/appStore'
import { useSessionStore } from '../store/session'
import { useWorkspaceStore } from '../store/workspaceStore'
import { useArtifactsStore } from '../store/artifactsStore'
import { useFileViewerStore } from '../store/fileViewerStore'
import { useAgentChatStore } from '../store/agentChatStore'
import { createNote, findNote, listNotes, noteTarget, readNote, saveNote, trashNote, type Note, type NoteSummary } from './api'
import { useNotesStore } from './store'
import { headingId, NoteMarkdown } from './NoteMarkdown'
import { NotesGraph } from './NotesGraph'
import './notes.css'

type Mode = 'preview' | 'edit' | 'split' | 'graph'
export function NotesTab() {
  const [notes, setNotes] = useState<NoteSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [reading, setReading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [query, setQuery] = useState('')
  const [note, setNote] = useState<Note | null>(null)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [mode, setMode] = useState<Mode>('preview')
  const [creating, setCreating] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [creatingBusy, setCreatingBusy] = useState(false)
  const [formError, setFormError] = useState('')
  const [confirmTrash, setConfirmTrash] = useState(false)
  const [linkPicker, setLinkPicker] = useState(false)
  const [linkQuery, setLinkQuery] = useState('')
  const editor = useRef<HTMLTextAreaElement>(null)
  const importInput = useRef<HTMLInputElement>(null)
  const latest = useRef({ note, draft })
  latest.current = { note, draft }
  const inFlight = useRef<Promise<Note> | null>(null)
  const pendingHeading = useRef('')
  const selectedId = useNotesStore(s => s.selectedId)
  const select = useNotesStore(s => s.select)
  const capture = useNotesStore(s => s.capture)
  const activeTab = useAppStore(s => s.activeTab)
  const pinned = useSessionStore(s => s.sessions.find(session => session.id === s.activeId)?.noteContext)
  const isPinned = Boolean(pinned?.some(p => p.id === note?.id))

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listNotes()
      setNotes(result.notes)
      if (result.skipped.length) setNotice(`${result.skipped.length} files could not be indexed (unsupported size, filename, or encoding).`)
      setError('')
    } catch (e) { setError(String((e as Error).message)) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { if (activeTab === 'notes') void refresh() }, [activeTab, refresh])

  const open = useCallback(async (id: string) => {
    setReading(true)
    setError('')
    try {
      const saved = await readNote(id)
      if (useNotesStore.getState().selectedId !== id) return
      const restored = useNotesStore.getState().drafts[id]
      setNote(restored ? { ...saved, revision: restored.revision } : saved)
      setDraft(restored?.content ?? saved.content)
      if (restored && restored.revision !== saved.revision) setError('The saved note changed while you had a draft. Download your draft or discard it and reload before editing.')
    } catch (e) { if (useNotesStore.getState().selectedId === id) { setNote(null); setError((e as Error).message) } }
    finally { if (useNotesStore.getState().selectedId === id) setReading(false) }
  }, [])
  useEffect(() => {
    if (selectedId) void open(selectedId)
    else { setNote(null); setDraft('') }
  }, [selectedId, open])
  useEffect(() => {
    const current = latest.current
    if (activeTab === 'notes' && current.note?.id === useNotesStore.getState().selectedId
      && current.note && current.draft === current.note.content && !inFlight.current) void open(current.note.id)
  }, [activeTab, open])
  useEffect(() => {
    if (capture) { setNewTitle(capture.title); setFormError(''); setCreating(true) }
  }, [capture])

  async function persistCurrent(): Promise<Note | null> {
    if (inFlight.current) await inFlight.current
    const { note: current, draft: content } = latest.current
    if (!current || content === current.content) return current
    const request = saveNote(current.id, content, current.revision)
    inFlight.current = request
    setSaving(true)
    try {
      const saved = await request
      setNotes(items => items.map(item => item.id === saved.id ? saved : item))
      const pending = useNotesStore.getState().drafts[saved.id]
      if (pending && pending.content !== saved.content) useNotesStore.getState().setDraft(saved.id, pending.content, saved.revision)
      else useNotesStore.getState().clearDraft(saved.id)
      if (latest.current.note?.id === saved.id) {
        latest.current.note = saved
        setNote(saved)
        setError('')
      }
      return saved
    } catch (e) { setError((e as Error).message); throw e }
    finally { inFlight.current = null; setSaving(false) }
  }
  useEffect(() => {
    if (!note || draft === note.content || saving || error || reading) return
    const timer = window.setTimeout(() => { void persistCurrent().catch(() => {}) }, 900)
    return () => clearTimeout(timer)
  }, [draft, note, saving, error, reading])
  useEffect(() => {
    const onUnload = (event: BeforeUnloadEvent) => { if (latest.current.note && latest.current.draft !== latest.current.note.content) { event.preventDefault(); event.returnValue = '' } }
    window.addEventListener('beforeunload', onUnload)
    return () => window.removeEventListener('beforeunload', onUnload)
  }, [])
  useEffect(() => {
    if (!pendingHeading.current || reading || mode === 'edit') return
    const target = document.getElementById(`note-heading-${headingId(pendingHeading.current)}`)
    if (target) { target.scrollIntoView({ block: 'start' }); pendingHeading.current = '' }
  }, [note, reading, mode])

  function edit(content: string) {
    setDraft(content)
    latest.current.draft = content
    if (note) {
      try { useNotesStore.getState().setDraft(note.id, content, note.revision) }
      catch { setNotice('Browser draft storage is full. Keep this page open until the note is saved to disk.') }
    }
  }
  async function navigate(target: string) {
    try { await persistCurrent() } catch { return }
    const [name, anchor] = target.split('#', 2)
    pendingHeading.current = anchor || ''
    const found = name ? findNote(notes, name) : note
    if (found) {
      select(found.id)
      setMode('preview')
      if (found.id === note?.id && anchor) document.getElementById(`note-heading-${headingId(anchor)}`)?.scrollIntoView({ block: 'start' })
    } else { setNewTitle(name.replace(/\.md$/i, '')); setFormError(''); setCreating(true) }
  }
  async function add(title: string, content?: string) {
    setCreatingBusy(true); setFormError('')
    try {
      await persistCurrent()
      const created = await createNote(title, content)
      setNotes(items => [...items, created].sort((a, b) => a.title.localeCompare(b.title)))
      select(created.id); setCreating(false); setMode('edit'); setNewTitle('')
      useNotesStore.getState().setCapture(null)
    } catch (e) { setFormError((e as Error).message) }
    finally { setCreatingBusy(false) }
  }
  async function toChat(pin: boolean) {
    try {
      const saved = await persistCurrent()
      if (!saved) return
      if (pin) {
        if (!isPinned && (pinned?.length ?? 0) >= 12) { setNotice('This conversation already has 12 pinned notes. Unpin one first.'); return }
        useSessionStore.getState().toggleNoteContext({ id: saved.id, title: saved.title })
        setNotice(isPinned ? 'Note removed from conversation context.' : 'Pinned to this conversation. Its latest saved contents will accompany each new task.')
      } else {
        useWorkspaceStore.getState().close()
        useArtifactsStore.getState().close()
        useFileViewerStore.getState().closeFile()
        useAgentChatStore.getState().setSelectedLogAgent(null)
        useWorkspaceStore.getState().setPendingInsertion(`@note:${encodeURIComponent(saved.id)} `)
        useAppStore.getState().setActiveTab('chat')
      }
    } catch { /* Save error is visible; do not insert a stale note. */ }
  }
  function download() {
    if (!note) return
    const url = URL.createObjectURL(new Blob([draft], { type: 'text/markdown;charset=utf-8' }))
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = note.id; anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  async function remove() {
    if (!note) return
    try {
      const saved = await persistCurrent()
      await trashNote(note.id, saved!.revision)
      useNotesStore.getState().clearDraft(note.id)
      useSessionStore.getState().removeNoteContext(note.id)
      setNotes(items => items.filter(item => item.id !== note.id)); select(null); setConfirmTrash(false)
      setNotice('Moved to the notes .trash folder. The Markdown file can be recovered there.')
    } catch (e) { setError((e as Error).message); setConfirmTrash(false) }
  }
  const filtered = notes.filter(n => `${n.title} ${n.excerpt} ${n.links.join(' ')}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
  const backlinks = note ? notes.filter(n => n.links.some(link => noteTarget(link) === noteTarget(note.id))) : []
  const dirty = Boolean(note && draft !== note.content)
  return <div className="notes-workspace" onKeyDown={event => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') { event.preventDefault(); void persistCurrent().catch(() => {}) }
  }}>
    <header className="studio-section-header notes-header"><div><h1>Notes</h1><p>Your knowledge, connected to your agents.</p></div>
      <button className="studio-secondary-button" onClick={() => { setNewTitle(''); setFormError(''); setCreating(true) }}><FilePlus2 size={16} />New note</button>
      <button className="studio-secondary-button" onClick={() => importInput.current?.click()} title="Import a Markdown file"><Upload size={16} /><span>Import</span></button>
      <input ref={importInput} type="file" accept=".md,text/markdown,text/plain" hidden onChange={async event => {
        const file = event.target.files?.[0]; event.target.value = ''
        if (!file) return
        if (file.size > 200_000) { setNotice('Import supports Markdown files up to 200 KB.'); return }
        useNotesStore.getState().setCapture({ title: file.name.replace(/\.md$/i, ''), content: await file.text() })
      }} />
      <button className="studio-secondary-button" onClick={() => { void refresh(); if (selectedId && !dirty && !saving) void open(selectedId) }} aria-label="Refresh notes"><RefreshCw size={16} /></button>
    </header>
    {notice && <div className="notes-notice" role="status">{notice}<button onClick={() => setNotice('')} aria-label="Dismiss notes notice">×</button></div>}
    <div className="notes-body">
      <aside className="notes-library" aria-label="Notes library">
        <label className="notes-search"><Search size={15} /><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search names and excerpts" aria-label="Search notes" /></label>
        <button className={`notes-graph-link ${mode === 'graph' ? 'is-active' : ''}`} onClick={() => setMode('graph')}><GitBranch size={16} />Links graph<span>{notes.length}</span></button>
        <div className="notes-list">
          {loading && <p className="notes-muted" role="status">Loading notes…</p>}
          {!loading && !filtered.length && <p className="notes-muted">{query ? 'No matching notes.' : 'Create or import your first note.'}</p>}
          {filtered.map(item => <button key={item.id} onClick={() => void navigate(item.id)} aria-label={item.title} aria-pressed={item.id === selectedId} className="notes-list-item">
            <span>{item.title}</span><small>{item.excerpt || 'Empty note'}</small><time>{new Date(item.updated_at).toLocaleDateString()}</time>
          </button>)}
        </div>
        <p className="notes-folder">Markdown files · app/projects/notes</p>
      </aside>
      <main className="notes-main">
        {error && <div className="studio-error" role="alert"><span>{error}</span>
          {note && <><button onClick={download}>Download draft</button><button onClick={() => { useNotesStore.getState().clearDraft(note.id); void open(note.id) }}>Discard draft and reload</button></>}
          {!note && <button onClick={() => { void refresh(); if (selectedId) void open(selectedId) }}>Try again</button>}
        </div>}
        {mode === 'graph' ? <NotesGraph notes={notes} selectedId={selectedId} onNavigate={target => void navigate(target)} />
          : reading ? <div className="studio-empty" role="status">Opening note…</div>
          : !note ? <div className="studio-empty notes-empty"><BookOpen size={32} /><h2>A place for connected thinking</h2><p>Write in Markdown. Link ideas with [[note names]]. Bring the right knowledge into a conversation.</p><button className="studio-primary-button" onClick={() => { setNewTitle(''); setFormError(''); setCreating(true) }}>Create a note</button></div>
          : <>
            <div className="notes-document-header"><div><h2>{note.title}</h2><span role="status">{saving ? 'Saving…' : error ? 'Save needs attention' : dirty ? 'Unsaved changes' : 'Saved to disk'}</span></div>
              <button className="studio-secondary-button" onClick={() => void toChat(false)}><MessageSquarePlus size={15} />Add to chat</button>
              <button className="studio-secondary-button" onClick={() => void toChat(true)} aria-pressed={isPinned}><Pin size={15} />{isPinned ? 'Pinned to context' : 'Pin as context'}</button>
            </div>
            <div className="notes-editor-toolbar"><div className="notes-modes" aria-label="Note view">
              {([{ id: 'preview', icon: BookOpen, label: 'Preview' }, { id: 'edit', icon: Code2, label: 'Edit' }, { id: 'split', icon: Columns2, label: 'Split' }] as const).map(({ id, icon: Icon, label }) =>
                <button key={id} aria-pressed={mode === id} onClick={() => setMode(id)}><Icon size={14} />{label}</button>)}
              </div><div className="notes-editor-actions">
              <button onClick={() => { setLinkQuery(''); setLinkPicker(true) }} title="Insert a note link" aria-label="Insert note link"><Link2 size={16} /></button>
              <button onClick={() => void persistCurrent().catch(() => {})} disabled={!dirty || saving} title="Save (Ctrl+S / Cmd+S)" aria-label="Save note"><Save size={16} /></button>
              <button onClick={download} title="Download Markdown" aria-label="Download note"><Download size={16} /></button>
              <button onClick={() => setConfirmTrash(true)} title="Move to trash" aria-label="Trash note"><Trash2 size={16} /></button>
              </div>
            </div>
            <div className="notes-document" data-mode={mode}>
              {mode !== 'preview' && <textarea ref={editor} value={draft} spellCheck={false} onChange={e => edit(e.target.value)} aria-label="Markdown editor" placeholder="Write Markdown. Link ideas with [[note names]]." />}
              {mode !== 'edit' && <div className="notes-preview"><NoteMarkdown content={draft} notes={notes} onNavigate={target => void navigate(target)} /></div>}
            </div>
            <footer className="notes-backlinks"><div><strong>Backlinks <span>{backlinks.length}</span></strong>{backlinks.length ? backlinks.map(n => <button key={n.id} onClick={() => void navigate(n.id)}>{n.title}</button>) : <span>No notes link here yet.</span>}</div>
              <div><strong>Outgoing</strong>{note.links.length ? note.links.map(link => <button key={link} className={findNote(notes, link) ? '' : 'is-missing'} onClick={() => void navigate(link)}>{link}{findNote(notes, link) ? '' : ' + create'}</button>) : <span>Add a [[wikilink]] to connect this note.</span>}</div>
            </footer>
          </>}
      </main>
    </div>
    {creating && <StudioDialog label="Create note" onClose={() => { setCreating(false); useNotesStore.getState().setCapture(null) }}><form onSubmit={event => { event.preventDefault(); void add(newTitle, capture?.content) }} className="notes-form"><h3>{capture ? 'Save as a note' : 'Create note'}</h3><label>Note name<input autoFocus value={newTitle} onChange={e => setNewTitle(e.target.value)} placeholder="Project ideas" maxLength={120} /></label><p>This name becomes the Markdown filename and its [[wikilink]] target.</p>{formError && <p role="alert" className="notes-form-error">{formError}</p>}<div><button className="studio-primary-button" disabled={!newTitle.trim() || creatingBusy}>{creatingBusy ? 'Creating…' : 'Create note'}</button><button type="button" className="studio-secondary-button" onClick={() => { setCreating(false); useNotesStore.getState().setCapture(null) }}>Cancel</button></div></form></StudioDialog>}
    {confirmTrash && note && <StudioDialog label="Trash note" onClose={() => setConfirmTrash(false)}><div className="notes-form"><h3>Move “{note.title}” to trash?</h3><p>The file will remain recoverable in app/projects/notes/.trash. Links to this note will become unresolved.</p><div><button className="studio-danger-button" onClick={() => void remove()}>Move to trash</button><button className="studio-secondary-button" onClick={() => setConfirmTrash(false)}>Cancel</button></div></div></StudioDialog>}
    {linkPicker && <StudioDialog label="Insert note link" onClose={() => setLinkPicker(false)}><div className="notes-form"><h3>Link a note</h3><input autoFocus aria-label="Find note to link" placeholder="Find a note…" value={linkQuery} onChange={e => setLinkQuery(e.target.value)} /><div className="notes-link-options">{notes.filter(n => n.title.toLocaleLowerCase().includes(linkQuery.toLocaleLowerCase())).map(n => <button key={n.id} onClick={() => {
      const start = editor.current?.selectionStart ?? draft.length, end = editor.current?.selectionEnd ?? draft.length
      edit(draft.slice(0, start) + `[[${n.title}]]` + draft.slice(end)); setLinkPicker(false); setMode('edit')
      requestAnimationFrame(() => editor.current?.focus())
    }}>{n.title}</button>)}</div></div></StudioDialog>}
  </div>
}
