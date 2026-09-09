import { useEffect, useState, useCallback } from 'react'
import { RefreshCw, HardDrive, Search, ExternalLink, Unplug } from 'lucide-react'
import {
  getDriveStatus,
  connectDrive,
  disconnectDrive,
  listDriveFiles,
  getDriveFileContent,
  type DriveStatus,
  type DriveFile,
} from '../api/driveClient'

const inputClass =
  'w-full bg-zinc-900 text-zinc-100 text-sm border border-zinc-800 rounded px-3 py-2 focus:outline-none focus:ring-1 focus:ring-zinc-600 placeholder-zinc-600'

function fmtSize(size?: string): string {
  if (!size) return '—'
  const n = Number(size)
  if (Number.isNaN(n)) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
  return `${(n / 1024 / 1024 / 1024).toFixed(1)} GB`
}

function fmtTime(iso?: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString()
}

function fmtType(mimeType: string): string {
  if (!mimeType) return '—'
  if (mimeType === 'application/vnd.google-apps.folder') return 'Folder'
  if (mimeType === 'application/vnd.google-apps.document') return 'Google Doc'
  if (mimeType === 'application/vnd.google-apps.spreadsheet') return 'Google Sheet'
  if (mimeType === 'application/vnd.google-apps.presentation') return 'Google Slides'
  if (mimeType.startsWith('image/')) return 'Image'
  if (mimeType.startsWith('video/')) return 'Video'
  if (mimeType.startsWith('audio/')) return 'Audio'
  if (mimeType.includes('pdf')) return 'PDF'
  return mimeType
}

