import type { AgentState } from '../../types'

interface Props {
  state: AgentState | string
  size?: 'sm' | 'md'
  showLabel?: boolean
}

const CONFIG: Record<string, { bg: string; text: string; border: string; dot: string; label: string }> = {
  running: {
    bg: 'bg-[#1F3A5F]', text: 'text-[#FFB633]', border: 'border-[#FFB633]',
    dot: 'bg-[#FFB633]', label: 'Running',
  },
  idle: {
    bg: 'bg-[#21262D]', text: 'text-[#8B949E]', border: 'border-[#30363D]',
    dot: 'bg-[#484F58]', label: 'Idle',
  },
  error: {
    bg: 'bg-[#3D1A1A]', text: 'text-[#F85149]', border: 'border-[#DA3633]',
    dot: 'bg-[#F85149]', label: 'Error',
  },
  done: {
    bg: 'bg-[#1A3A2A]', text: 'text-[#3FB950]', border: 'border-[#2EA043]',
    dot: 'bg-[#3FB950]', label: 'Done',
  },
  spawning: {
    bg: 'bg-[#1F3A5F]', text: 'text-[#FFB633]', border: 'border-[#FFB633]',
    dot: 'bg-[#FFB633]', label: 'Spawning',
  },
}

const FALLBACK = CONFIG.idle

export function StatusBadge({ state, size = 'md', showLabel = true }: Props) {
  const cfg = CONFIG[state] ?? FALLBACK
  const isRunning = state === 'running' || state === 'spawning'
  const px = size === 'sm' ? 'px-2 py-0.5 text-[13px]' : 'px-2.5 py-1 text-[14px]'
  // Retro glow effects for active states
  const shadow = isRunning
    ? 'shadow-[0_0_8px_rgba(255,182,51,0.4)]'
    : state === 'error'
      ? 'shadow-[0_0_8px_rgba(255,51,51,0.3)]'
      : state === 'done'
        ? 'shadow-[0_0_6px_rgba(51,255,102,0.2)]'
        : ''

  return (
    <span
      role="status"
      aria-label={`${cfg.label} — agent status`}
      className={`inline-flex items-center gap-1.5 border font-mono font-semibold uppercase tracking-widest whitespace-nowrap ${px} ${cfg.bg} ${cfg.text} ${cfg.border} ${shadow}`}
    >
      <span
        className={`w-[8px] h-[8px] flex-shrink-0 ${cfg.dot} ${isRunning ? 'animate-pulse' : ''}`}
      />
      {showLabel && cfg.label}
    </span>
  )
}
