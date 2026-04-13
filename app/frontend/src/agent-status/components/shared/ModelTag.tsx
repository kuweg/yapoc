interface Props {
  model: string
  adapter: string
  truncate?: boolean
}

const ADAPTER_COLORS: Record<string, string> = {
  anthropic: 'text-[#FFB633]',
  openai:    'text-[#3FB950]',
  ollama:    'text-[#D29922]',
  openrouter:'text-[#a78bfa]',
}

export function ModelTag({ model, adapter, truncate = true }: Props) {
  const color = ADAPTER_COLORS[adapter.toLowerCase()] ?? 'text-[#8B949E]'
  const display = truncate && model.length > 22 ? model.slice(0, 20) + '…' : model

  return (
    <span
      className="inline-flex items-center gap-1 font-mono text-sm"
      title={`${adapter}: ${model}`}
    >
      <span className={`font-semibold ${color}`}>{adapter}</span>
      <span className="text-[#484F58]">/</span>
      <span className="text-[#8B949E]">{display}</span>
    </span>
  )
}
