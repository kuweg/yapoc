import { ParallelUniverses } from './components/ParallelUniverses'
import { TaskProgressPanel } from './components/TaskProgress'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useSessionStore } from './store/session'
import { useAppStore } from './store/appStore'
import { useAgentChatStore } from './store/agentChatStore'
import { AgentSidebar } from './components/AgentSidebar'
import { ChatPanel } from './components/ChatPanel'
import { AgentChatFlowPanel } from './components/AgentChatFlowPanel'
import { StudioInspector, type InspectorPanel } from './studio/StudioInspector'
import { FileViewerPane } from './components/FileViewerPane'
import { useFileViewerStore } from './store/fileViewerStore'
import { useArtifactsStore } from './store/artifactsStore'
import { useWorkspaceStore } from './store/workspaceStore'
import { ArtifactsPanel } from './artifacts/ArtifactsPanel'
import { ArtifactGalleryTab } from './artifacts/ArtifactGalleryTab'
import { WhiteboardTab } from './whiteboard/WhiteboardTab'
import { WorkspacePanel } from './components/WorkspacePanel'
import { AgentDashboard } from './agent-status'
import { ThemeToggle } from './components/ThemeToggle'
import { MemoryGraphTab } from './memory-graph/components/MemoryGraphTab'
import { VaultTab } from './vault/components/VaultTab'
import { SkillsTab } from './components/SkillsTab'
import { McpTab } from './components/McpTab'
import { PluginsTab } from './components/PluginsTab'
import { DriveTab } from './components/DriveTab'
const GitHubTab = lazy(() => import('./components/GitHubTab').then(module => ({ default: module.GitHubTab })))
import CronTab from './components/CronTab'
import { NotesTab } from './notes/NotesTab'
import { SessionsPanel } from './components/SessionsPanel'
import { TasksPanel } from './components/TasksPanel'
import { ObservabilityTab } from './components/ObservabilityTab'
import { ConciliumTab } from './components/ConciliumTab'
import { ChannelsDashboard } from './components/ChannelsDashboard'
import { AgentLogDrawer } from './components/AgentLogDrawer'
import { InsightsTab } from './insights/InsightsTab'
import { CommandPalette } from './components/CommandPalette'
import { NotificationBell, NotificationCenter } from './components/NotificationCenter'
import { ConnectionStatus } from './components/ConnectionStatus'
import { MasterProgressPill } from './components/MasterProgressPill'
import SpeakingSphere from './components/SpeakingSphere'
import { useWindowsStore } from './store/windowsStore'
import { useWebSocket } from './hooks/useWebSocket'
import { PanelLeft as Bars3Icon, Search as MagnifyingGlassIcon, PanelRight as UsersIcon } from 'lucide-react'
import { NAV_SECTIONS, StudioNavigation } from './studio/StudioNavigation'