export function DriveTab() {
  const [status, setStatus] = useState<DriveStatus | null>(null)
  const [statusLoading, setStatusLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // connect form state
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [connecting, setConnecting] = useState(false)
  const [connectHint, setConnectHint] = useState<string | null>(null)

  // file browser state
  const [query, setQuery] = useState('')
  const [files, setFiles] = useState<DriveFile[]>([])
  const [filesLoading, setFilesLoading] = useState(false)
  const [filesError, setFilesError] = useState<string | null>(null)
  const [preview, setPreview] = useState<{ name: string; summary: string } | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  const loadStatus = useCallback(() => {
    setStatusLoading(true)
    setError(null)
    getDriveStatus()
      .then(setStatus)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'failed'))
      .finally(() => setStatusLoading(false))
  }, [])

  useEffect(() => { loadStatus() }, [loadStatus])

  const browse = useCallback(async (q?: string) => {
    setFilesLoading(true)
    setFilesError(null)
    try {
      const res = await listDriveFiles(q || undefined)
      setFiles(res.files ?? [])
    } catch (e) {
      setFilesError(e instanceof Error ? e.message : 'failed')
    } finally {
      setFilesLoading(false)
    }
  }, [])

  // Auto-browse once connected.
  useEffect(() => {
    if (status?.connected) browse()
  }, [status?.connected, browse])

  const doConnect = async () => {
    setConnecting(true)
    setError(null)
    setConnectHint(null)
    try {
      const { auth_url } = await connectDrive(clientId.trim(), clientSecret.trim())
      window.open(auth_url, '_blank')
      setConnectHint('Complete authorization in the new tab, then click Refresh status.')
      setClientSecret('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'connect failed')
    } finally {
      setConnecting(false)
    }
  }

  const doDisconnect = async () => {
    if (!window.confirm('Disconnect Google Drive?')) return
    setError(null)
    try {
      await disconnectDrive()
      setFiles([])
      loadStatus()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'disconnect failed')
    }
  }

  const doSearch = () => browse(query)

  const doPreview = async (f: DriveFile) => {
    setPreviewLoading(true)
    setFilesError(null)
    try {
      const res = await getDriveFileContent(f.id)
      setPreview({ name: res.name || f.name, summary: res.summary })
    } catch (e) {
      setFilesError(e instanceof Error ? e.message : 'preview failed')
    } finally {
      setPreviewLoading(false)
    }
  }

  return (
    <div className="studio-settings relative flex flex-col h-full bg-zinc-950 text-zinc-100 overflow-hidden">
      <div className="studio-section-header">
        <div><h1>Google Drive</h1><p>Connect your Drive account and browse your files.</p></div>
        <button className="studio-secondary-button" onClick={loadStatus} aria-label="Refresh status"><RefreshCw size={16} /></button>
      </div>
      <div className="studio-settings-body">
        {error && <div role="alert" className="studio-error"><strong>Could not load or update Drive.</strong><span>{error}</span><button onClick={loadStatus}>Try again</button></div>}

        {/* ── Connection card ── */}
        <div className="border border-zinc-800 bg-zinc-900 rounded p-4 mb-6">
          <h2 className="text-sm font-medium text-zinc-100 mb-3">Connection</h2>
          {statusLoading ? (
            <div className="studio-loading" role="status">Checking connection…<div /><div /><div /></div>
          ) : status?.connected ? (
            <div className="space-y-3">
              <p className="text-sm text-zinc-300">
                Connected{status.user_email ? <> as <strong className="text-zinc-100">{status.user_email}</strong></> : null}
              </p>
              <button className="studio-danger-button" onClick={doDisconnect}><Unplug size={14} /> Disconnect</button>
            </div>
          ) : (
            <div className="space-y-3">
              <label className="block">
                <span className="block text-xs uppercase tracking-widest text-zinc-500 mb-1">OAuth Client ID</span>
                <input className={inputClass} value={clientId} placeholder="…apps.googleusercontent.com"
                  onChange={(e) => setClientId(e.target.value)} />
              </label>
              <label className="block">
                <span className="block text-xs uppercase tracking-widest text-zinc-500 mb-1">OAuth Client Secret</span>
                <input className={inputClass} type="password" value={clientSecret} placeholder="Client secret"
                  onChange={(e) => setClientSecret(e.target.value)} />
              </label>
              <button
                className="px-3 py-1.5 text-xs rounded bg-[#FFB633] text-zinc-900 font-medium disabled:opacity-50"
                onClick={doConnect}
                disabled={connecting || !clientId.trim() || !clientSecret.trim()}
              >
                {connecting ? 'Connecting…' : 'Connect Google Drive'}
              </button>
              {connectHint && <p className="text-xs text-zinc-400">{connectHint}</p>}
            </div>
          )}
        </div>

        {/* ── File browser ── */}
        <div>
          <h2 className="text-sm font-medium text-zinc-100 mb-3">Browse files</h2>
          <div className="flex gap-2 mb-4">
            <input
              className={inputClass}
              value={query}
              placeholder="Search files (e.g. name contains 'report')"
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') doSearch() }}
            />
            <button className="studio-secondary-button" onClick={doSearch} aria-label="Search files"><Search size={16} /> Search</button>
          </div>

          {filesError && <div role="alert" className="studio-error"><strong>Could not list files.</strong><span>{filesError}</span></div>}
          {filesLoading ? (
            <div className="studio-loading" role="status">Loading files…<div /><div /><div /></div>
          ) : files.length === 0 ? (
            !filesError && <div className="studio-empty"><HardDrive size={24} /><h2>No files</h2><p>Connect Drive and search to see your files.</p></div>
          ) : (
            <div className="studio-table-scroll">
              <table className="studio-table" aria-label="Drive files">
                <thead><tr><th>Name</th><th>Type</th><th>Modified</th><th>Size</th><th>Preview</th><th><span className="sr-only">Open</span></th></tr></thead>
                <tbody>
                  {files.map((f) => (
                    <tr key={f.id}>
                      <td><strong>{f.name}</strong></td>
                      <td>{fmtType(f.mime_type)}</td>
                      <td>{fmtTime(f.modified_time)}</td>
                      <td>{fmtSize(f.size)}</td>
                      <td>
                        <button className="studio-secondary-button" onClick={() => doPreview(f)} aria-label={`Preview ${f.name}`}>Preview</button>
                      </td>
                      <td>
                        {f.web_view_link ? (
                          <a className="studio-secondary-button" href={f.web_view_link} target="_blank" rel="noreferrer" aria-label={`Open ${f.name}`}><ExternalLink size={14} /> Open</a>
                        ) : (
                          <span className="text-xs text-zinc-600">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {previewLoading && <div className="studio-loading" role="status">Loading preview…<div /><div /><div /></div>}
          {preview && !previewLoading && (
            <div className="border border-zinc-800 bg-zinc-900 rounded p-4 mt-4">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-medium text-zinc-100">{preview.name}</h3>
                <button className="text-xs text-zinc-500 hover:text-zinc-300" onClick={() => setPreview(null)}>Close</button>
              </div>
              <pre className="text-xs text-zinc-300 whitespace-pre-wrap break-words max-h-96 overflow-y-auto">{preview.summary}</pre>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
