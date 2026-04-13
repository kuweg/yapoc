import type { GraphPoint } from '../types'

interface Props {
  point: GraphPoint
  svgX: number
  svgY: number
  svgW: number
  svgH: number
}

const TIP_W = 200
const TIP_H = 72

export function PointTooltip({ point, svgX, svgY, svgW, svgH }: Props) {
  const preview = point.content.length > 100
    ? point.content.slice(0, 100) + '…'
    : point.content

  // Clamp so tooltip stays inside SVG bounds
  const tx = Math.min(svgX + 12, svgW - TIP_W - 4)
  const ty = Math.max(Math.min(svgY - TIP_H - 4, svgH - TIP_H - 4), 4)

  return (
    <g style={{ pointerEvents: 'none' }}>
      <rect
        x={tx} y={ty} width={TIP_W} height={TIP_H}
        rx={4} fill="#1C2128" stroke="#30363D" strokeWidth={1}
      />
      {/* agent · source */}
      <text x={tx + 8} y={ty + 14} fontSize={9} fill="#FFB633" fontFamily="monospace">
        {point.agent} · {point.source}
      </text>
      {/* timestamp */}
      <text x={tx + 8} y={ty + 26} fontSize={8} fill="#484F58" fontFamily="monospace">
        {point.timestamp}
      </text>
      {/* content preview — two lines of ~30 chars */}
      <text x={tx + 8} y={ty + 40} fontSize={8} fill="#E6EDF3" fontFamily="monospace">
        {preview.slice(0, 30)}
      </text>
      <text x={tx + 8} y={ty + 52} fontSize={8} fill="#E6EDF3" fontFamily="monospace">
        {preview.slice(30, 60)}
      </text>
      <text x={tx + 8} y={ty + 64} fontSize={8} fill="#E6EDF3" fontFamily="monospace">
        {preview.slice(60)}
      </text>
    </g>
  )
}
