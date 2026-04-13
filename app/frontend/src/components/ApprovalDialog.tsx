import { useState } from 'react'
import { approveToolCall } from '../api/client'

interface ApprovalDialogProps {
  requestId: string
  toolName: string
  input: Record<string, unknown>
  onClose: () => void
}

export function ApprovalDialog({ requestId, toolName, input, onClose }: ApprovalDialogProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function respond(approved: boolean) {
    setBusy(true)
    try {
      await approveToolCall(requestId, approved)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-xl border border-zinc-600 bg-zinc-900 shadow-2xl mx-4">
        {/* Header */}
        <div className="flex items-center gap-2 px-5 py-4 border-b border-zinc-700">
          <span className="text-amber-400 text-lg">⚠</span>
          <div>
            <p className="text-sm font-semibold text-zinc-100">Tool approval required</p>
            <p className="text-xs text-zinc-400 mt-0.5">
              The agent wants to run a privileged tool
            </p>
          </div>
        </div>

        {/* Tool details */}
        <div className="px-5 py-4 space-y-3">
          <div>
            <span className="text-xs text-zinc-500 uppercase tracking-wider">Tool</span>
            <p className="text-sm font-mono text-amber-400 mt-0.5">{toolName}</p>
          </div>
          <div>
            <span className="text-xs text-zinc-500 uppercase tracking-wider">Input</span>
            <pre className="mt-1 rounded bg-zinc-800 p-3 text-xs font-mono text-zinc-300 overflow-x-auto max-h-48 whitespace-pre-wrap break-words">
              {JSON.stringify(input, null, 2)}
            </pre>
          </div>
          {error && (
            <p className="text-xs text-red-400">{error}</p>
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-3 px-5 py-4 border-t border-zinc-700">
          <button
            onClick={() => respond(false)}
            disabled={busy}
            className="flex-1 rounded-lg border border-zinc-600 px-4 py-2 text-sm text-zinc-300 hover:bg-zinc-800 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Deny
          </button>
          <button
            onClick={() => respond(true)}
            disabled={busy}
            className="flex-1 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {busy ? 'Sending…' : 'Approve'}
          </button>
        </div>
      </div>
    </div>
  )
}
