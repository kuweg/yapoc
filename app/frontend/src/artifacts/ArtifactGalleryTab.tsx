import { useEffect, useMemo, useState } from 'react'
import { Download, File, FileImage, FileText, Presentation, Search, Trash2, X } from 'lucide-react'
import { FileViewerPane } from '../components/FileViewerPane'
import { useFileViewerStore } from '../store/fileViewerStore'
import { deleteArtifact, listArtifacts } from './api'
import type { Artifact } from './types'

const kinds: Array<'all' | Artifact['kind']> = ['all', 'image', 'text', 'pdf', 'pptx', 'binary']

function formatSize(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function iconFor(kind: Artifact['kind']) {
  if (kind === 'image') return FileImage
  if (kind === 'text') return FileText
  if (kind === 'pptx') return Presentation
  return File
}

export function ArtifactGalleryTab() {
  const [items, setItems] = useState<Artifact[]>([])
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState<(typeof kinds)[number]>('all')
  const [sort, setSort] = useState<'newest' | 'name' | 'size'>('newest')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const selectedFile = useFileViewerStore(s => s.selectedFile)

  const load = () => {
    setLoading(true); setError('')
    listArtifacts().then(setItems).catch((e: unknown) => setError(e instanceof Error ? e.message : 'Unable to load artifacts')).finally(() => setLoading(false))
  }
  useEffect(load, [])

  const agents = useMemo(() => new Set(items.map(item => item.source_agent)).size, [items])
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    const filtered = items.filter(item => (kind === 'all' || item.kind === kind) && (!q
      || item.name.toLowerCase().includes(q) || item.source_agent.toLowerCase().includes(q)
      || (item.source_task || '').toLowerCase().includes(q)))
    return filtered.sort((a, b) => sort === 'name' ? a.name.localeCompare(b.name)
      : sort === 'size' ? b.size - a.size : b.updated_at.localeCompare(a.updated_at))
  }, [items, query, kind, sort])

  const open = (item: Artifact) => useFileViewerStore.getState().selectFile({ path: item.path, name: item.name })
  const remove = async (item: Artifact) => {
    if (confirmDelete !== item.id) { setConfirmDelete(item.id); return }
    try { await deleteArtifact(item.id); setItems(current => current.filter(x => x.id !== item.id)); setConfirmDelete(null) }
    catch (e) { setError(e instanceof Error ? e.message : 'Unable to delete artifact') }
  }

  return <section className="artifact-gallery-tab">
    <header className="artifact-gallery-header">
      <div><h1>Artifact gallery</h1><p>Everything your agents produced, with provenance and versions.</p></div>
      <div className="artifact-gallery-stats"><span><strong>{items.length}</strong> files</span><span><strong>{agents}</strong> agents</span></div>
    </header>
    <div className="artifact-gallery-toolbar">
      <label className="artifact-gallery-search"><Search size={15}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search files, agents, tasks…" aria-label="Search artifacts"/>{query && <button onClick={() => setQuery('')} aria-label="Clear search"><X size={13}/></button>}</label>
      <div className="artifact-kind-filter" aria-label="Artifact type filter">{kinds.map(value => <button key={value} aria-pressed={kind === value} onClick={() => setKind(value)}>{value}</button>)}</div>
      <select value={sort} onChange={e => setSort(e.target.value as typeof sort)} aria-label="Sort artifacts"><option value="newest">Newest</option><option value="name">Name</option><option value="size">Size</option></select>
    </div>
    {error && <div className="artifact-gallery-error" role="alert">{error}<button onClick={load}>Retry</button></div>}
    <div className="artifact-gallery-body">
      <div className="artifact-gallery-scroll">
        {loading && <div className="artifact-gallery-empty">Loading gallery…</div>}
        {!loading && shown.length === 0 && <div className="artifact-gallery-empty"><FileImage size={32}/><strong>{items.length ? 'No matching artifacts' : 'The gallery is empty'}</strong><span>Generated images, reports, charts and files will appear here.</span></div>}
        <div className="artifact-grid">{shown.map(item => {
          const Icon = iconFor(item.kind)
          const inlineUrl = `/api/files/download?path=${encodeURIComponent(item.path)}&inline=1`
          return <article className="artifact-card" key={item.id}>
            <button className="artifact-card-preview" onClick={() => open(item)} aria-label={`Preview ${item.name}`}>
              {item.kind === 'image' ? <img src={inlineUrl} alt="" loading="lazy"/> : <div className={`artifact-file-icon is-${item.kind}`}><Icon size={35}/><span>{item.name.split('.').pop()?.slice(0, 6) || item.kind}</span></div>}
              <span className="artifact-card-kind">{item.kind}</span>
            </button>
            <div className="artifact-card-copy"><button onClick={() => open(item)} title={item.name}>{item.name}</button><p><span>{item.source_agent}</span><span>v{item.version}</span><span>{formatSize(item.size)}</span></p><time dateTime={item.updated_at}>{new Date(item.updated_at).toLocaleString()}</time></div>
            <div className="artifact-card-actions"><button onClick={() => open(item)}>Preview</button><a href={`/api/files/download?path=${encodeURIComponent(item.path)}`} download={item.name} aria-label={`Download ${item.name}`}><Download size={14}/></a><button className={confirmDelete === item.id ? 'is-confirming' : ''} onClick={() => void remove(item)} onBlur={() => setConfirmDelete(null)} aria-label={confirmDelete === item.id ? `Confirm delete ${item.name}` : `Delete ${item.name}`}><Trash2 size={14}/>{confirmDelete === item.id && <span>Confirm</span>}</button></div>
          </article>
        })}</div>
      </div>
      {selectedFile && <div className="artifact-gallery-viewer"><FileViewerPane /></div>}
    </div>
  </section>
}
