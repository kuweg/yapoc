import { useEffect, useRef, useState } from 'react'
import { useSessionStore } from './store/session'
import { useAppStore } from './store/appStore'
import { useAgentChatStore } from './store/agentChatStore'
import { AgentSidebar } from './components/AgentSidebar'
import { ChatPanel } from './components/ChatPanel'
import { AgentFlowPane } from './components/AgentFlowPane'
import { FileViewerPane } from './components/FileViewerPane'
import { useFileViewerStore } from './store/fileViewerStore'
import { useArtifactsStore } from './store/artifactsStore'
import { useWorkspaceStore } from './store/workspaceStore'
import { ArtifactsPanel } from './artifacts/ArtifactsPanel'
import { WorkspacePanel } from './components/WorkspacePanel'
import { AgentDashboard } from './agent-status'
import { ThemeToggle } from './components/ThemeToggle'
import { MemoryGraphTab } from './memory-graph/components/MemoryGraphTab'
import { VaultTab } from './vault/components/VaultTab'
import { SkillsTab } from './components/SkillsTab'
import { SessionsPanel } from './components/SessionsPanel'
import { TasksPanel } from './components/TasksPanel'
import { ObservabilityTab } from './components/ObservabilityTab'
import { ConciliumTab } from './components/ConciliumTab'
import { ChannelsDashboard } from './components/ChannelsDashboard'
import { AgentLogDrawer } from './components/AgentLogDrawer'
import { InsightsTab } from './insights/InsightsTab'
import { LiveTopologyHUD } from './topology/LiveTopologyHUD'
import { CommandPalette } from './components/CommandPalette'
import { NotificationBell, NotificationCenter } from './components/NotificationCenter'
import { ConnectionStatus } from './components/ConnectionStatus'
import { MasterProgressPill } from './components/MasterProgressPill'
import SpeakingSphere from './components/SpeakingSphere'
import { useWindowsStore } from './store/windowsStore'
import { useWebSocket } from './hooks/useWebSocket'
import {
  ChatBubbleLeftRightIcon,
  UsersIcon,
  ClipboardDocumentListIcon,
  ChartBarIcon,
  EyeIcon,
  ScaleIcon,
  CircleStackIcon,
  ArchiveBoxIcon,
  PuzzlePieceIcon,
  Bars3Icon,
  SignalIcon,
  PlusIcon,
  Squares2X2Icon,
  FolderOpenIcon,
} from '@heroicons/react/24/outline'

