import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import type { Ticket } from '../../types'
import { updateTicket, deleteTicket, assignTicket } from '../../api/ticketClient'
import { useDashboardStore } from '../../store/dashboardStore'
import { useSessionStore } from '../../../store/session'
import { useAppStore } from '../../../store/appStore'
import { AssignAgentSelect } from './AssignAgentSelect'

interface Props {
  ticket: Ticket | null
  pendingAssignId: string | null
}

export function TicketDetailPanel({ ticket, pendingAssignId }: Props) {
  const { upsertTicket, removeTicket, selectTicket, setPendingAssign } = useDashboardStore()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [requirements, setRequirements] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    if (ticket) {
      setTitle(ticket.title)
      setDescription(ticket.description)
      setRequirements(ticket.requirements)
      setDirty(false)
      setConfirmDelete(false)
    }
  }, [ticket?.id])

  async function handleSave() {
    if (!ticket || !dirty) return
    setSaving(true)
    try {
      const updated = await updateTicket(ticket.id, { title, description, requirements })
      upsertTicket(updated)
      setDirty(false)
    } catch (err) {
      console.error(err)
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!ticket) return
    if (isAgent && !confirmDelete) {
      setConfirmDelete(true)
      return
    }
    setDeleting(true)
    setConfirmDelete(false)
    try {
      await deleteTicket(ticket.id)
      removeTicket(ticket.id)
    } catch (err) {
      console.error(err)
    } finally {
      setDeleting(false)
    }
  }

  async function handleAssign(agentName: string) {
    if (!ticket) return
    const updated = await assignTicket(ticket.id, agentName)
    upsertTicket(updated)
    setPendingAssign(null)

    // When assigned to master, route execution through the visible chat stream
    if (agentName === 'master') {
      const taskText = [ticket.title, ticket.description, ticket.requirements]
        .filter(Boolean)
        .join('\n\n')
      // Track which ticket master is working on so ChatPanel can mark it done
      useDashboardStore.getState().setActiveMasterTicketId(updated.id)
      useSessionStore.getState().setPendingChatInput(taskText)
      useAppStore.getState().setActiveTab('chat')
      selectTicket(null)
    }
  }

  const isAgent = ticket?.type === 'agent'
  const isPendingAssign = ticket?.id === pendingAssignId

  return (
    <AnimatePresence>
      {ticket && (
        <motion.div
          key={ticket.id}
          initial={{ x: 480, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 480, opacity: 0 }}
          transition={{ type: 'spring', stiffness: 380, damping: 38 }}
          className="absolute right-0 top-0 bottom-0 w-[480px] bg-[#161B22] border-l border-[#30363D] flex flex-col shadow-2xl z-30 overflow-hidden"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-[#30363D] bg-[#1C2128] flex-shrink-0">
            <div className="flex items-center gap-2">
              <span
                className="w-2 h-2 rounded-full"
                style={{ background: isAgent ? '#FFB633' : '#9E68FF' }}
              />
              <span className="text-[#8B949E] text-xs">
                {isAgent ? 'Agent Task' : 'User Ticket'}
              </span>
            </div>
            <button
              onClick={() => selectTicket(null)}
              className="text-[#484F58] hover:text-[#E6EDF3] text-lg leading-none transition-colors"
            >
              ×
            </button>
          </div>

          {/* Scrollable body */}
          <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4">
            {/* Title */}
            <div>
              <label className="text-[#8B949E] text-xs font-medium block mb-1">Title</label>
              {isAgent ? (
                <p className="text-[#E6EDF3] text-sm font-medium">{ticket.title}</p>
              ) : (
                <input
                  type="text"
                  value={title}
                  onChange={(e) => { setTitle(e.target.value); setDirty(true) }}
                  className="w-full bg-[#0D1117] text-[#E6EDF3] text-sm rounded px-3 py-2 border border-[#30363D] focus:outline-none focus:border-[#FFB633]"
                />
              )}
            </div>

            {/* Description */}
            <div>
              <label className="text-[#8B949E] text-xs font-medium block mb-1">Description</label>
              {isAgent ? (
                <pre className="text-[#8B949E] text-xs whitespace-pre-wrap break-words bg-[#0D1117] rounded p-3 border border-[#21262D]">
                  {ticket.task_text || ticket.description || '—'}
                </pre>
              ) : (
                <textarea
                  value={description}
                  onChange={(e) => { setDescription(e.target.value); setDirty(true) }}
                  rows={4}
                  className="w-full bg-[#0D1117] text-[#E6EDF3] text-xs rounded px-3 py-2 border border-[#30363D] focus:outline-none focus:border-[#FFB633] resize-y"
                />
              )}
            </div>

            {/* Requirements (UDT only) */}
            {!isAgent && (
              <div>
                <label className="text-[#8B949E] text-xs font-medium block mb-1">Requirements</label>
                <textarea
                  value={requirements}
                  onChange={(e) => { setRequirements(e.target.value); setDirty(true) }}
                  rows={3}
                  placeholder="Acceptance criteria, technical notes…"
                  className="w-full bg-[#0D1117] text-[#E6EDF3] text-xs rounded px-3 py-2 border border-[#30363D] focus:outline-none focus:border-[#FFB633] resize-y placeholder-[#484F58]"
                />
              </div>
            )}

            {/* Agent assignment */}
            {!isAgent && (
              <div className={isPendingAssign ? 'ring-1 ring-[#D29922] rounded-md p-3 bg-[#D2992210]' : ''}>
                {isPendingAssign && (
                  <p className="text-[#D29922] text-[11px] mb-2">
                    Moved to In Progress — assign an agent to process this ticket.
                  </p>
                )}
                <AssignAgentSelect
                  currentAgent={ticket.assigned_agent}
                  onAssign={handleAssign}
                />
              </div>
            )}

            {/* Agent result (for agent tasks or assigned UDTs) */}
            {(isAgent || ticket.result_text) && ticket.result_text && (
              <div>
                <label className="text-[#3FB950] text-xs font-medium block mb-1">Result</label>
                <pre className="text-[#8B949E] text-xs whitespace-pre-wrap break-words bg-[#0D1117] rounded p-3 border border-[#21262D] max-h-48 overflow-y-auto">
                  {ticket.result_text}
                </pre>
              </div>
            )}

            {/* Agent error */}
            {(isAgent || ticket.error_text) && ticket.error_text && (
              <div>
                <label className="text-[#F85149] text-xs font-medium block mb-1">Error</label>
                <pre className="text-[#F85149] text-xs whitespace-pre-wrap break-words bg-[#0D1117] rounded p-3 border border-[#21262D] max-h-32 overflow-y-auto">
                  {ticket.error_text}
                </pre>
              </div>
            )}

            {/* Activity trace */}
            {ticket.trace.length > 0 && (
              <div>
                <label className="text-[#8B949E] text-xs font-medium block mb-2">Activity</label>
                <div className="flex flex-col gap-1.5 max-h-40 overflow-y-auto">
                  {[...ticket.trace].reverse().map((entry, i) => (
                    <div key={i} className="flex gap-2 items-start text-[11px]">
                      <span className="text-[#484F58] flex-shrink-0 tabular-nums">
                        {entry.ts.slice(11, 16)}
                      </span>
                      {entry.agent && (
                        <span className="text-[#FFB633] flex-shrink-0">{entry.agent}</span>
                      )}
                      <span className="text-[#8B949E] break-words">{entry.note}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Metadata */}
            <div className="border-t border-[#21262D] pt-3 grid grid-cols-2 gap-x-4 gap-y-1.5">
              {([
                ['Status', ticket.status.replace('_', ' ')],
                ['Type', ticket.type],
                ...(ticket.parent_agent ? [['Spawned by', ticket.parent_agent]] : []),
                ['Created', ticket.created_at.slice(0, 10)],
                ['Updated', ticket.updated_at.slice(0, 10)],
              ] as string[][]).map(([k, v]) => (
                <div key={k}>
                  <span className="text-[#484F58] text-[10px]">{k}</span>
                  <p className="text-[#8B949E] text-xs capitalize">{v}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Footer actions */}
          <div className="flex-shrink-0 border-t border-[#30363D] bg-[#1C2128]">
            {/* Agent ticket warning confirmation */}
            {confirmDelete && isAgent && (
              <div className="px-4 py-3 border-b border-[#D2992240] bg-[#D2992215]">
                <p className="text-[#D29922] text-xs font-medium mb-1">⚠ Delete auto-generated agent task?</p>
                <p className="text-[#8B949E] text-[11px] mb-3 leading-relaxed">
                  This ticket was created automatically from an agent's work. Deleting it removes it from the board but the agent may still be running.
                  References to this task's result may be broken or produce unpredictable behavior.
                </p>
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleDelete}
                    disabled={deleting}
                    className="px-3 py-1.5 rounded bg-[#DA3633] text-white text-xs font-medium hover:bg-[#F85149] disabled:opacity-40 transition-colors"
                  >
                    {deleting ? 'Deleting…' : 'Delete anyway'}
                  </button>
                  <button
                    onClick={() => setConfirmDelete(false)}
                    className="px-3 py-1.5 rounded bg-[#21262D] text-[#8B949E] text-xs hover:text-[#E6EDF3] transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            <div className="flex items-center gap-2 px-4 py-3">
              {!isAgent && dirty && (
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="px-3 py-1.5 rounded bg-[#1F6FEB] text-white text-xs font-medium hover:bg-[#388BFD] disabled:opacity-40 transition-colors"
                >
                  {saving ? 'Saving…' : 'Save'}
                </button>
              )}
              {!confirmDelete && (
                <button
                  onClick={handleDelete}
                  disabled={deleting}
                  className="px-3 py-1.5 rounded bg-[#21262D] text-[#F85149] text-xs hover:bg-[#30363D] disabled:opacity-40 transition-colors ml-auto"
                >
                  {deleting ? 'Deleting…' : 'Delete'}
                </button>
              )}
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