function Workspace() {
  // Establish persistent WebSocket connection for real-time events
  useWebSocket()
  const newSession = useSessionStore((s) => s.newSession)
  const tab = useAppStore((s) => s.activeTab)
  const setTab = useAppStore((s) => s.setActiveTab)
  const openWindows = useWindowsStore((s) => s.windows)
  const closeWindow = useWindowsStore((s) => s.closeWindow)
  const selectedFlowAgent = useAgentChatStore((s) => s.selectedLogAgent)
  const openFlowAgents = useAgentChatStore((s) => s.openLogAgents)
  const closeFlowAgent = useAgentChatStore((s) => s.closeLogAgent)
  const flowFocusVersion = useAgentChatStore((s) => s.focusVersion)
  const selectedFile = useFileViewerStore((s) => s.selectedFile)
  const artifactsOpen = useArtifactsStore((s) => s.open)
  const workspaceOpen = useWorkspaceStore((s) => s.open)
  const [notificationsOpen, setNotificationsOpen] = useState(false)

  const [sidebarExpanded, setSidebarExpanded] = useState(() =>
    typeof window !== 'undefined' ? window.matchMedia('(min-width: 768px)').matches : true
  )

  const [teamOpen, setTeamOpen] = useState(() => window.matchMedia('(min-width: 1200px)').matches)
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (window.matchMedia('(max-width: 700px)').matches) setSidebarExpanded(false)
      if (window.matchMedia('(max-width: 1000px)').matches) setTeamOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])
  const currentSection = NAV_SECTIONS.flatMap(section => section.items).find(item => item.id === tab)
  const navigate = (next: typeof tab) => {
    setTab(next)
    if (window.matchMedia('(max-width: 700px)').matches) setSidebarExpanded(false)
  }
  const startConversation = () => { newSession(); navigate('chat') }
  const inspectors: InspectorPanel[] = []
  for (const agent of openFlowAgents) inspectors.push({ id: `flow-${agent}`, label: `${agent} flow`, identity: agent, group: 'flow',
    close: () => closeFlowAgent(agent), content: <AgentChatFlowPanel agentName={agent} onClose={() => closeFlowAgent(agent)} /> })
  if (artifactsOpen) inspectors.push({ id: 'artifacts', label: 'Artifacts', identity: true,
    close: () => useArtifactsStore.getState().close(), content: <ArtifactsPanel /> })
  if (workspaceOpen) inspectors.push({ id: 'workspace', label: 'Workspace files', identity: true,
    close: () => useWorkspaceStore.getState().close(), content: <WorkspacePanel /> })
  if (selectedFile) inspectors.push({ id: 'file', label: 'File preview', identity: selectedFile.path,
    close: () => useFileViewerStore.getState().closeFile(), content: <FileViewerPane /> })

  // Single render tree — all tabs stay mounted; inactive tabs are hidden via display:none
  // This preserves React state (e.g. ChatPanel input) across tab switches.
  return (
    <div
      className="studio-shell flex flex-col text-zinc-100 overflow-hidden"
      style={{ height: '100dvh', minHeight: '100dvh' }}
    >

      {/* ── Floating dockable windows (rendered at root so a docked window can
          reflow the whole app body regardless of the active tab) ── */}
      {openWindows.map((w) => (
        <AgentLogDrawer
          key={w.id}
          agentName={w.agentName}
          state={w.state}
          onClose={() => closeWindow(w.id)}
        />
      ))}

      <div className="studio-body">
        <StudioNavigation expanded={sidebarExpanded} tab={tab}
          onToggle={() => setSidebarExpanded(v => !v)} onNavigate={navigate} onNew={startConversation}
          workspaceOpen={workspaceOpen}
          onWorkspace={() => { navigate('chat'); useWorkspaceStore.getState().toggle() }} />
        <div className="studio-main">
          <header className="studio-header">
            <button className="studio-icon-button studio-menu-toggle" onClick={() => setSidebarExpanded(v => !v)}
              aria-label="Toggle navigation" aria-expanded={sidebarExpanded} aria-controls="studio-navigation"><Bars3Icon /></button>
            <div className="studio-page-title"><span>Workspace <span aria-hidden="true">/</span></span><strong>{currentSection?.label ?? 'Conversation'}</strong></div>
            <div className="studio-header-progress"><SpeakingSphere /><MasterProgressPill /></div>
            <div className="studio-header-actions">
              <button className="studio-search" onClick={() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }))}
                title="Search commands (Ctrl+K)" aria-label="Open command palette"><MagnifyingGlassIcon /><span>Commands</span><kbd>{/Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl'} K</kbd></button>
              <ConnectionStatus showAge={false} />
              <NotificationBell onClick={() => setNotificationsOpen(true)} />
              <ThemeToggle />
              {tab === 'chat' && <button className="studio-icon-button studio-team-toggle" onClick={() => setTeamOpen(v => !v)}
                title={teamOpen ? 'Hide agent team' : 'Show agent team'} aria-label={teamOpen ? 'Hide agent team' : 'Show agent team'} aria-pressed={teamOpen}><UsersIcon /></button>}
            </div>
          </header>

      {/* ── Chat tab content — always mounted, hidden when inactive ── */}
      <div
        className="flex flex-1 overflow-hidden"
        style={{ display: tab === 'chat' ? 'flex' : 'none', minHeight: 0 }}
      >
        <main className="studio-conversation-layout flex-1 flex flex-row overflow-hidden relative" data-inspecting={inspectors.length > 0} style={{ minWidth: 0 }}>
          <div className="studio-conversation-content flex-1 min-w-0 h-full flex flex-col">
            <TaskProgressPanel conversation active={tab === 'chat'} />
            <ParallelUniverses />
            <div className="flex-1 min-h-0"><ChatPanel /></div>
          </div>
          <StudioInspector panels={inspectors} focusId={selectedFlowAgent ? `flow-${selectedFlowAgent}` : undefined} focusVersion={flowFocusVersion} />
        </main>
        {teamOpen && <button className="studio-team-scrim" aria-label="Close agent team" onClick={() => setTeamOpen(false)} />}
        <div className="studio-team-slot" data-open={teamOpen}><AgentSidebar onClose={() => setTeamOpen(false)} /></div>
      </div>

      {/* ── Agents tab ── */}
      <div
        className="flex flex-col flex-1 overflow-hidden"
        style={{ display: tab === 'agents' ? 'flex' : 'none', minHeight: 0 }}
      >
        <AgentDashboard />
      </div>

      <div className="flex flex-col flex-1 overflow-hidden" style={{ display: tab === 'artifacts' ? 'flex' : 'none', minHeight: 0 }}>
        {tab === 'artifacts' && <ArtifactGalleryTab />}
      </div>

      <div className="flex flex-col flex-1 overflow-hidden" style={{ display: tab === 'whiteboard' ? 'flex' : 'none', minHeight: 0 }}>
        <WhiteboardTab active={tab === 'whiteboard'} />
      </div>

      {/* ── Memory Graph tab ── */}
      <div
        className="flex flex-col flex-1 overflow-hidden"
        style={{ display: tab === 'graph' ? 'flex' : 'none', minHeight: 0 }}
      >
        <MemoryGraphTab />
      </div>

      {/* ── Vault tab ── */}
      <div
        className="flex flex-col flex-1 overflow-hidden"
        style={{ display: tab === 'vault' ? 'flex' : 'none', minHeight: 0 }}
      >
        <VaultTab />
      </div>

      {/* ── Sessions tab ── */}
      <div
        className="flex flex-col flex-1 overflow-hidden"
        style={{ display: tab === 'sessions' ? 'flex' : 'none', minHeight: 0 }}
      >
        <SessionsPanel />
      </div>

      {/* ── Tasks tab ── */}
      <div
        className="flex flex-col flex-1 overflow-hidden"
        style={{ display: tab === 'tasks' ? 'flex' : 'none', minHeight: 0 }}
      >
        <TasksPanel active={tab === 'tasks'} />
      </div>

      {/* ── Channels tab ── */}
      <div
        className="flex flex-col flex-1 overflow-hidden"
        style={{ display: tab === 'channels' ? 'flex' : 'none', minHeight: 0 }}
      >
        <ChannelsDashboard />
      </div>

      {/* ── Insights tab — cost / trace / topology / errors ── */}
      <div
        className="flex flex-col flex-1 overflow-hidden"
        style={{ display: tab === 'insights' ? 'flex' : 'none', minHeight: 0 }}
      >
        {tab === 'insights' && <InsightsTab />}
      </div>

      {/* ── Observability tab ── */}
      <div
        className="flex flex-col flex-1 overflow-hidden"
        style={{ display: tab === 'observability' ? 'flex' : 'none', minHeight: 0 }}
      >
        <ObservabilityTab active={tab === 'observability'} />
      </div>

      {/* ── Concilium tab ── */}
      <div
        className="flex flex-col flex-1 overflow-hidden"
        style={{ display: tab === 'concilium' ? 'flex' : 'none', minHeight: 0 }}
      >
        <ConciliumTab />
      </div>

      {/* ── Skills tab ── */}
      <div
        className="flex flex-col flex-1 overflow-hidden"
        style={{ display: tab === 'skills' ? 'flex' : 'none', minHeight: 0 }}
      >
        <SkillsTab />
      </div>

      {/* ── GitHub tab ── */}
      <div className="flex flex-col flex-1 overflow-hidden" style={{ display: tab === 'github' ? 'flex' : 'none', minHeight: 0 }}>
        {tab === 'github' && <Suspense fallback={<div role="status">Loading GitHub…</div>}><GitHubTab /></Suspense>}
      </div>

      {/* ── MCP tab ── */}
      <div
        className="flex flex-col flex-1 overflow-hidden"
        style={{ display: tab === 'mcp' ? 'flex' : 'none', minHeight: 0 }}
      >
        <McpTab />
      </div>

      {/* ── Plugins tab ── */}
      <div className="flex flex-col flex-1 overflow-hidden" style={{ display: tab === 'notes' ? 'flex' : 'none', minHeight: 0 }}>
        <NotesTab />
      </div>

      <div
        className="flex flex-col flex-1 overflow-hidden"
        style={{ display: tab === 'plugins' ? 'flex' : 'none', minHeight: 0 }}
      >
        <PluginsTab />
      </div>

      {/* ── Cron tab ── */}
      <div
        className="flex flex-col flex-1 overflow-hidden"
        style={{ display: tab === 'cron' ? 'flex' : 'none', minHeight: 0 }}
      >
        <CronTab />
      </div>

      {/* ── Drive tab ── */}
      <div
        className="flex flex-col flex-1 overflow-hidden"
        style={{ display: tab === 'drive' ? 'flex' : 'none', minHeight: 0 }}
      >
        <DriveTab />
      </div>

        </div>
      </div>

      {/* ── Global overlays ── */}
      <CommandPalette />
      <NotificationCenter open={notificationsOpen} onClose={() => setNotificationsOpen(false)} />

    </div>
  )
}


