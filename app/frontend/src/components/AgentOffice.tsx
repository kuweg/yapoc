import { useState, type CSSProperties } from 'react'
import type { AgentStatus } from '../api/types'
import { getAgentColor, getAgentDisplayName } from '../lib/agentIdentity'
import './agentOffice.css'

export function officeState(agent: AgentStatus, disconnected = false) {
  if (disconnected) return 'offline'
  const state = agent.runtime_state ?? 'unknown'
  if (['running', 'busy'].includes(state)) return 'working'
  if (['waiting', 'blocked'].includes(state)) return 'waiting'
  if (['error', 'interrupted', 'failed'].includes(state)) return 'attention'
  if (['idle', 'done', 'completed'].includes(state)) return 'idle'
  return 'offline'
}
const labels: Record<string, string> = { working: 'Working', waiting: 'Waiting', attention: 'Needs attention', idle: 'Idle', offline: 'Status unavailable' }

function Resident({ agent, disconnected, onOpen }: { agent: AgentStatus; disconnected: boolean; onOpen: (agent: AgentStatus) => void }) {
  const state = officeState(agent, disconnected)
  return <button className={`office-resident is-${state}`} onClick={() => onOpen(agent)}
    aria-label={`${agent.name}: ${labels[state]}. Open agent flow`} title={`${agent.name} · ${labels[state]}${agent.task_summary ? `\n${agent.task_summary}` : ''}`}>
    <svg viewBox="0 0 32 30" shapeRendering="crispEdges" aria-hidden="true">
      <path d="M3 27h27v1H3z" fill="#0b1518" />
      {state === 'working' ? <g className="office-desk">
        <path d="M15 20h15v2H15zm2 2h2v5h-2zm10 0h2v5h-2z" fill="#9d805a" />
        <path d="M21 10h9v8h-9z" fill="#708d82" /><path d="M22 11h7v6h-7z" fill="#102c32" />
        <path className="office-screen" d="M23 12h3v1h-3zm0 2h5v1h-5z" fill="var(--resident-color)" />
        <path d="M25 18h2v2h-2zM6 19h8v2H6zm2 2h2v6H8z" fill="#4a645a" />
      </g> : <g>
        <path d="M4 19h17v6H4zm2-2h13v3H6z" fill="#456954" />
        <path d="M4 20h2v4H4zm15 0h2v4h-2zM6 25h2v2H6zm11 0h2v2h-2z" fill="#293f37" />
      </g>}
      <g className="office-human">
        <path d="M9 19h4v3h4v4h-2v-3h-5v3H8v-5h1z" fill="#728ca7" />
        <path d="M8 26h4v1H8zm7 0h4v1h-4z" fill="#17252b" />
        <path d="M9 12h5v2h1v6H8v-6h1z" fill="var(--resident-color)" />
        <path d="M8 14h2v5H8z" fill="#000" opacity=".15" />
        <path className="office-arm" d={state === 'attention' ? 'M14 13h3v-3h2V5h-2v4h-2v2h-1z' : state === 'working' ? 'M14 14h2v3h3v1h2v2h-5v-1h-2z' : 'M14 14h2v4h2v2h-4z'} fill="#dfb48c" />
        <g className="office-head"><path d="M9 5h5v1h2v5h-2v2h-4v-2H8V7h1z" fill="#dfb48c" /><path d="M9 4h5v1h2v3h-2V7h-4v2H8V6h1z" fill="#423a39" /><path d="M14 8h1v1h-1z" fill="#18242b" /></g>
      </g>
      {state === 'attention' && <path d="M25 5h2v5h-2zm0 6h2v2h-2z" fill="#f0bd69" />}
      {state === 'waiting' && <g><path d="M24 7h5v1h1v5h-1v1h-5v-1h-1V8h1z" fill="#91aaa3" /><path d="M26 8h1v3h2v1h-3z" fill="#263e39" /></g>}
    </svg>
    <span className="office-person-name">{getAgentDisplayName(agent.name)}</span>
    <span className="office-person-state">{labels[state]}</span>
  </button>
}

export function AgentOffice({ agents, disconnected, onOpen }: { agents: AgentStatus[]; disconnected: boolean; onOpen: (agent: AgentStatus) => void }) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const floors = new Map<string, AgentStatus[]>()
  for (const agent of agents) {
    const role = agent.office_role || agent.name
    floors.set(role, [...(floors.get(role) || []), agent])
  }
  return <div className="agent-office" aria-label="Agent building">
    <div className="office-roof"><span>YAPOC</span><span>AGENT HOUSE</span></div>
    {[...floors].sort(([a], [b]) => a === 'master' ? -1 : b === 'master' ? 1 : a.localeCompare(b)).map(([role, residents], index) => <section className="office-floor" key={role} style={{ '--resident-color': getAgentColor(role) } as CSSProperties} aria-label={`${role} floor`}>
      <button className="office-floor-heading" aria-expanded={!collapsed.has(role)} onClick={() => setCollapsed(previous => {
        const next = new Set(previous); if (next.has(role)) next.delete(role); else next.add(role); return next
      })}>
        <span className="office-floor-number">{String(index + 1).padStart(2, '0')}</span>
        <span>{getAgentDisplayName(role)}</span><span className="office-floor-count">{residents.length} {residents.length === 1 ? 'resident' : 'residents'} {collapsed.has(role) ? '+' : '−'}</span>
      </button>
      {!collapsed.has(role) && <div className="office-apartment">
        <div className="office-window" aria-hidden="true" /><div className="office-lamp" aria-hidden="true" />
        <div className="office-residents">{[...residents].sort((a, b) => a.name.localeCompare(b.name)).map(agent => <Resident key={agent.name} agent={agent} disconnected={disconnected} onOpen={onOpen} />)}</div>
      </div>}
    </section>)}
    {!agents.length && <p className="office-empty">Your agents will appear here when connected.</p>}
    <div className="office-foundation">One floor. One team. Room to grow.</div>
  </div>
}
