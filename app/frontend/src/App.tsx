import { useState } from 'react'
import { useSessionStore } from './store/session'
import { useAppStore } from './store/appStore'
import { useAgentChatStore } from './store/agentChatStore'
import { AgentSidebar } from './components/AgentSidebar'
import { ChatPanel } from './components/ChatPanel'
import { AgentFlowPane } from './components/AgentFlowPane'
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
import { useWindowsStore } from './store/windowsStore'
import { useWebSocket } from './hooks/useWebSocket'

export default function App() {
  // Establish persistent WebSocket connection for real-time events
  useWebSocket()
  const newSession = useSessionStore((s) => s.newSession)
  const tab = useAppStore((s) => s.activeTab)
  const setTab = useAppStore((s) => s.setActiveTab)
  const openWindows = useWindowsStore((s) => s.windows)
  const closeWindow = useWindowsStore((s) => s.closeWindow)
  const selectedFlowAgent = useAgentChatStore((s) => s.selectedLogAgent)
  const setSelectedFlowAgent = useAgentChatStore((s) => s.setSelectedLogAgent)
  const [notificationsOpen, setNotificationsOpen] = useState(false)

  function NavButton({ id, label }: { id: ReturnType<typeof useAppStore.getState>['activeTab']; label: string }) {
    const active = tab === id
    return (
      <button
        onClick={() => setTab(id)}
        className={[
          'px-3 py-1.5 text-xs font-mono tracking-wider uppercase transition-colors border flex-shrink-0 whitespace-nowrap',
          active
            ? 'bg-zinc-700 text-[#FFB633] border-[#FFB633]'
            : 'text-zinc-400 border-transparent hover:text-[#FFB633] hover:border-[#2a2a1a]',
        ].join(' ')}
      >
        {label}
      </button>
    )
  }

  // Shared header component
  function AppHeader() {
    return (
      <header className="flex items-center gap-3 px-4 py-2 bg-zinc-900 border-b border-zinc-700 flex-shrink-0">
        <span className="font-mono font-bold text-[#FFB633] tracking-widest text-sm uppercase">&gt; YAPOC</span>
        <div className="flex items-center gap-1 bg-zinc-800 border border-zinc-700 p-0.5 overflow-x-auto max-w-full nav-scroll" role="tablist" aria-label="Main sections">
          <NavButton id="chat" label="Chat" />
          <NavButton id="agents" label="Agents" />
          <NavButton id="tasks" label="Tasks" />
          <NavButton id="insights" label="Insights" />
          <NavButton id="observability" label="Obs" />
          <NavButton id="concilium" label="Concilium" />
          <NavButton id="graph" label="Memory" />
          <NavButton id="vault" label="Vault" />
          <NavButton id="sessions" label="Sessions" />
          <NavButton id="channels" label="Channels" />
          <NavButton id="skills" label="Skills" />
        </div>
        <div className="flex-1" />
        <MasterProgressPill />
        {/* The palette existed but nothing advertised it — an invisible
            shortcut is not a feature. */}
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

      {/* ── Chat tab header (only visible when chat is active) ── */}
      {tab === 'chat' ? (
        <header className="flex items-center gap-3 px-4 py-2 bg-zinc-900 border-b border-zinc-700 flex-shrink-0">
          <span className="font-mono font-bold text-[#FFB633] tracking-widest text-sm uppercase">&gt; YAPOC</span>

          {/* Nav tabs */}
          <div className="flex items-center gap-1 bg-zinc-800 border border-zinc-700 p-0.5 overflow-x-auto max-w-full nav-scroll" role="tablist" aria-label="Main sections">
            <NavButton id="chat" label="Chat" />
            <NavButton id="agents" label="Agents" />
            <NavButton id="tasks" label="Tasks" />
            <NavButton id="insights" label="Insights" />
            <NavButton id="observability" label="Obs" />
            <NavButton id="concilium" label="Concilium" />
            <NavButton id="graph" label="Memory" />
            <NavButton id="vault" label="Vault" />
            <NavButton id="sessions" label="Sessions" />
            <NavButton id="channels" label="Channels" />
            <NavButton id="skills" label="Skills" />
          </div>

          <div className="flex items-center gap-2 flex-1 min-w-0">
            <button
              onClick={newSession}
              className="px-3 py-1.5 bg-zinc-700 text-zinc-200 text-xs hover:bg-zinc-600 border border-zinc-600 font-mono tracking-wider flex-shrink-0 whitespace-nowrap"
            >
              + NEW
            </button>
          </div>

          {/* Theme toggle — right side of header */}
        {/* The palette existed but nothing advertised it — an invisible
              shortcut is not a feature. */}
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
      ) : (
        /* Shared header for all other tabs */
        <AppHeader />
      )}

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

      {/* ── Live topology HUD — pinned below every tab ── */}
      <LiveTopologyHUD />

      {/* ── Global overlays ── */}
      <CommandPalette />
      <NotificationCenter open={notificationsOpen} onClose={() => setNotificationsOpen(false)} />

    </div>
  )
}
