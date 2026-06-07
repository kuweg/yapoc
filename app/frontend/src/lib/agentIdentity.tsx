import type { CSSProperties } from 'react'

/**
 * Single source of truth for per-agent visual identity (color, display name,
 * avatar). Previously these lived in 5 places with conflicting colors
 * (MessageBubble, types/agentActivity, ObservabilityTab, SearchPanel) — those
 * should import from here.
 *
 * Canonical colors are the chat-facing set (most user-visible), filled out for
 * every agent in the inventory. Unknown / dynamically-created agents get a
 * STABLE hash-derived hue so they're still visually distinct (not all gray).
 */
export const AGENT_COLORS: Record<string, string> = {
  master: '#a855f7',        // purple
  planning: '#3b82f6',      // blue
  builder: '#22c55e',       // green
  keeper: '#eab308',        // yellow
  cron: '#f97316',          // orange
  doctor: '#ef4444',        // red
  model_manager: '#06b6d4', // cyan
  evaluator: '#8b5cf6',     // violet
  librarian: '#14b8a6',     // teal
  researcher: '#ec4899',    // pink
  security: '#f43f5e',      // rose
  concilium: '#6366f1',     // indigo
}

const DEFAULT_COLOR = '#9ca3af'

/** Deterministic 0-359 hue from an agent name (FNV-ish), for unknown agents. */
function hashHue(name: string): number {
  let h = 2166136261
  for (let i = 0; i < name.length; i++) {
    h ^= name.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return (h >>> 0) % 360
}

/** Canonical accent color (hex or hsl) for an agent. Stable for unknowns. */
export function getAgentColor(name: string): string {
  const key = (name || '').toLowerCase()
  if (AGENT_COLORS[key]) return AGENT_COLORS[key]
  if (!key) return DEFAULT_COLOR
  return `hsl(${hashHue(key)} 62% 60%)`
}

/** Translucent variant of an agent's color — works for both hex and hsl(...). */
export function withAlpha(color: string, alpha: number): string {
  if (color.startsWith('#') && color.length === 7) {
    return color + Math.round(alpha * 255).toString(16).padStart(2, '0')
  }
  if (color.startsWith('hsl(')) return color.replace(')', ` / ${alpha})`)
  return color
}

/** model_manager -> "model manager" (rendered uppercase by callers as desired). */
export function getAgentDisplayName(name: string): string {
  return (name || 'agent').replace(/_/g, ' ')
}

/** Avatar initials: "model_manager" -> "MM", "builder" -> "BU". */
export function getAgentInitials(name: string): string {
  const key = (name || '?').toLowerCase()
  const parts = key.split(/[_\s-]+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return key.slice(0, 2).toUpperCase()
}

/**
 * Stable per-agent avatar — a colored disc with the agent's initials. No assets,
 * deterministic from the name, and tinted with the agent's canonical color so
 * identity is consistent everywhere it appears (bubbles, cards, chips, spinners).
 */
export function AgentAvatar({ name, size = 18, title }: { name: string; size?: number; title?: string }) {
  const color = getAgentColor(name)
  const style: CSSProperties = {
    width: size,
    height: size,
    backgroundColor: withAlpha(color, 0.16),
    color,
    borderColor: color,
    fontSize: Math.max(8, Math.round(size * 0.42)),
  }
  return (
    <span
      className="inline-flex items-center justify-center rounded-full border font-bold font-mono flex-shrink-0 leading-none select-none"
      style={style}
      title={title ?? getAgentDisplayName(name)}
      aria-hidden
    >
      {getAgentInitials(name)}
    </span>
  )
}
