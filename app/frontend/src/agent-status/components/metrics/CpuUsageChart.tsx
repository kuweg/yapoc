import { useEffect, useRef, useState } from 'react'
import { getAgentCpuMetrics, type AgentCpuMetrics } from '../../api/agentStatusClient'
import { useThemeStore } from '../../../store/themeStore'

// ── Constants ────────────────────────────────────────────────────────────────

const POLL_INTERVAL_MS = 5_000
const CHART_HEIGHT = 120
const BAR_GAP = 4
const LABEL_AREA_HEIGHT = 32
const Y_AXIS_WIDTH = 36
const MIN_BAR_WIDTH = 8
const MAX_BAR_WIDTH = 48

// ── Colour helpers ───────────────────────────────────────────────────────────

function cpuColour(pct: number): string {
  if (pct >= 80) return '#F85149'   // red — high load
  if (pct >= 50) return '#D29922'   // yellow — moderate
  if (pct >= 10) return '#FFB633'   // blue — light
  return '#3FB950'                  // green — idle
}

// ── Sub-components ───────────────────────────────────────────────────────────

interface BarProps {
  x: number
  barWidth: number
  item: AgentCpuMetrics
  chartHeight: number
  tooltipBg: string
  tooltipBorder: string
  tooltipText: string
  labelColor: string
}

function CpuBar({ x, barWidth, item, chartHeight, tooltipBg, tooltipBorder, tooltipText, labelColor }: BarProps) {
  const [hovered, setHovered] = useState(false)
  const pct = item.cpu_percent
  const barH = Math.max(2, (pct / 100) * chartHeight)
  const y = chartHeight - barH
  const colour = cpuColour(pct)
  const label = item.agent_name.length > 8
    ? item.agent_name.slice(0, 7) + '…'
    : item.agent_name

  return (
    <g
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{ cursor: 'default' }}
    >
      {/* Bar */}
      <rect
        x={x}
        y={y}
        width={barWidth}
        height={barH}
        fill={colour}
        rx={2}
        opacity={hovered ? 1 : 0.85}
      />

      {/* Tooltip on hover */}
      {hovered && (
        <g>
          <rect
            x={x - 4}
            y={Math.max(0, y - 36)}
            width={barWidth + 8}
            height={32}
            fill={tooltipBg}
            stroke={tooltipBorder}
            strokeWidth={1}
            rx={4}
          />
          <text
            x={x + barWidth / 2}
            y={Math.max(0, y - 36) + 12}
            textAnchor="middle"
            fontSize={9}
            fill={tooltipText}
            fontFamily="monospace"
          >
            {item.agent_name}
          </text>
          <text
            x={x + barWidth / 2}
            y={Math.max(0, y - 36) + 24}
            textAnchor="middle"
            fontSize={9}
            fill={colour}
            fontFamily="monospace"
          >
            {pct.toFixed(1)}% · {item.memory_mb.toFixed(0)} MB
          </text>
        </g>
      )}

      {/* X-axis label */}
      <text
        x={x + barWidth / 2}
        y={chartHeight + 14}
        textAnchor="middle"
        fontSize={8}
        fill={labelColor}
        fontFamily="monospace"
      >
        {label}
      </text>

      {/* CPU % above bar (only if bar is tall enough) */}
      {barH > 16 && (
        <text
          x={x + barWidth / 2}
          y={y + 10}
          textAnchor="middle"
          fontSize={8}
          fill={tooltipText}
          fontFamily="monospace"
        >
          {pct.toFixed(0)}%
        </text>
      )}

      <title>{`${item.agent_name}: ${pct.toFixed(2)}% CPU, ${item.memory_mb.toFixed(1)} MB RAM${item.pid ? ` (PID ${item.pid})` : ''}`}</title>
    </g>
  )
}

// ── Main component ───────────────────────────────────────────────────────────

