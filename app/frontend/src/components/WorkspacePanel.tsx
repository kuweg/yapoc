import { useEffect, useMemo, useRef, useState } from 'react'
import { getTask, linkArtifactSource, listUploads, processUpload, uploadFiles } from '../api/client'
import { listArtifacts } from '../artifacts/api'
import type { Attachment } from '../api/types'
import { useWorkspaceStore } from '../store/workspaceStore'

const PROCESS_ACTIONS = [
  { action: 'extract', label: 'Extract' },
  { action: 'summarize', label: 'Summarize' },
  { action: 'analyze', label: 'Analyze' },
  { action: 'convert', label: 'Convert' },
  { action: 'generate_from', label: 'Generate from' },
] as const

function formatSize(size?: number): string {
  if (size === undefined) return 'Unknown size'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function uploadUrl(id: string, inline = false): string {
  return `/api/upload/${encodeURIComponent(id)}${inline ? '?inline=1' : ''}`
}

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

export function WorkspacePanel() {
  const close = useWorkspaceStore((state) => state.close)
  const setPendingInsertion = useWorkspaceStore((state) => state.setPendingInsertion)
  const inputRef = useRef<HTMLInputElement>(null)
  const [files, setFiles] = useState<Attachment[]>([])
  const [filter, setFilter] = useState('')
  const [selected, setSelected] = useState<Attachment | null>(null)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState('')
  const [uploadErrors, setUploadErrors] = useState<string[]>([])
  const [copied, setCopied] = useState(false)
  const [processingAction, setProcessingAction] = useState<string | null>(null)
  const [processResult, setProcessResult] = useState('')
  const [generatePrompt, setGeneratePrompt] = useState('')

  async function refreshUploads() {
    setLoading(true)
    setError('')
    try {
      const response = await listUploads()
      setFiles(response.files)
      setSelected((current) => current && response.files.find((file) => file.id === current.id) ? current : null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load uploaded files')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void refreshUploads() }, [])

  const filteredFiles = useMemo(() => {
    const query = filter.trim().toLowerCase()
    if (!query) return files
    return files.filter((file) =>
      file.name.toLowerCase().includes(query) || file.mime.toLowerCase().includes(query),
    )
  }, [files, filter])

  async function handleUpload(fileList: FileList | File[]) {
    const selectedFiles = Array.from(fileList)
    if (!selectedFiles.length || uploading) return
    setUploading(true)
    setError('')
    setUploadErrors([])
    try {
      const response = await uploadFiles(selectedFiles)
      setUploadErrors(response.errors.map(({ name, error: message }) => `${name}: ${message}`))
      setFiles((current) => {
        const uploadedIds = new Set(response.files.map((file) => file.id))
        return [...response.files, ...current.filter((file) => !file.id || !uploadedIds.has(file.id))]
      })
      if (response.files.length) setSelected(response.files[0])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to upload files')
    } finally {
      setUploading(false)
    }
  }

  async function copyId() {
    if (!selected?.id) return
    try {
      await navigator.clipboard.writeText(selected.id)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      setError('Unable to copy upload ID')
    }
  }

  async function processSelected(action: string) {
    if (!selected?.id || processingAction) return
    if (action === 'generate_from' && !generatePrompt.trim()) {
      setProcessResult('Enter a prompt for Generate from.')
      return
    }

    const fileId = selected.id
    const fileName = selected.name
    setProcessingAction(action)
    setProcessResult('Processing…')
    try {
      const queued = await processUpload(fileId, action, action === 'generate_from' ? generatePrompt.trim() : undefined)
      let task = await getTask(queued.task_id)
      const deadline = Date.now() + 120000
      while (!['done', 'error', 'blocked', 'cancelled'].includes(task.status) && Date.now() < deadline) {
        await sleep(1500)
        task = await getTask(queued.task_id)
      }
      if (!['done', 'error', 'blocked', 'cancelled'].includes(task.status)) {
        setProcessResult('Processing timed out; task may still be running.')
        return
      }
      if (task.status !== 'done') {
        setProcessResult(task.error || `Task ${task.status}.`)
        return
      }

      let linkedCount = 0
      try {
        const artifacts = await listArtifacts()
        const matchingArtifacts = artifacts.filter((artifact) => artifact.source_task === queued.task_id)
        await Promise.all(matchingArtifacts.map(async (artifact) => {
          await linkArtifactSource(artifact.id, fileId, fileName)
          linkedCount += 1
        }))
      } catch {
        // Processing succeeded; artifact linking is best-effort and only reported when confirmed.
      }
      const snippet = task.result?.trim().replace(/\s+/g, ' ').slice(0, 160)
      setProcessResult(`${snippet ? `Done — ${snippet}` : 'Done — see chat'}${linkedCount ? ` · Linked ${linkedCount} artifact${linkedCount === 1 ? '' : 's'}` : ''}`)
    } catch (err) {
      setProcessResult(err instanceof Error ? err.message : 'Unable to process file')
    } finally {
      setProcessingAction(null)
    }
  }

  const selectedUrl = selected?.id ? uploadUrl(selected.id, true) : ''

  return (
    <aside className="workspace-pane flex h-full min-w-0 flex-col border-l border-zinc-700 bg-zinc-900" aria-label="Workspace uploads">
      <header className="flex items-center gap-2 border-b border-zinc-700 px-3 py-2">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-zinc-100">Workspace</div>
          <div className="text-xs text-zinc-500">Uploaded files</div>
        </div>
        <button type="button" onClick={() => void refreshUploads()} disabled={loading || uploading} className="rounded px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50" aria-label="Refresh workspace uploads">↻</button>
        <button type="button" onClick={close} className="rounded px-2 py-1 text-sm text-zinc-300 hover:bg-zinc-700" aria-label="Close workspace">×</button>
      </header>

      <div className="space-y-3 border-b border-zinc-800 p-3">
        <input ref={inputRef} type="file" multiple className="hidden" onChange={(event) => {
          if (event.target.files) void handleUpload(event.target.files)
          event.target.value = ''
        }} />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragOver={(event) => { event.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(event) => { event.preventDefault(); setDragOver(false); void handleUpload(event.dataTransfer.files) }}
          className={`w-full border border-dashed px-3 py-5 text-center text-xs transition-colors ${dragOver ? 'border-[#FFB633] bg-[#FFB633]/10 text-[#FFB633]' : 'border-zinc-600 text-zinc-300 hover:border-[#FFB633] hover:text-[#FFB633]'}`}
        >
          {uploading ? 'Uploading files…' : 'Drop files here or click to browse'}
        </button>
        {uploadErrors.length > 0 && <div className="flex gap-2 border border-red-900 bg-red-950/40 p-2 text-xs text-red-300" role="alert">
          <span className="min-w-0 flex-1">{uploadErrors.length} file{uploadErrors.length === 1 ? '' : 's'} rejected: {uploadErrors.join('; ')}</span>
          <button type="button" onClick={() => setUploadErrors([])} className="text-red-200 hover:text-white" aria-label="Dismiss upload errors">×</button>
        </div>}
        <input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter name or type" className="w-full border border-zinc-700 bg-zinc-800 px-2 py-1.5 text-xs text-zinc-100 placeholder:text-zinc-500 focus:border-[#FFB633] focus:outline-none" aria-label="Filter uploaded files" />
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {loading && <div className="p-4 text-sm text-zinc-400">Loading uploaded files…</div>}
        {error && <div className="p-4 text-sm text-red-400">{error}</div>}
        {!loading && !error && filteredFiles.length === 0 && <div className="p-4 text-sm text-zinc-400">{files.length ? 'No uploaded files match this filter.' : 'No uploaded files yet.'}</div>}
        {!loading && !error && filteredFiles.map((file) => <button key={file.id ?? file.name} type="button" onClick={() => { setSelected(file); setCopied(false); setProcessResult('') }} className={`block w-full border-b border-zinc-800 px-3 py-3 text-left transition-colors hover:bg-zinc-800 ${selected?.id === file.id ? 'bg-zinc-800' : ''}`}>
          <div className="truncate text-sm text-zinc-100" title={file.name}>{file.name}</div>
          <div className="mt-1 flex items-center gap-2 text-xs text-zinc-500"><span className="truncate">{file.mime}</span><span>·</span><span>{formatSize(file.size)}</span></div>
        </button>)}
      </div>

      {selected?.id && <section className="border-t border-zinc-700 p-3">
        <div className="mb-2 truncate text-xs text-zinc-300" title={selected.name}>{selected.name}</div>
        <iframe title={`Preview of ${selected.name}`} src={selectedUrl} className="h-40 w-full border border-zinc-700 bg-zinc-950" />
        <div className="mt-2 flex items-center gap-2">
          <a href={uploadUrl(selected.id)} download={selected.name} className="text-xs text-[#FFB633] hover:underline">Download</a>
          <button type="button" onClick={() => void copyId()} className="text-xs text-zinc-300 hover:text-[#FFB633]">{copied ? 'Copied' : 'Copy ID'}</button>
          <button type="button" onClick={() => window.open(selectedUrl, '_blank', 'noopener,noreferrer')} className="text-xs text-zinc-300 hover:text-[#FFB633]" title="Open inline preview in a new tab">Open</button>
        </div>
        <div className="mt-3 border-t border-zinc-800 pt-3">
          <div className="mb-2 text-xs font-medium text-zinc-300">Actions</div>
          <button type="button" onClick={() => setPendingInsertion(`@file:${selected.id} `)} className="mb-2 text-xs text-[#FFB633] hover:underline">Use in chat</button>
          <div className="flex flex-wrap gap-1.5">
            {PROCESS_ACTIONS.map(({ action, label }) => <button key={action} type="button" disabled={Boolean(processingAction)} onClick={() => void processSelected(action)} className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:border-[#FFB633] hover:text-[#FFB633] disabled:cursor-not-allowed disabled:opacity-50">
              {processingAction === action ? 'Processing…' : label}
            </button>)}
          </div>
          <input value={generatePrompt} onChange={(event) => setGeneratePrompt(event.target.value)} placeholder="Generate from prompt" className="mt-2 w-full border border-zinc-700 bg-zinc-800 px-2 py-1.5 text-xs text-zinc-100 placeholder:text-zinc-500 focus:border-[#FFB633] focus:outline-none" aria-label="Generate from prompt" />
          {processResult && <div className="mt-2 text-xs text-zinc-400" role="status">{processResult}</div>}
        </div>
      </section>}
    </aside>
  )
}
