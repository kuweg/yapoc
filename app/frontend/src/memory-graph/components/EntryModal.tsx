import type { GraphPoint } from '../types'

interface Props {
  entry: GraphPoint
  onClose: () => void
}

export function EntryModal({ entry, onClose }: Props) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
    >
      <div
        className="bg-zinc-900 border border-zinc-700 rounded-lg p-5 max-w-lg w-full mx-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2 text-xs">
            <span className="text-blue-400 font-medium">{entry.agent}</span>
            <span className="text-zinc-500">·</span>
            <span className="text-zinc-400">{entry.source}</span>
            <span className="text-zinc-500">·</span>
            <span className="text-zinc-500">{entry.timestamp}</span>
          </div>
          <button
            onClick={onClose}
            className="text-zinc-500 hover:text-zinc-200 text-xs px-2 py-0.5 rounded hover:bg-zinc-800"
          >
            ✕
          </button>
        </div>

        {/* Content */}
        <pre className="text-xs text-zinc-300 whitespace-pre-wrap break-words max-h-96 overflow-y-auto font-mono leading-relaxed">
          {entry.content}
        </pre>

        {/* Footer */}
        <div className="mt-3 text-[10px] text-zinc-600">
          entry #{entry.id} · cluster {entry.cluster}
        </div>
      </div>
    </div>
  )
}
