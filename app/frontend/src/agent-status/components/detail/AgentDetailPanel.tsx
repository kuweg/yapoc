import { AnimatePresence, motion } from 'framer-motion'
import { XMarkIcon } from '@heroicons/react/24/solid'
import { useAgentStore } from '../../store/agentStore'
import { StatusBadge } from '../shared/StatusBadge'
import { HealthIndicator } from '../shared/HealthIndicator'
import { AgentMetaGrid } from './AgentMetaGrid'
import { TaskDetail } from './TaskDetail'
import { HealthLogList } from './HealthLogList'
import { HealthSparkline } from './HealthSparkline'
import { MemoryPreview } from './MemoryPreview'
import { AgentActions } from './AgentActions'

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-[10px] uppercase tracking-widest text-[#484F58] mb-2">{title}</h3>
      {children}
    </div>
  )
}

export function AgentDetailPanel() {
  const { selectedAgentName, selectedAgentDetail, isDetailLoading, selectAgent } = useAgentStore()

  // Build sparkline data from health log
  const sparklineData = (() => {
    if (!selectedAgentDetail?.health_log) return []
    const buckets: Record<string, number> = {}
    for (const entry of selectedAgentDetail.health_log) {
      const h = entry.timestamp.slice(0, 13) // "2026-04-10T14"
      const isError = entry.level.toUpperCase() === 'ERROR'
      buckets[h] = (buckets[h] ?? 0) + (isError ? 1 : 0)
    }
    return Object.entries(buckets)
      .sort(([a], [b]) => a.localeCompare(b))
      .slice(-24)
      .map(([hour, errorCount]) => ({ hour: hour.slice(11) + 'h', errorCount }))
  })()

  return (
    <AnimatePresence>
      {selectedAgentName && (
        <motion.div
          key="detail-panel"
          initial={{ x: 480, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 480, opacity: 0 }}
          transition={{ type: 'spring', damping: 30, stiffness: 300 }}
          role="dialog"
          aria-modal="true"
          aria-label={`Agent details: ${selectedAgentName}`}
          className="fixed right-0 top-0 bottom-0 w-[480px] max-w-full bg-[#161B22] border-l border-[#30363D]
            shadow-2xl overflow-y-auto z-20 flex flex-col
            max-md:w-full max-md:inset-0"
        >
          {/* Header */}
          <div className="sticky top-0 bg-[#1C2128] border-b border-[#30363D] px-4 py-3 flex items-center gap-3">
            <button
              onClick={() => selectAgent(null)}
              aria-label="Close detail panel"
              className="p-1 rounded text-[#8B949E] hover:text-[#E6EDF3] hover:bg-[#30363D] transition-colors"
            >
              <XMarkIcon className="w-4 h-4" />
            </button>
            <span className="font-mono text-sm font-semibold text-[#E6EDF3] truncate flex-1">
              {selectedAgentName}
            </span>
            {selectedAgentDetail && (
              <div className="flex items-center gap-2">
                <StatusBadge state={selectedAgentDetail.state} size="sm" />
                <HealthIndicator health={selectedAgentDetail.health} size="sm" />
              </div>
            )}
          </div>

          {/* Body */}
          <div className="flex-1 px-4 py-4 space-y-5">
            {isDetailLoading && !selectedAgentDetail && (
              <div className="flex items-center justify-center h-32 text-sm text-[#484F58]">
                Loading…
              </div>
            )}

            {selectedAgentDetail && (
              <>
                <Section title="Overview">
                  <AgentMetaGrid detail={selectedAgentDetail} />
                </Section>

                <Section title="Actions">
                  <AgentActions agentName={selectedAgentName} state={selectedAgentDetail.state} />
                </Section>

                <Section title="Current Task">
                  <TaskDetail task={selectedAgentDetail.task} />
                </Section>

                <Section title="Health Log">
                  <HealthLogList entries={selectedAgentDetail.health_log} />
                </Section>

                {sparklineData.length > 0 && (
                  <Section title="Error History (24h)">
                    <HealthSparkline data={sparklineData} />
                  </Section>
                )}

                <Section title="Recent Memory">
                  <MemoryPreview entries={selectedAgentDetail.memory_log} />
                </Section>
              </>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
