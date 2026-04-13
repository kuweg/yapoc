import { useSessionStore } from './store/session'
import { useAppStore } from './store/appStore'
import { AgentSidebar } from './components/AgentSidebar'
import { ChatPanel } from './components/ChatPanel'
import { AgentDashboard } from './agent-status'
import { DashboardView } from './dashboard'
import { ThemeToggle } from './components/ThemeToggle'
import { MemoryGraphTab } from './memory-graph/components/MemoryGraphTab'
import { VaultTab } from './vault/components/VaultTab'

export default function App() {
  const { sessions, activeId, newSession, loadSession } = useSessionStore()
  const tab = useAppStore((s) => s.activeTab)
  const setTab = useAppStore((s) => s.setActiveTab)

  function NavButton({ id, label }: { id: ReturnType<typeof useAppStore.getState>['activeTab']; label: string }) {
    const active = tab === id
    return (
      <button
        onClick={() => setTab(id)}
        className={[
          'px-3 py-1 text-xs font-mono tracking-wider uppercase transition-colors border',
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
        <div className="flex items-center gap-1 bg-zinc-800 border border-zinc-700 p-0.5">
          <NavButton id="chat" label="Chat" />
          <NavButton id="agents" label="Agents" />
          <NavButton id="dashboard" label="Dashboard" />
          <NavButton id="graph" label="Memory" />
          <NavButton id="vault" label="Vault" />
        </div>
        <div className="flex-1" />
        <ThemeToggle />
      </header>
    )
  }

  // Single render tree — all tabs stay mounted; inactive tabs are hidden via display:none
  // This preserves React state (e.g. ChatPanel input) across tab switches.
  return (
    <div className="flex flex-col h-screen bg-zinc-950 text-zinc-100 overflow-hidden">

      {/* ── Chat tab header (only visible when chat is active) ── */}
      {tab === 'chat' ? (
        <header className="flex items-center gap-3 px-4 py-2 bg-zinc-900 border-b border-zinc-700 flex-shrink-0">
          <span className="font-mono font-bold text-[#FFB633] tracking-widest text-sm uppercase">&gt; YAPOC</span>

          {/* Nav tabs */}
          <div className="flex items-center gap-1 bg-zinc-800 border border-zinc-700 p-0.5">
            <NavButton id="chat" label="Chat" />
            <NavButton id="agents" label="Agents" />
            <NavButton id="dashboard" label="Dashboard" />
            <NavButton id="graph" label="Memory" />
            <NavButton id="vault" label="Vault" />
          </div>

          <div className="flex items-center gap-2 flex-1">
            {sessions.length > 0 && (
              <select
                value={activeId ?? ''}
                onChange={(e) => loadSession(e.target.value)}
                className="bg-zinc-800 text-zinc-200 text-xs px-2 py-1 border border-zinc-700 focus:outline-none max-w-[240px] truncate font-mono"
              >
                {sessions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            )}

            <button
              onClick={newSession}
              className="px-3 py-1 bg-zinc-700 text-zinc-200 text-xs hover:bg-zinc-600 border border-zinc-600 font-mono tracking-wider"
            >
              + NEW
            </button>
          </div>

          {/* Theme toggle — right side of header */}
          <ThemeToggle />
        </header>
      ) : (
        /* Shared header for all other tabs */
        <AppHeader />
      )}

      {/* ── Chat tab content — always mounted, hidden when inactive ── */}
      <div
        className="flex flex-1 overflow-hidden"
        style={{ display: tab === 'chat' ? 'flex' : 'none' }}
      >
        <AgentSidebar />
        <main className="flex-1 overflow-hidden">
          <ChatPanel />
        </main>
      </div>

      {/* ── Agents tab ── */}
      <div
        className="flex flex-col flex-1 overflow-hidden"
        style={{ display: tab === 'agents' ? 'flex' : 'none' }}
      >
        <AgentDashboard />
      </div>

      {/* ── Dashboard tab ── */}
      <div
        className="flex flex-col flex-1 overflow-hidden"
        style={{ display: tab === 'dashboard' ? 'flex' : 'none' }}
      >
        <DashboardView />
      </div>

      {/* ── Memory Graph tab ── */}
      <div
        className="flex flex-col flex-1 overflow-hidden"
        style={{ display: tab === 'graph' ? 'flex' : 'none' }}
      >
        <MemoryGraphTab />
      </div>

      {/* ── Vault tab ── */}
      <div
        className="flex flex-col flex-1 overflow-hidden"
        style={{ display: tab === 'vault' ? 'flex' : 'none' }}
      >
        <VaultTab />
      </div>

    </div>
  )
}
