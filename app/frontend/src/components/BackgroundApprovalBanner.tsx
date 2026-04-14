/**
 * BackgroundApprovalBanner — shows pending tool approvals from background tasks.
 *
 * These come via WebSocket `approval_needed` events (Phase 4B).
 * The user can approve/deny via REST, and the banner updates accordingly.
 */
import { useState } from 'react'
import { useWsStore, type PendingApproval } from '../store/wsStore'

export function BackgroundApprovalBanner() {
  const approvals = useWsStore((s) => s.pendingApprovals)
  const clearApproval = useWsStore((s) => s.clearApproval)

  if (approvals.length === 0) return null

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
      {approvals.map((a) => (
        <ApprovalCard key={a.id} approval={a} onResolved={() => clearApproval(a.id)} />
      ))}
    </div>
  )
}

function ApprovalCard({ approval, onResolved }: { approval: PendingApproval; onResolved: () => void }) {
  const [loading, setLoading] = useState(false)

  let inputPreview = ''
  try {
    const parsed = JSON.parse(approval.input_json)
    inputPreview = JSON.stringify(parsed, null, 2).slice(0, 200)
  } catch {
    inputPreview = approval.input_json.slice(0, 200)
  }

  async function resolve(approved: boolean) {
    setLoading(true)
    try {
      await fetch(`/api/approvals/${approval.id}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved }),
      })
    } catch {
      // best-effort
    } finally {
      setLoading(false)
      onResolved()
    }
  }

  return (
    <div className="bg-zinc-900 border border-yellow-600/50 rounded-lg p-3 shadow-xl">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-yellow-500 text-xs font-bold uppercase">Approval Needed</span>
        <span className="text-zinc-500 text-[10px]">{approval.agent}</span>
      </div>
      <div className="text-zinc-300 text-xs mb-1 font-mono">{approval.tool}</div>
      <pre className="text-zinc-500 text-[10px] max-h-20 overflow-auto mb-2 whitespace-pre-wrap">{inputPreview}</pre>
      <div className="flex gap-2">
        <button
          onClick={() => resolve(true)}
          disabled={loading}
          className="px-3 py-1 rounded bg-green-700 text-white text-xs hover:bg-green-600 disabled:opacity-40"
        >
          Approve
        </button>
        <button
          onClick={() => resolve(false)}
          disabled={loading}
          className="px-3 py-1 rounded bg-red-700 text-white text-xs hover:bg-red-600 disabled:opacity-40"
        >
          Deny
        </button>
      </div>
    </div>
  )
}