export default function App() {
  const authStarted = useRef(false)
  const [authenticated, setAuthenticated] = useState(false)
  const [checking, setChecking] = useState(true)
  const [token, setToken] = useState('')
  const [error, setError] = useState('')
  const check = () => {
    setError('')
    setChecking(true)
    fetch('/api/auth/status').then((r) => {
      if (!r.ok) throw new Error('Backend unavailable')
      return r.json()
    }).then((data) => {
      setAuthenticated(Boolean(data.authenticated))
      if (!data.authenticated && !data.configured) setError('Remote access requires BACKEND_API_TOKEN on the backend.')
    }).catch((e) => setError(String(e))).finally(() => setChecking(false))
  }
  useEffect(() => {
    if (authStarted.current) return
    authStarted.current = true
    // The installer hands off browser access in a fragment: it is never sent
    // in the HTTP URL or access logs. Clear it before the app makes requests.
    const setupToken = new URLSearchParams(window.location.hash.slice(1)).get('setup-token')
    if (!setupToken) { check(); return }
    window.history.replaceState(null, '', window.location.pathname + window.location.search)
    fetch('/api/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: setupToken }),
    }).then((response) => {
      if (!response.ok) throw new Error('Installer access token was not accepted')
      check()
    }).catch((e) => { setError(String(e)); setChecking(false) })
  }, [])
  if (authenticated) return <Workspace />
  return <main className="min-h-screen bg-zinc-950 text-zinc-100 flex items-center justify-center">
    <form className="space-y-4 w-80" onSubmit={async (event) => {
      event.preventDefault()
      setError('')
      try {
        const response = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }) })
        if (!response.ok) throw new Error('Access token was not accepted')
        setToken('')
        check()
      } catch (e) { setError(String(e)) }
    }}>
      <h1 className="text-xl">YAPOC backend access</h1>
      {checking ? <p>Connecting…</p> : <>
        <label className="block">Access token<input className="block w-full bg-zinc-800 p-2" type="password" autoComplete="current-password" value={token} onChange={(e) => setToken(e.target.value)} /></label>
        <button className="px-4 py-2 bg-zinc-700" type="submit">Connect</button>
        <button className="px-4 py-2" type="button" onClick={check}>Retry connection</button>
        {error && ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname) && <button className="px-4 py-2" type="button" onClick={async () => {
          try {
            const response = await fetch('/__yapoc/start', { method: 'POST' })
            if (!response.ok) throw new Error('Start the backend with yapoc start, then retry the connection.')
            setError('Backend starting. Retry the connection in a few seconds.')
          } catch (e) { setError(String(e)) }
        }}>Start local backend</button>}
      </>}
      {error && <p role="alert">{error}</p>}
    </form>
  </main>
}