function Workspace() {
  // Establish persistent WebSocket connection for real-time events
  useWebSocket()
  const newSession = useSessionStore((s) => s.newSession)
  const tab = useAppStore((s) => s.activeTab)
  const setTab = useAppStore((s) => s.setActiveTab)
  const openWindows = useWindowsStore((s) => s.windows)
  const closeWindow = useWindowsStore((s) => s.closeWindow)
  const selectedFlowAgent = useAgentChatStore((s) => s.selectedLogAgent)
  const setSelectedFlowAgent = useAgentChatStore((s) => s.setSelectedLogAgent)
  const selectedFile = useFileViewerStore((s) => s.selectedFile)
  const artifactsOpen = useArtifactsStore((s) => s.open)
  const workspaceOpen = useWorkspaceStore((s) => s.open)
  const [notificationsOpen, setNotificationsOpen] = useState(false)

  const [sidebarExpanded, setSidebarExpanded] = useState(() =>
    typeof window !== 'undefined' ? window.matchMedia('(min-width: 768px)').matches : true
  )

  type NavItem = { id: ReturnType<typeof useAppStore.getState>['activeTab']; label: string; icon: typeof ChatBubbleLeftRightIcon }
  const NAV_SECTIONS: { title: string; items: NavItem[] }[] = [
    {
      title: 'Primary',
      items: [
        { id: 'chat', label: 'Chat', icon: ChatBubbleLeftRightIcon },
        { id: 'agents', label: 'Agents', icon: UsersIcon },
        { id: 'tasks', label: 'Tasks', icon: ClipboardDocumentListIcon },
      ],
    },
    {
      title: 'Insights',
      items: [
        { id: 'insights', label: 'Insights', icon: ChartBarIcon },
        { id: 'observability', label: 'Observability', icon: EyeIcon },
        { id: 'concilium', label: 'Concilium', icon: ScaleIcon },
      ],
    },
    {
      title: 'Knowledge',
      items: [
        { id: 'graph', label: 'Memory', icon: CircleStackIcon },
        { id: 'vault', label: 'Vault', icon: ArchiveBoxIcon },
        { id: 'skills', label: 'Skills', icon: PuzzlePieceIcon },
      ],
    },
    {
      title: 'Comms',
      items: [
        { id: 'sessions', label: 'Sessions', icon: Bars3Icon },
        { id: 'channels', label: 'Channels', icon: SignalIcon },
      ],
    },
  ]

  function AppSidebar() {
    return (
      <aside
        className={[
          'flex flex-col bg-zinc-900 border-r border-zinc-700 flex-shrink-0 overflow-y-auto transition-all',
          sidebarExpanded ? 'w-56' : 'w-14',
        ].join(' ')}
      >
        {/* Chat actions */}
        <div className="p-2 flex flex-col gap-1">
          <button
            onClick={newSession}
            title="New session"
            className={[
              'flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs font-mono tracking-wider text-zinc-200 bg-zinc-700 hover:bg-zinc-600 border border-zinc-600 transition-colors',
              sidebarExpanded ? 'justify-start' : 'justify-center',
            ].join(' ')}
          >
            <PlusIcon className="w-4 h-4 flex-shrink-0" />
            {sidebarExpanded && <span>NEW</span>}
          </button>
          <button
            onClick={() => useArtifactsStore.getState().toggle()}
            title="Artifacts"
            className={[
              'flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs font-mono tracking-wider text-zinc-400 border border-zinc-700 hover:text-[#FFB633] hover:border-[#FFB633] transition-colors',
              sidebarExpanded ? 'justify-start' : 'justify-center',
            ].join(' ')}
          >
            <Squares2X2Icon className="w-4 h-4 flex-shrink-0" />
            {sidebarExpanded && <span>ARTIFACTS</span>}
          </button>
          <button
            onClick={() => useWorkspaceStore.getState().toggle()}
            title="Workspace"
            className={[
              'flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs font-mono tracking-wider text-zinc-400 border border-zinc-700 hover:text-[#FFB633] hover:border-[#FFB633] transition-colors',
              sidebarExpanded ? 'justify-start' : 'justify-center',
            ].join(' ')}
          >
            <FolderOpenIcon className="w-4 h-4 flex-shrink-0" />
            {sidebarExpanded && <span>WORKSPACE</span>}
          </button>
        </div>

        {/* Nav sections */}
        {NAV_SECTIONS.map((section) => (
          <div key={section.title} className="px-2 pb-2">
            {sidebarExpanded && (
              <div className="px-2 pt-2 pb-1 text-[10px] font-mono uppercase tracking-widest text-zinc-500">
                {section.title}
              </div>
            )}
            <div className="flex flex-col gap-0.5">
              {section.items.map((item) => {
                const Icon = item.icon
                const active = tab === item.id
                return (
                  <button
                    key={item.id}
                    onClick={() => setTab(item.id)}
                    title={item.label}
                    className={[
                      'flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs font-mono tracking-wider transition-colors border-l-2',
                      sidebarExpanded ? 'justify-start' : 'justify-center',
                      active
                        ? 'bg-zinc-800 text-[#FFB633] border-l-[#FFB633]'
                        : 'text-zinc-400 border-l-transparent hover:text-[#FFB633] hover:bg-zinc-800/50',
                    ].join(' ')}
                  >
                    <Icon className="w-4 h-4 flex-shrink-0" />
                    {sidebarExpanded && <span>{item.label}</span>}
                  </button>
                )
              })}
            </div>
          </div>
        ))}

        {/* Collapse toggle */}
        <div className="mt-auto p-2 border-t border-zinc-700">
          <button
            onClick={() => setSidebarExpanded((v) => !v)}
            title={sidebarExpanded ? 'Collapse sidebar' : 'Expand sidebar'}
            aria-label={sidebarExpanded ? 'Collapse sidebar' : 'Expand sidebar'}
            className={[
              'flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs font-mono text-zinc-400 hover:text-[#FFB633] transition-colors w-full',
              sidebarExpanded ? 'justify-start' : 'justify-center',
            ].join(' ')}
          >
            <Bars3Icon className="w-4 h-4 flex-shrink-0" />
            {sidebarExpanded && <span>Collapse</span>}
          </button>
        </div>
      </aside>
    )
  }

  // Single render tree — all tabs stay mounted; inactive tabs are hidden via display:none
  // This preserves React state (e.g. ChatPanel input) across tab switches.
  return (
    <div
      className="flex flex-col bg-zinc-950 text-zinc-100 overflow-hidden"
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

      {/* ── Unified header (top bar) ── */}
      <header className="flex items-center gap-3 px-4 py-2 bg-zinc-900 border-b border-zinc-700 flex-shrink-0">
        <SpeakingSphere />
        <span className="font-mono font-bold text-[#FFB633] tracking-widest text-sm uppercase">&gt; YAPOC</span>
        <div className="flex-1" />
        <MasterProgressPill />
        <button
          onClick={() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }))}
          title="Command palette (Ctrl+K)"
          aria-label="Open command palette"
          className="px-2 py-1.5 text-xs font-mono text-zinc-400 border border-zinc-700 hover:text-[#FFB633] hover:border-[#FFB633] transition-colors flex-shrink-0 whitespace-nowrap"
        >
          ⌘K
        </button>
        <ConnectionStatus showAge={false} />
        <NotificationBell onClick={() => setNotificationsOpen(true)} />
        <ThemeToggle />
      </header>

      {/* ── App shell: sidebar rail + main content ── */}
      <div className="flex flex-1 overflow-hidden" style={{ minHeight: 0 }}>
        <AppSidebar />
        <div className="flex-1 flex flex-col overflow-hidden" style={{ minWidth: 0 }}>


      {/* ── Chat tab content — always mounted, hidden when inactive ── */}
      <div
        className="flex flex-1 overflow-hidden"
        style={{ display: tab === 'chat' ? 'flex' : 'none', minHeight: 0 }}
      >
        <AgentSidebar />
        {/* Chat + agent-flow tile in one row: ChatPanel (flex-1) shrinks to make
            room for the flow pane, and the draggable seam between them sets the
            ratio. */}
        <main className="flex-1 flex flex-row overflow-hidden relative" style={{ minWidth: 0 }}>
          <div className="flex-1 min-w-0 h-full">
            <ChatPanel />
          </div>
          {selectedFlowAgent && (
            <AgentFlowPane
              agentName={selectedFlowAgent}
              onClose={() => setSelectedFlowAgent(null)}
            />
          )}
          {artifactsOpen && <ArtifactsPanel />}
          {workspaceOpen && <WorkspacePanel />}
          {selectedFile && <FileViewerPane />}
        </main>
      </div>

      {/* ── Agents tab ── */}
      <div
        className="flex flex-col flex-1 overflow-hidden"
        style={{ display: tab === 'agents' ? 'flex' : 'none', minHeight: 0 }}
      >
        <AgentDashboard />
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
        <TasksPanel />
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
        <ObservabilityTab />
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

        </div>
      </div>

      {/* ── Live topology HUD — pinned below every tab ── */}
      <LiveTopologyHUD />

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
