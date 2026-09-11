import {
  NotebookPen,
  MessageSquare as ChatBubbleLeftRightIcon, Users as UsersIcon, ListTodo as ClipboardDocumentListIcon, ChartNoAxesCombined as ChartBarIcon,
  Activity as EyeIcon, GitBranch as ScaleIcon, BrainCircuit as CircleStackIcon, Archive as ArchiveBoxIcon, WandSparkles as PuzzlePieceIcon,
  History as ClockIcon, Radio as SignalIcon, Plus as PlusIcon, PanelsTopLeft as Squares2X2Icon, FolderOpen as FolderOpenIcon,
  Unplug as ServerIcon, Blocks as CubeIcon, PanelLeftClose as ChevronDoubleLeftIcon, PanelLeftOpen as ChevronDoubleRightIcon,
  HardDrive as HardDriveIcon, GitPullRequest,
} from 'lucide-react'
import type { useAppStore } from '../store/appStore'

type Tab = ReturnType<typeof useAppStore.getState>['activeTab']
export const NAV_SECTIONS: { title: string; items: { id: Tab; label: string; icon: typeof UsersIcon }[] }[] = [
  { title: 'Workspace', items: [
    { id: 'chat', label: 'Conversation', icon: ChatBubbleLeftRightIcon },
    { id: 'agents', label: 'Agents', icon: UsersIcon },
    { id: 'tasks', label: 'Tasks', icon: ClipboardDocumentListIcon },
    { id: 'notes', label: 'Notes', icon: NotebookPen },
    { id: 'cron', label: 'Cron', icon: ClockIcon },
  ] },
  { title: 'Intelligence', items: [
    { id: 'insights', label: 'Insights', icon: ChartBarIcon },
    { id: 'observability', label: 'Observability', icon: EyeIcon },
    { id: 'concilium', label: 'Concilium', icon: ScaleIcon },
    { id: 'graph', label: 'Memory', icon: CircleStackIcon },
    { id: 'vault', label: 'Vault', icon: ArchiveBoxIcon },
    { id: 'skills', label: 'Skills', icon: PuzzlePieceIcon },
  ] },
  { title: 'Connections', items: [
    { id: 'github', label: 'GitHub', icon: GitPullRequest },
    { id: 'mcp', label: 'MCP servers', icon: ServerIcon },
    { id: 'plugins', label: 'Plugins', icon: CubeIcon },
    { id: 'drive', label: 'Google Drive', icon: HardDriveIcon },
  ] },
  { title: 'Communication', items: [
    { id: 'sessions', label: 'Conversations', icon: ClockIcon },
    { id: 'channels', label: 'Channels', icon: SignalIcon },
  ] },
]

/** A coordinator and its connected agents, shared by the brand and welcome view. */
export function YapocMark({ className = '' }: { className?: string }) {
  return <svg className={className} viewBox="0 0 48 48" fill="none" aria-hidden="true">
    <path d="M24 14V6M31 18l8-6M33 26l9 3M28 33l5 9M19 33l-5 9M15 26l-9 3M17 18l-8-6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    <circle cx="24" cy="24" r="10" stroke="currentColor" strokeWidth="1.6" />
    <circle cx="24" cy="24" r="4" fill="currentColor" />
    {[[24, 5], [40, 11], [43, 30], [34, 43], [13, 43], [5, 30], [8, 11]].map(([cx, cy]) =>
      <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r="2" fill="currentColor" />,
    )}
  </svg>
}

interface Props {
  expanded: boolean
  tab: Tab
  onToggle: () => void
  onNavigate: (tab: Tab) => void
  onNew: () => void
  onArtifacts: () => void
  onWorkspace: () => void
  artifactsOpen: boolean
  workspaceOpen: boolean
}

export function StudioNavigation(p: Props) {
  return <>
    {p.expanded && <button className="studio-nav-scrim" aria-label="Close navigation" onClick={p.onToggle} />}
    <aside id="studio-navigation" className="studio-nav" data-expanded={p.expanded}>
      <a href="#" className="studio-brand" aria-label="YAPOC conversation" onClick={e => { e.preventDefault(); p.onNavigate('chat') }}>
        <YapocMark />
        <span className="studio-nav-copy"><strong>yapoc<span>●</span></strong><small>Local agent workspace</small></span>
      </a>
      <button className="studio-new" onClick={p.onNew} title="New conversation" aria-label="New conversation">
        <PlusIcon /><span className="studio-nav-copy">New conversation</span>
      </button>
      <nav aria-label="Main navigation" className="studio-nav-links">
        {NAV_SECTIONS.map(section => <div className="studio-nav-section" key={section.title}>
          <p className="studio-nav-copy">{section.title}</p>
          {section.items.map(({ id, label, icon: Icon }) => <button key={id}
            onClick={() => p.onNavigate(id)} title={label} aria-label={label}
            aria-current={p.tab === id ? 'page' : undefined} className="studio-nav-link">
            <Icon /><span className="studio-nav-copy">{label}</span>
            {p.tab === id && <span className="studio-nav-active studio-nav-copy" />}
          </button>)}
          {section.title === 'Workspace' && <div className="studio-workspace-links">
        <button className="studio-nav-link" onClick={p.onArtifacts} aria-pressed={p.artifactsOpen} title="Artifacts" aria-label="Artifacts">
          <Squares2X2Icon /><span className="studio-nav-copy">Artifacts</span>
        </button>
        <button className="studio-nav-link" onClick={p.onWorkspace} aria-pressed={p.workspaceOpen} title="Workspace files" aria-label="Workspace files">
          <FolderOpenIcon /><span className="studio-nav-copy">Workspace files</span>
        </button>
          </div>}
        </div>)}
      </nav>
      <button className="studio-nav-collapse studio-nav-link" onClick={p.onToggle}
        title={p.expanded ? 'Collapse navigation' : 'Expand navigation'} aria-expanded={p.expanded} aria-controls="studio-navigation">
        {p.expanded ? <ChevronDoubleLeftIcon /> : <ChevronDoubleRightIcon />}
        <span className="studio-nav-copy">Collapse navigation</span>
      </button>
    </aside>
  </>
}
