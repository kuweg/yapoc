import { useRef, useEffect } from 'react'
import * as echarts from 'echarts'

/**
 * Renders an interactive ECharts chart from a normalized option object.
 *
 * The option typically carries `animation: false` from the backend render_chart
 * tool, so the chart appears instantly on setOption — we deliberately do NOT
 * override it. The container has no forced background so it stays transparent
 * and dark-mode friendly (ECharts default theme is used).
 *
 * An empty / invalid payload renders a small fallback note instead of a chart.
 */
export default function ChartBlock({ option }: { option: Record<string, unknown> }) {
  const containerRef = useRef<HTMLDivElement>(null)

  // Only treat the payload as chartable if it holds a non-empty series array.
  const valid = Array.isArray(option?.series) && option.series.length > 0

  useEffect(() => {
    const el = containerRef.current
    if (!valid || !el) return

    const chart = echarts.init(el)
    chart.setOption(option)

    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.dispose()
    }
    // option is treated as immutable config for the lifetime of the chart.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [valid])

  if (!valid) {
    return (
      <div className="w-full">
        <p className="text-xs text-zinc-500 italic">_No chart data to display._</p>
      </div>
    )
  }

  return (
    <div className="w-full my-1">
      <div
        ref={containerRef}
        className="w-full h-72"
        style={{ background: 'transparent' }}
      />
    </div>
  )
}
