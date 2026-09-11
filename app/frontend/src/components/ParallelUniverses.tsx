import { useEffect, useState } from 'react'
import { GitBranch, X } from 'lucide-react'
import { useUniverseStore } from '../store/universeStore'
import { useAppStore } from '../store/appStore'
import { useSessionStore } from '../store/session'
import { useAgentChatStore } from '../store/agentChatStore'
import { StudioDialog } from '../studio/StudioDialog'
import './parallelUniverses.css'

type Check = { command: string; exit_code: number; output: string }
type Run = { id: string; letter: string; approach: string; status: string; summary: string; checks: Check[]; cost_usd: number; branch: string; preview_url?: string | null; preview_available?: boolean }
type Mission = { id: string; objective: string; requirements: string; budget_usd: number; runs: Run[]; integration?: { branch: string; status: string; checks: Check[] } | null }
const active = ['preparing', 'running', 'checking']
async function request<T>(path = '', method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api/universes${path}`, { method, headers: { 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) })
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The request could not be completed. Check the supplied values.')
  return data
}

function Attempt({ mission, run, refresh }: { mission: Mission; run: Run; refresh: () => void }) {
  const [view, setView] = useState<'Preview' | 'Changes' | 'Checks' | 'Activity'>('Preview')
  const [detail, setDetail] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let live = true
    if (view === 'Changes') request<{ stat: string; patch: string }>(`/${mission.id}/${run.letter}/changes`).then(data => { if (live) setDetail(`${data.stat}\n${data.patch}`) }).catch(() => { if (live) setDetail('Changes could not be loaded.') })
    if (view === 'Activity') request<Array<{ type: string; name?: string; text?: string; result?: string }>>(`/${mission.id}/${run.letter}/activity`).then(data => { if (live) setDetail(data.map(e => `${e.type}: ${e.name || e.text || e.result || ''}`).join('\n')) }).catch(() => { if (live) setDetail('Activity could not be loaded.') })
    return () => { live = false }
  }, [view, mission.id, run.letter, run.status])
  async function action(name: string) {
    setBusy(true); setError('')
    try { await request(`/${mission.id}/${run.letter}/${name}`, 'POST'); refresh() }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  const local = ['localhost', '127.0.0.1'].includes(window.location.hostname)
  return <section className={`universe-attempt universe-${run.letter}`} aria-label={`Universe ${run.letter.toUpperCase()}`}>
    <header><span className="universe-badge">{run.letter.toUpperCase()}</span><div><h3>{run.approach}</h3><p>{run.status.replace(/_/g, ' ')} · ${run.cost_usd.toFixed(3)} estimated</p></div></header>
    <div className="universe-tabs" aria-label={`Universe ${run.letter.toUpperCase()} views`}>{(['Preview', 'Changes', 'Checks', 'Activity'] as const).map(tab => <button key={tab} aria-pressed={tab === view} onClick={() => setView(tab)}>{tab}</button>)}</div>
    <div className="universe-output">
      {view === 'Preview' && (run.preview_url && local
        ? <><p className="universe-muted">Static preview · application APIs disabled</p><iframe title={`Universe ${run.letter.toUpperCase()} preview`} sandbox="allow-scripts" referrerPolicy="no-referrer" src={run.preview_url} /></>
        : <div className="universe-empty"><GitBranch size={28} /><p>{active.includes(run.status) ? 'This approach is taking shape.' : run.preview_url ? 'Preview is available in a browser on the YAPOC host.' : 'No static frontend preview was produced.'}</p><span>Changes and checks are available in the tabs above.</span>{run.preview_available && local && <button disabled={busy} onClick={() => void action('preview')}>Start preview</button>}</div>)}
      {view === 'Checks' && (run.checks.length ? run.checks.map((check, i) => <div key={i}><strong>{check.exit_code === 0 ? 'Passed' : 'Failed'}</strong><pre>{check.command}{'\n'}{check.output}</pre></div>) : <p className="universe-muted">No verified checks yet.</p>)}
      {(view === 'Changes' || view === 'Activity') && <pre>{detail || 'No recorded output yet.'}</pre>}
    </div>
    {run.summary && <details><summary>Result and limitations</summary><p className="universe-result">{run.summary}</p></details>}
    {error && <p role="alert" className="universe-error">{error}</p>}
    <footer>
      <button onClick={() => { useAgentChatStore.getState().setSelectedLogAgent(run.id); useUniverseStore.getState().close() }}>Agent flow</button>
      {active.includes(run.status) ? <button disabled={busy} onClick={() => void action('stop')}>Stop {run.letter.toUpperCase()}</button>
        : <button className="universe-primary" disabled={busy || run.status !== 'completed' || !run.checks.length || run.checks.some(c => c.exit_code !== 0) || mission.runs.some(r => active.includes(r.status)) || Boolean(mission.integration)} onClick={() => void action('choose')}>{busy ? 'Checking integration…' : `Choose ${run.letter.toUpperCase()}`}</button>}
    </footer>
  </section>
}

export function ParallelUniverses() {
  const tab = useAppStore(s => s.activeTab)
  const sessionId = useSessionStore(s => s.activeId)
  const ui = useUniverseStore()
  const [missions, setMissions] = useState<Mission[]>([])
  const [selected, setSelected] = useState<Mission | null>(null)
  const [objective, setObjective] = useState('')
  const [requirements, setRequirements] = useState('')
  const [a, setA] = useState('Conservative: a small, familiar solution')
  const [b, setB] = useState('Experimental: explore a different design')
  const [minutes, setMinutes] = useState(15)
  const [budget, setBudget] = useState(2)
  const [check, setCheck] = useState('npm --prefix app/frontend run build')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [mobile, setMobile] = useState('a')
  const [tick, setTick] = useState(0)
  useEffect(() => { setObjective(ui.draft); setError('') }, [ui.draft, ui.open])
  useEffect(() => {
    let live = true
    const load = async () => {
      if (!sessionId || document.hidden || (tab !== 'chat' && !ui.open)) return
      try {
        const data = await request<Mission[]>(`?session_id=${encodeURIComponent(sessionId)}`)
        if (live) setMissions(data)
        if (ui.open && ui.missionId) {
          const item = await request<Mission>(`/${ui.missionId}`)
          if (live) setSelected(item)
        }
      } catch { if (live && ui.open) setError('Comparison status is unavailable. Reconnecting…') }
    }
    setSelected(null); setMissions([])
    void load(); const timer = setInterval(load, ui.open ? 3000 : 10000)
    return () => { live = false; clearInterval(timer) }
  }, [sessionId, ui.missionId, ui.open, tick, tab])
  async function launch(event: React.FormEvent) {
    event.preventDefault()
    if (!useSessionStore.getState().activeId) useSessionStore.getState().newSession()
    const launchSession = useSessionStore.getState().activeId!
    setBusy(true); setError('')
    try {
      const mission = await request<Mission>('', 'POST', { objective, requirements, approaches: [a, b], minutes, budget_usd: budget, session_id: launchSession, check_command: check })
      setSelected(mission); ui.compare(mission.id)
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  return <>
    {missions.length > 0 && <div className="universe-missions" aria-label="Parallel comparisons">{missions.slice(0, 3).map(mission => <button key={mission.id} onClick={() => ui.compare(mission.id)}><GitBranch size={15} /><span>{mission.objective}</span><small>{mission.runs.map(r => `${r.letter.toUpperCase()} · ${r.status.replace(/_/g, ' ')}`).join(' / ')}</small></button>)}</div>}
    {ui.open && <StudioDialog label="Parallel universes" onClose={ui.close}><div className="universe-dialog">
      <header className="universe-header"><div><p className="universe-muted">CONVERSATION / PARALLEL UNIVERSES</p><h2>{ui.missionId ? selected?.objective || 'Loading comparison…' : 'One objective. Two approaches.'}</h2></div><button aria-label="Close parallel universes" onClick={ui.close}><X size={20} /></button></header>
      {error && <p role="alert" className="universe-error">{error}</p>}
      {!ui.missionId ? <form className="universe-setup" onSubmit={launch}>
        <label>What should we achieve?<textarea required minLength={3} maxLength={6000} value={objective} onChange={e => setObjective(e.target.value)} /></label>
        <div className="universe-form-grid"><label>A · Approach<input required maxLength={2000} value={a} onChange={e => setA(e.target.value)} /></label><label>B · Approach<input required maxLength={2000} value={b} onChange={e => setB(e.target.value)} /></label></div>
        <label>Shared requirements<textarea maxLength={6000} value={requirements} onChange={e => setRequirements(e.target.value)} /></label>
        <label>Required check command<input required value={check} onChange={e => setCheck(e.target.value)} /></label>
        <div className="universe-form-grid"><label>Minutes per attempt<input type="number" required min={1} max={60} value={minutes} onChange={e => setMinutes(Number(e.target.value))} /></label><label>Total estimated spending limit ($)<input type="number" required min={0.1} max={100} step={0.1} value={budget} onChange={e => setBudget(Number(e.target.value))} /></label></div>
        <p className="universe-muted">Each attempt gets half the spending limit. Usage is checked after model responses, so an in-flight response can exceed the estimate. Your working files stay unchanged; choosing prepares a separate integration branch.</p>
        <button className="universe-primary" disabled={busy}>{busy ? 'Preparing isolated worktrees…' : 'Start 2 universes'}</button>
      </form> : selected && <>
        <div className="universe-toolbar"><span>Total ${selected.runs.reduce((sum, r) => sum + r.cost_usd, 0).toFixed(3)} / ${selected.budget_usd.toFixed(2)} estimated</span><button disabled={!selected.runs.some(r => active.includes(r.status))} onClick={() => { void request(`/${selected.id}/stop`, 'POST').then(() => setTick(n => n + 1)).catch(e => setError(e.message)) }}>Stop all</button></div>
        {selected.integration && <div className="universe-integration"><strong>Integration: {selected.integration.status.replace(/_/g, ' ')}</strong><code>{selected.integration.branch}</code><p>Your live workspace is unchanged. Review this branch before merging.</p>{selected.integration.checks.map((c,i) => <details key={i}><summary>{c.exit_code === 0 ? 'Checks passed' : 'Checks failed'}</summary><pre>{c.output}</pre></details>)}</div>}
        <div className="universe-mobile-tabs">{['a', 'b'].map(letter => <button key={letter} aria-pressed={mobile === letter} onClick={() => setMobile(letter)}>Universe {letter.toUpperCase()}</button>)}</div>
        <div className="universe-comparison">{selected.runs.map(run => <div key={run.id} data-mobile-active={mobile === run.letter}><Attempt mission={selected} run={run} refresh={() => setTick(n => n + 1)} /></div>)}</div>
      </>}
    </div></StudioDialog>}
  </>
}
