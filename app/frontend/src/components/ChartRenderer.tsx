import { useRef, useEffect } from 'react'
import * as echarts from 'echarts'
import { useThemeStore } from '../store/themeStore'

/**
 * Renders an interactive ECharts chart from a normalized option object.
 *
 * The backend render_chart tool injects a colourblind-safe palette and sets
 * `animation: false` for instant first paint. Here we layer theme-aware
 * colours (text, grid, tooltip) resolved from CSS custom properties so the
 * chart matches the active dark / light / claude theme.
 *
 * An empty / invalid payload renders a small fallback note instead of a chart.
 */

function styleAxis(axis: unknown, gridColor: string): unknown {
  if (Array.isArray(axis)) return axis.map((a) => styleAxis(a, gridColor))
  if (axis && typeof axis === 'object') {
    const a = axis as Record<string, unknown>
    const splitLine = (a.splitLine as Record<string, unknown>) ?? {}
    const axisLine = (a.axisLine as Record<string, unknown>) ?? {}
    return {
      ...a,
      splitLine: { ...splitLine, lineStyle: { color: gridColor, ...((splitLine.lineStyle as object) ?? {}) } },
      axisLine: { ...axisLine, lineStyle: { color: gridColor, ...((axisLine.lineStyle as object) ?? {}) } },
    }
  }
  return axis
}

export default function ChartBlock({ option }: { option: Record<string, unknown> }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const theme = useThemeStore((s) => s.theme)

  // Only treat the payload as chartable if it holds a non-empty series array.
  const valid = Array.isArray(option?.series) && option.series.length > 0

  useEffect(() => {
    const el = containerRef.current
    if (!valid || !el) return

    // Resolve theme tokens from CSS custom properties (see index.css per theme).
    const css = getComputedStyle(el)
    const text = css.getPropertyValue('--color-chart-text').trim() || '#6e6862'
    const grid = css.getPropertyValue('--color-chart-grid').trim() || '#262626'
    const tooltipBg = css.getPropertyValue('--color-tooltip-bg').trim() || '#1f1f1f'
    const tooltipBorder = css.getPropertyValue('--color-tooltip-border').trim() || '#303030'
    const tooltipText = css.getPropertyValue('--color-tooltip-text').trim() || '#e8e6e3'
    const fontMono = css.getPropertyValue('--font-mono').trim() || 'monospace'

    const themed: Record<string, unknown> = {
      ...option,
      textStyle: { color: text, fontFamily: fontMono },
      legend: { ...(option.legend as object), textStyle: { color: text, fontFamily: fontMono } },
      tooltip: {
        backgroundColor: tooltipBg,
        borderColor: tooltipBorder,
        textStyle: { color: tooltipText, fontFamily: fontMono },
        ...(option.tooltip as object),
      },
      xAxis: styleAxis(option.xAxis, grid),
      yAxis: styleAxis(option.yAxis, grid),
    }

    const chart = echarts.init(el)
    chart.setOption(themed)

    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.dispose()
    }
    // option is immutable config; theme changes rebuild with new tokens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [valid, theme])

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
