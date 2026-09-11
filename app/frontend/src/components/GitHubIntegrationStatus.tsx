import { useEffect, useState } from 'react'

interface GitHubStatus {
  enabled: boolean
  repositories: string[]
  connection: string
  last_successful_check: string | null
  write_enabled: boolean
  mcp_enabled: boolean
  mcp_connection: string
  summary: { message: string; stale_issues: number; stale_pull_requests: number } | null
}

export function GitHubIntegrationStatus() {
  const [status, setStatus] = useState<GitHubStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function load(check = false) {
    setBusy(true)
    try {
      const response = await fetch(`/api/integrations/github${check ? '/check' : ''}`, { method: check ? 'POST' : 'GET' })
      if (!response.ok) throw new Error('unavailable')
      setStatus(await response.json())
      setError('')
    } catch { setError('GitHub integration status unavailable. Check that the backend is running and has loaded the GitHub integration.') }
    finally { setBusy(false) }
  }
  useEffect(() => { void load() }, [])
  return <section aria-label="GitHub integration" className="border-b border-zinc-800 bg-zinc-900/60 p-3 text-xs text-zinc-300 shrink-0">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="font-medium">GitHub · {status ? (status.enabled ? 'Enabled' : 'Disabled') : 'Status unavailable'} · Writes {status ? (status.write_enabled ? 'enabled' : 'disabled') : 'unknown'}</span>
      <button disabled={busy || !status?.enabled} onClick={() => void load(true)} className="border border-zinc-700 px-3 py-2 text-amber-400 disabled:opacity-40">{busy ? 'Checking…' : 'Check GitHub'}</button>
    </div>
    {error && <button disabled={busy} onClick={() => void load()} className="mt-2 border border-zinc-700 px-3 py-2 disabled:opacity-40">Retry connection</button>}
    {error && <p role="status" className="mt-2 text-amber-400">{error}</p>}
    {status && <div className="mt-2 space-y-1 break-words">
      <p>{status.repositories.join(', ') || 'No repositories configured'} · {status.connection}</p>
      <p>Last successful check: {status.last_successful_check ? new Date(status.last_successful_check).toLocaleString() : 'Never'}</p>
      <p>MCP: {status.mcp_enabled ? status.mcp_connection : 'Disabled'}</p>
      {status.summary && <p>{status.summary.message} Stale: {status.summary.stale_pull_requests} PRs, {status.summary.stale_issues} issues.</p>}
    </div>}
  </section>
}
