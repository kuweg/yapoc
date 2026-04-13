interface Props {
  entries: string[]
}

export function MemoryPreview({ entries }: Props) {
  if (entries.length === 0) {
    return (
      <div className="py-4 text-center text-sm text-[#484F58]">
        No memory entries
      </div>
    )
  }

  return (
    <div className="space-y-1.5 max-h-40 overflow-y-auto">
      {entries.slice(0, 5).map((entry, i) => (
        <div
          key={i}
          className="text-xs text-[#8B949E] font-mono bg-[#0D1117] border border-[#21262D] rounded px-2 py-1.5
            whitespace-pre-wrap break-words leading-relaxed"
        >
          {entry}
        </div>
      ))}
    </div>
  )
}