export function CpuUsageChart() {
  const [data, setData] = useState<AgentCpuMetrics[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState(600)
  const theme = useThemeStore((s) => s.theme)

  // Theme-aware colors
  const isDark = theme === 'dark'
  const gridColor = isDark ? '#21262D' : '#E8EAED'
  const axisLabelColor = isDark ? '#484F58' : '#8C959F'
  const tooltipBg = isDark ? '#1C2128' : '#FFFFFF'
  const tooltipBorder = isDark ? '#30363D' : '#D0D7DE'
  const tooltipText = isDark ? '#E6EDF3' : '#1F2328'

  // Observe container width for responsive sizing
  useEffect(() => {
    if (!containerRef.current) return
    const obs = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width
      if (w) setContainerWidth(w)
    })
    obs.observe(containerRef.current)
    return () => obs.disconnect()
  }, [])

  const fetchData = async () => {
    try {
      const result = await getAgentCpuMetrics()
      setData(result)
      setError(null)
      setLastUpdated(new Date().toLocaleTimeString())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch CPU metrics')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    const id = setInterval(fetchData, POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [])

  // ── Derived layout ─────────────────────────────────────────────────────────

  const svgWidth = containerWidth - Y_AXIS_WIDTH
  const totalHeight = CHART_HEIGHT + LABEL_AREA_HEIGHT

  const barWidth = data.length === 0
    ? MAX_BAR_WIDTH
    : Math.min(
        MAX_BAR_WIDTH,
        Math.max(MIN_BAR_WIDTH, Math.floor((svgWidth - BAR_GAP) / data.length) - BAR_GAP),
      )

  const totalBarsWidth = data.length * (barWidth + BAR_GAP) - BAR_GAP
  const startX = Math.max(0, (svgWidth - totalBarsWidth) / 2)

  // Y-axis grid lines at 0, 25, 50, 75, 100 %
  const gridLines = [0, 25, 50, 75, 100]

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="bg-[#161B22] border border-[#30363D] rounded-lg p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <h3 className="text-[10px] uppercase tracking-widest text-[#484F58]">
            CPU Usage per Agent
          </h3>
          {loading && !data.length && (
            <span className="text-[10px] text-[#484F58] animate-pulse">Loading…</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {/* Legend */}
          <div className="flex items-center gap-2 text-[9px] text-[#484F58]">
            {[
              { colour: '#3FB950', label: '<10%' },
              { colour: '#FFB633', label: '10–50%' },
              { colour: '#D29922', label: '50–80%' },
              { colour: '#F85149', label: '≥80%' },
            ].map(({ colour, label }) => (
              <span key={label} className="flex items-center gap-1">
                <span
                  className="inline-block w-2 h-2 rounded-sm"
                  style={{ backgroundColor: colour }}
                />
                {label}
              </span>
            ))}
          </div>
          {lastUpdated && (
            <span className="text-[9px] text-[#484F58]">
              Updated {lastUpdated}
            </span>
          )}
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="flex items-center gap-2 text-xs text-[#F85149] bg-[#1C2128] rounded px-3 py-2 mb-3">
          <span>⚠</span>
          <span>{error}</span>
          <button
            onClick={fetchData}
            className="ml-auto text-[#FFB633] hover:underline text-xs"
          >
            Retry
          </button>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && data.length === 0 && (
        <div className="flex items-center justify-center h-24 text-xs text-[#484F58]">
          No agents found
        </div>
      )}

      {/* Chart */}
      {data.length > 0 && (
        <div ref={containerRef} className="w-full overflow-x-auto">
          <svg
            width="100%"
            height={totalHeight + 8}
            viewBox={`0 0 ${containerWidth} ${totalHeight + 8}`}
            aria-label="CPU usage bar chart per agent"
            className="block"
          >
            {/* Y-axis grid lines + labels */}
            {gridLines.map((pct) => {
              const y = CHART_HEIGHT - (pct / 100) * CHART_HEIGHT
              return (
                <g key={pct}>
                  <line
                    x1={Y_AXIS_WIDTH}
                    y1={y}
                    x2={containerWidth}
                    y2={y}
                    stroke={gridColor}
                    strokeWidth={1}
                    strokeDasharray={pct === 0 ? undefined : '3 3'}
                  />
                  <text
                    x={Y_AXIS_WIDTH - 4}
                    y={y + 4}
                    textAnchor="end"
                    fontSize={8}
                    fill={axisLabelColor}
                    fontFamily="monospace"
                  >
                    {pct}%
                  </text>
                </g>
              )
            })}

            {/* Bars */}
            <g transform={`translate(${Y_AXIS_WIDTH + startX}, 0)`}>
              {data.map((item, i) => (
                <CpuBar
                  key={item.agent_name}
                  x={i * (barWidth + BAR_GAP)}
                  barWidth={barWidth}
                  item={item}
                  chartHeight={CHART_HEIGHT}
                  tooltipBg={tooltipBg}
                  tooltipBorder={tooltipBorder}
                  tooltipText={tooltipText}
                  labelColor={axisLabelColor}
                />
              ))}
            </g>
          </svg>
        </div>
      )}
    </div>
  )
}
