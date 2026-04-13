import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { createTicket } from '../../api/ticketClient'
import { useDashboardStore } from '../../store/dashboardStore'

export function CreateTicketModal() {
  const { isCreateOpen, setCreateOpen, upsertTicket } = useDashboardStore()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [requirements, setRequirements] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleCreate() {
    if (!title.trim()) return
    setLoading(true)
    setError(null)
    try {
      const ticket = await createTicket({ title: title.trim(), description, requirements })
      upsertTicket(ticket)
      setTitle('')
      setDescription('')
      setRequirements('')
      setCreateOpen(false)
    } catch (err: any) {
      setError(err.message ?? 'Failed to create ticket')
    } finally {
      setLoading(false)
    }
  }

  function handleClose() {
    setCreateOpen(false)
    setTitle('')
    setDescription('')
    setRequirements('')
    setError(null)
  }

  return (
    <AnimatePresence>
      {isCreateOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 z-40"
            onClick={handleClose}
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: -20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -20 }}
            transition={{ type: 'spring', stiffness: 400, damping: 32 }}
            className="fixed inset-0 flex items-center justify-center z-50 pointer-events-none"
          >
            <div
              className="bg-[#161B22] border border-[#30363D] rounded-lg shadow-2xl w-[520px] pointer-events-auto"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Header */}
              <div className="flex items-center justify-between px-5 py-4 border-b border-[#30363D]">
                <span className="text-[#E6EDF3] text-sm font-semibold">New Ticket</span>
                <button
                  onClick={handleClose}
                  className="text-[#484F58] hover:text-[#E6EDF3] text-xl leading-none transition-colors"
                >
                  ×
                </button>
              </div>

              {/* Body */}
              <div className="px-5 py-4 flex flex-col gap-4">
                <div>
                  <label className="text-[#8B949E] text-xs font-medium block mb-1">
                    Title <span className="text-[#F85149]">*</span>
                  </label>
                  <input
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) handleCreate() }}
                    autoFocus
                    placeholder="What needs to be done?"
                    className="w-full bg-[#0D1117] text-[#E6EDF3] text-sm rounded px-3 py-2 border border-[#30363D] focus:outline-none focus:border-[#FFB633] placeholder-[#484F58]"
                  />
                </div>

                <div>
                  <label className="text-[#8B949E] text-xs font-medium block mb-1">Description</label>
                  <textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    rows={3}
                    placeholder="Background, context, links…"
                    className="w-full bg-[#0D1117] text-[#E6EDF3] text-xs rounded px-3 py-2 border border-[#30363D] focus:outline-none focus:border-[#FFB633] resize-y placeholder-[#484F58]"
                  />
                </div>

                <div>
                  <label className="text-[#8B949E] text-xs font-medium block mb-1">Requirements</label>
                  <textarea
                    value={requirements}
                    onChange={(e) => setRequirements(e.target.value)}
                    rows={2}
                    placeholder="Acceptance criteria, constraints…"
                    className="w-full bg-[#0D1117] text-[#E6EDF3] text-xs rounded px-3 py-2 border border-[#30363D] focus:outline-none focus:border-[#FFB633] resize-y placeholder-[#484F58]"
                  />
                </div>

                {error && <p className="text-[#F85149] text-xs">{error}</p>}
              </div>

              {/* Footer */}
              <div className="flex justify-end gap-2 px-5 py-3 border-t border-[#30363D]">
                <button
                  onClick={handleClose}
                  className="px-4 py-1.5 rounded bg-[#21262D] text-[#8B949E] text-xs hover:text-[#E6EDF3] transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleCreate}
                  disabled={!title.trim() || loading}
                  className="px-4 py-1.5 rounded bg-[#238636] text-white text-xs font-medium hover:bg-[#2EA043] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {loading ? 'Creating…' : 'Create Ticket'}
                </button>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
