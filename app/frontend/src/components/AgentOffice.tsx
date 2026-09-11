import { useState, type CSSProperties } from 'react'
import type { AgentStatus } from '../api/types'
import { getAgentColor, getAgentDisplayName } from '../lib/agentIdentity'
import './agentOffice.css'
import { OfficeDelivery, OfficeFurnishing, OfficePet, officeTheme } from './OfficeAtmosphere'
import { useUniverseStore } from '../store/universeStore'

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

function RoomDetails() {
  return <svg className="office-room-details" viewBox="0 0 240 110" preserveAspectRatio="none" shapeRendering="crispEdges" aria-hidden="true">
    {/* Small furnishings stay behind the interactive residents. */}
    <path d="M14 27h46v3H14zm3 3h3v4h-3zm37 0h3v4h-3z" fill="#846747" />
    <path d="M19 15h5v12h-5z" fill="#799c82" /><path d="M25 18h4v9h-4z" fill="#ba8868" />
    <path d="M30 13h5v14h-5z" fill="#718caa" /><path d="M36 17h4v10h-4z" fill="#baa36b" />
    <path d="M47 22h8v5h-8z" fill="#a78e73" /><path d="M50 16h2v6h-2zm-4 1h4v3h-4zm6-3h4v4h-4z" fill="#779768" />
    <path d="M91 14h27v23H91z" fill="#987653" /><path d="M94 17h21v17H94z" fill="#c1b48c" />
    <path d="M96 29h3v-4h4v-4h3v4h4v4h3v3H96z" fill="#638378" /><path d="M109 19h3v3h-3z" fill="#e1ba6e" />
    <path d="M202 87h18v3h-18zm3 3h12v10h-12z" fill="#ae7b5d" /><path d="M207 91h3v7h-3z" fill="#c79b73" />
    <path d="M210 64h3v23h-3zm-8 7h8v5h-5v-2h-3zm11-7h8v5h-5v3h-3zm0 14h10v4h-7v3h-3zm-13 1h10v5h-7v-2h-3z" fill="#668761" />
    <path d="M210 66h2v20h-2zm5 13h6v1h-6z" fill="#8fac76" />
    <path d="M19 83h17v3H19zm2 3h2v13h-2zm11 0h2v13h-2z" fill="#8b6d50" />
    <path d="M23 76h7v7h-7zm7 1h3v4h-3z" fill="#b9b2a0" /><path d="M24 75h5v2h-5z" fill="#473e33" />
  </svg>
}

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
    <span className="office-person-name">{agent.universe_letter ? `Builder ${agent.universe_letter.toUpperCase()}` : getAgentDisplayName(agent.name)}</span>
    <span className="office-person-state">{labels[state]}</span>
  </button>
}

export function AgentOffice({ agents, disconnected, onOpen }: { agents: AgentStatus[]; disconnected: boolean; onOpen: (agent: AgentStatus) => void }) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [atmosphere, setAtmosphere] = useState(() => { try { return localStorage.getItem('yapoc-office-atmosphere') !== 'off' } catch { return true } })
  const states = agents.map(agent => officeState(agent, disconnected))
  const weather = !states.length || states.includes('offline') ? 'fog' : states.includes('attention') ? 'rain' : states.includes('working') || states.includes('waiting') ? 'sun' : 'night'
  const weatherLabels = { fog: 'Status unavailable', rain: 'Needs attention', sun: 'Team active', night: 'Team resting' }
  const floors = new Map<string, AgentStatus[]>()
  for (const agent of agents) {
    const role = agent.office_role || agent.name
    floors.set(role, [...(floors.get(role) || []), agent])
  }
  return <div className={`agent-office ${atmosphere ? "has-atmosphere" : "quiet-office"} weather-${weather}`} aria-label="Agent building">
    <div className="office-atmosphere-controls"><span>{weatherLabels[weather]}</span><button aria-pressed={atmosphere} onClick={() => { setAtmosphere(!atmosphere); try { localStorage.setItem("yapoc-office-atmosphere", atmosphere ? "off" : "on") } catch { /* optional preference */ } }}>Atmosphere {atmosphere ? "on" : "off"}</button></div>
    {atmosphere && <div className="office-sky" aria-hidden="true"><span className="office-celestial" /><span className="office-cloud" /><span className="office-rain" /></div>}
    <div className="office-roof"><span>YAPOC</span><span>AGENT HOUSE</span></div>
    {[...floors].sort(([a], [b]) => a === 'master' ? -1 : b === 'master' ? 1 : a.localeCompare(b)).map(([role, residents], index) => <section className={`office-floor room-${officeTheme(role)}`} key={role} data-room={officeTheme(role)} style={{ '--resident-color': getAgentColor(role) } as CSSProperties} aria-label={`${role} floor`}>
      <button className="office-floor-heading" aria-expanded={!collapsed.has(role)} onClick={() => setCollapsed(previous => {
        const next = new Set(previous); if (next.has(role)) next.delete(role); else next.add(role); return next
      })}>
        <span className="office-floor-number">{String(index + 1).padStart(2, '0')}</span>
        <span>{getAgentDisplayName(role)}</span><span className="office-floor-count">{residents.length} {residents.length === 1 ? 'resident' : 'residents'} {collapsed.has(role) ? '+' : '−'}</span>
      </button>
      {!collapsed.has(role) && <div className="office-apartment">
        <div className="office-window" aria-hidden="true" /><div className="office-lamp" aria-hidden="true" />
        <RoomDetails />
        <OfficeFurnishing role={role} />
        {atmosphere && <><OfficePet sleeping={!residents.some(agent => officeState(agent, disconnected) === 'working')} /><OfficeDelivery connected={!disconnected} signature={residents.filter(agent => officeState(agent, disconnected) === 'working').map(agent => JSON.stringify([agent.name, agent.task_summary])).sort().join('|')} /></>}
        <div className="office-residents">{[...residents].sort((a, b) => a.name.localeCompare(b.name)).map(agent => <div key={agent.name} className={`office-resident-slot portal-${agent.universe_letter || "none"}`}>{atmosphere && agent.universe_id && <span className="office-portal" aria-hidden="true" />}<Resident agent={agent} disconnected={disconnected} onOpen={onOpen} />{agent.universe_id && <button className="office-universe-badge" onClick={() => useUniverseStore.getState().compare(agent.universe_id!)} aria-label={`Compare universe ${agent.universe_letter?.toUpperCase()}`}>{agent.universe_letter?.toUpperCase()} · Compare</button>}</div>)}</div>
      </div>}
    </section>)}
    {!agents.length && <p className="office-empty">Your agents will appear here when connected.</p>}
    <div className="office-foundation">One floor. One team. Room to grow.</div>
  </div>
}
