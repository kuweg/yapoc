import { CheckCircleIcon, ExclamationTriangleIcon, XCircleIcon } from '@heroicons/react/24/solid'
import type { HealthStatus } from '../../types'

interface Props {
  health: HealthStatus
  errorCount?: number
  size?: 'sm' | 'md'
}

const CONFIG = {
  ok:       { color: 'text-[#3FB950]', Icon: CheckCircleIcon,         label: 'OK' },
  warning:  { color: 'text-[#D29922]', Icon: ExclamationTriangleIcon, label: 'Warning' },
  critical: { color: 'text-[#F85149]', Icon: XCircleIcon,             label: 'Critical' },
}

export function HealthIndicator({ health, errorCount, size = 'md' }: Props) {
  const { color, Icon, label } = CONFIG[health] ?? CONFIG.ok
  const iconSize = size === 'sm' ? 'w-4 h-4' : 'w-5 h-5'

  return (
    <span
      className={`inline-flex items-center gap-1 ${color}`}
      title={errorCount != null ? `${errorCount} error(s) in recent log` : undefined}
      aria-label={`Health ${label}${errorCount ? ` — ${errorCount} recent errors` : ''}`}
    >
      <Icon className={iconSize} />
      <span className="text-sm font-medium">{label}</span>
    </span>
  )
}
