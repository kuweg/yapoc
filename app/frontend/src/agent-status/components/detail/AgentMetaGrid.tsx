import type { AgentDetail } from '../../types'
import { ModelTag } from '../shared/ModelTag'
import { TimestampCell } from '../shared/TimestampCell'

interface Props {
  detail: AgentDetail
}

function MetaItem({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[12px] uppercase tracking-widest text-[#484F58] mb-0.5">{label}</dt>
      <dd className="text-sm text-[#E6EDF3]">{children}</dd>
    </div>
  )
}

function formatUptime(seconds: number | null): string {
  if (seconds == null) return '—'
  if (seconds < 60) return `${Math.floor(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
  return `${Math.floor(seconds / 86400)}d`
}

export function AgentMetaGrid({ detail }: Props) {
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-3 px-4 py-3 bg-[#0D1117] rounded-lg border border-[#21262D]">
      <MetaItem label="PID">{detail.pid ?? '—'}</MetaItem>
      <MetaItem label="Process">{detail.process_state || '—'}</MetaItem>
      <MetaItem label="Model">
        <ModelTag model={detail.model} adapter={detail.adapter} truncate={false} />
      </MetaItem>
      <MetaItem label="Uptime">{formatUptime(detail.uptime_seconds)}</MetaItem>
      <MetaItem label="Memory entries">{detail.memory_entries}</MetaItem>
      <MetaItem label="Health errors">{detail.health_errors}</MetaItem>
      <MetaItem label="Started">
        <TimestampCell timestamp={detail.started_at} />
      </MetaItem>
      <MetaItem label="Last active">
        <TimestampCell timestamp={detail.updated_at} />
      </MetaItem>
    </dl>
  )
}
