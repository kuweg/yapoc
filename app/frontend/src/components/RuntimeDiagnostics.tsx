import { useEffect, useState } from 'react'
interface Report {
  runtime: { boot_id: string; started_at: string; restart_required: boolean }
  workers: { agent: string; current: boolean }[]
  network_enabled: boolean
  last_check: null | { checked_at: string; status: string; checks: { name: string; status: string; detail: string }[] }
}
export function RuntimeDiagnostics() {
  const [report, setReport] = useState<Report | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/health/runtime', { signal: controller.signal }).then(r => { if (!r.ok) throw new Error(); return r.json() }).then(setReport).catch(() => { if (!controller.signal.aborted) setError('Runtime status unavailable.') })
    return () => controller.abort()
  }, [])
  async function check() {
    setBusy(true); setError('')
    try {
      const r = await fetch('/api/health/runtime/check', { method: 'POST' })
      if (!r.ok) throw new Error()
      setReport(await r.json())
    } catch { setError('Checks could not finish. Check the backend connection and retry.') }
    finally { setBusy(false) }
  }
  return <section className="rounded-lg border border-zinc-800 p-4 space-y-3" aria-label="Runtime diagnostics">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h3 className="text-sm font-semibold">Runtime diagnostics</h3>
      <button className="rounded border border-emerald-700 px-3 py-2 text-xs text-emerald-300 disabled:opacity-50" disabled={busy} onClick={check}>{busy ? 'Checking execution tools…' : 'Run diagnostics'}</button>
    </div>
    <p className="text-xs text-zinc-400">Checks DNS, HTTPS, Poetry, dependencies and project access through the agent tools. Runs only when requested.</p>
    {error && <p role="alert" className="text-xs text-amber-300">{error}</p>}
    {report && <>
      <p className="text-xs text-zinc-400">Started {new Date(report.runtime.started_at).toLocaleString()} · Network {report.network_enabled ? 'enabled' : 'disabled'} · {report.runtime.restart_required ? 'Backend restart required' : 'Backend code current'}</p>
      {report.workers.filter(w => !w.current).map(w => <p key={w.agent} className="text-xs text-amber-300">{w.agent}: older worker code; restart required.</p>)}
      {report.last_check ? <>
        <p className="text-xs text-zinc-400">Last check: {new Date(report.last_check.checked_at).toLocaleString()}</p>
        <div className="grid gap-2 sm:grid-cols-2">{report.last_check.checks.map(c => <div key={c.name} className="rounded bg-zinc-900 p-3 text-xs">
          <strong className={c.status === 'ok' ? 'text-emerald-300' : 'text-amber-300'}>{c.name}: {c.status}</strong><p className="mt-1 text-zinc-400">{c.detail}</p>
        </div>)}</div>
      </> : <p className="text-xs text-zinc-500">Diagnostics have not run since startup.</p>}
    </>}
  </section>
}
