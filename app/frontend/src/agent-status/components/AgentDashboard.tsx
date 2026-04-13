import { useAgentPolling } from '../hooks/useAgentPolling'
import { useEventStream } from '../hooks/useEventStream'
import { DashboardHeader } from './DashboardHeader'
import { DashboardLayout } from './DashboardLayout'
import { DashboardFooter } from './DashboardFooter'

export function AgentDashboard() {
  useAgentPolling()
  useEventStream()

  return (
    <div className="flex flex-col h-screen bg-[#0D1117] text-[#E6EDF3] overflow-hidden">
      <DashboardHeader />
      <DashboardLayout />
      <DashboardFooter />
    </div>
  )
}
