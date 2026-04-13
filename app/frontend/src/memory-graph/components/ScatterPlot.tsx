import { useEffect, useRef, useState } from 'react'
import type { ClusterInfo, GraphPoint } from '../types'
import { PointTooltip } from './PointTooltip'

interface Props {
  points: GraphPoint[]
  clusters: ClusterInfo[]
  onSelect: (p: GraphPoint) => void
}

const PADDING = 28

function clusterColor(clusters: ClusterInfo[], id: number): string {
  return clusters.find((c) => c.id === id)?.color ?? '#FFB633'
}

export function ScatterPlot({ points, clusters, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(600)
  const [h, setH] = useState(600)
  const [hovered, setHovered] = useState<GraphPoint | null>(null)

  useEffect(() => {
    if (!containerRef.current) return
    const obs = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect
      if (rect) {
        setW(Math.max(rect.width, 100))
        setH(Math.max(rect.height, 100))
      }
    })
    obs.observe(containerRef.current)
    return () => obs.disconnect()
  }, [])

  // Map [-1, 1] → SVG pixel coordinate on each axis independently
  const toX = (v: number) => PADDING + ((v + 1) / 2) * (w - PADDING * 2)
  const toY = (v: number) => PADDING + ((v + 1) / 2) * (h - PADDING * 2)

  return (
    <div ref={containerRef} className="w-full h-full">
      <svg
        width={w}
        height={h}
        style={{ display: 'block' }}
        aria-label="Memory semantic scatter plot"
      >
        {/* Axis lines */}
        <line x1={PADDING} y1={toY(0)} x2={w - PADDING} y2={toY(0)} stroke="#21262D" strokeWidth={1} />
        <line x1={toX(0)} y1={PADDING} x2={toX(0)} y2={h - PADDING} stroke="#21262D" strokeWidth={1} />

        {/* Points */}
        {points.map((p) => {
          const cx = toX(p.x)
          const cy = toY(p.y)
          const color = clusterColor(clusters, p.cluster)
          const isHovered = hovered?.id === p.id

          return (
            <circle
              key={p.id}
              cx={cx}
              cy={cy}
              r={isHovered ? 8 : 5}
              fill={color}
              opacity={isHovered ? 1 : 0.75}
              style={{ cursor: 'pointer' }}
              onMouseEnter={() => setHovered(p)}
              onMouseLeave={() => setHovered(null)}
              onClick={() => onSelect(p)}
            />
          )
        })}

        {/* Tooltip */}
        {hovered && (
          <PointTooltip
            point={hovered}
            svgX={toX(hovered.x)}
            svgY={toY(hovered.y)}
            svgW={w}
            svgH={h}
          />
        )}
      </svg>
    </div>
  )
}
