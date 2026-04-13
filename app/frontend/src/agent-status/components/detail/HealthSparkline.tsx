interface DataPoint {
  hour: string
  errorCount: number
}

interface Props {
  data: DataPoint[]
  height?: number
}

export function HealthSparkline({ data, height = 40 }: Props) {
  if (data.length === 0) {
    return <div className="h-10 flex items-center text-xs text-[#484F58]">No data</div>
  }

  const max = Math.max(...data.map((d) => d.errorCount), 1)
  const width = 240
  const barWidth = Math.max(2, (width / data.length) - 1)

  return (
    <div className="overflow-x-auto">
      <svg
        width={width}
        height={height + 12}
        aria-label={`Health sparkline: ${data.length} data points`}
        className="block"
      >
        {data.map((d, i) => {
          const barH = Math.max(2, (d.errorCount / max) * height)
          const x = i * (barWidth + 1)
          const y = height - barH
          const color = d.errorCount === 0 ? '#3FB950' : d.errorCount <= 2 ? '#D29922' : '#F85149'
          return (
            <g key={i}>
              <rect
                x={x}
                y={y}
                width={barWidth}
                height={barH}
                fill={color}
                rx={1}
              />
              <title>{`${d.hour}: ${d.errorCount} error(s)`}</title>
            </g>
          )
        })}
        {/* Hour labels: first and last */}
        {data.length > 0 && (
          <>
            <text x={0} y={height + 10} fontSize={8} fill="#484F58">{data[0].hour}</text>
            <text x={width} y={height + 10} fontSize={8} fill="#484F58" textAnchor="end">
              {data[data.length - 1].hour}
            </text>
          </>
        )}
      </svg>
    </div>
  )
}
