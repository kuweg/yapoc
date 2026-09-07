import { useEffect, useState } from 'react'
import { useFileViewerStore } from '../store/fileViewerStore'

type FileKind = 'text' | 'image' | 'pdf' | 'pptx' | 'binary'

interface FilePreview {
  path: string
  name: string
  size: number
  ext: string
  kind: FileKind
  content?: string
}

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

export function FileViewerPane() {
  const selectedFile = useFileViewerStore((s) => s.selectedFile)
  const closeFile = useFileViewerStore((s) => s.closeFile)
  const [preview, setPreview] = useState<FilePreview | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!selectedFile) {
      setPreview(null)
      setError('')
      return
    }
    const controller = new AbortController()
    setLoading(true)
    setError('')
    setPreview(null)
    fetch(`/api/files/preview?path=${encodeURIComponent(selectedFile.path)}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => null)
          throw new Error(body?.detail || `Preview failed (${response.status})`)
        }
        return response.json() as Promise<FilePreview>
      })
      .then(setPreview)
      .catch((err: unknown) => {
        if ((err as { name?: string })?.name !== 'AbortError') {
          setError(err instanceof Error ? err.message : 'Unable to load file preview')
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [selectedFile?.path])

  if (!selectedFile) return null

  const name = preview?.name || selectedFile.name || selectedFile.path.split('/').pop() || selectedFile.path
  const inlineUrl = `/api/files/download?path=${encodeURIComponent(selectedFile.path)}&inline=1`
  const downloadUrl = `/api/files/download?path=${encodeURIComponent(selectedFile.path)}`

  return (
    <aside className="file-viewer-pane flex h-full min-w-0 flex-col border-l border-zinc-700 bg-zinc-900" aria-label="File viewer">
      <header className="flex items-center gap-2 border-b border-zinc-700 px-3 py-2">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-zinc-100" title={selectedFile.path}>{name}</div>
          {preview && <div className="truncate text-xs text-zinc-500">{preview.ext || preview.kind} · {formatSize(preview.size)}</div>}
        </div>
        <a href={downloadUrl} download={name} className="rounded px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-700" title="Download file">Download</a>
        <button type="button" onClick={closeFile} className="rounded px-2 py-1 text-sm text-zinc-300 hover:bg-zinc-700" aria-label="Close file viewer">×</button>
      </header>
      <div className="min-h-0 flex-1 overflow-auto">
        {loading && <div className="p-4 text-sm text-zinc-400">Loading preview…</div>}
        {error && <div className="p-4 text-sm text-red-400">{error}</div>}
        {preview?.kind === 'text' && <pre className="whitespace-pre-wrap break-words p-4 text-xs leading-relaxed text-zinc-200">{preview.content || '(empty file)'}</pre>}
        {preview?.kind === 'image' && <div className="flex h-full items-center justify-center p-4"><img src={inlineUrl} alt={name} className="max-h-full max-w-full object-contain" /></div>}
        {preview?.kind === 'pdf' && <iframe src={inlineUrl} title={name} className="h-full min-h-[480px] w-full border-0 bg-white" />}
        {preview?.kind === 'pptx' && <div className="p-4 text-sm text-zinc-400">Presentation preview is unavailable here. Use Download to open it locally.</div>}
        {preview?.kind === 'binary' && <div className="p-4 text-sm text-zinc-400">No inline preview is available for this file. Use Download to open it locally.</div>}
      </div>
    </aside>
  )
}
