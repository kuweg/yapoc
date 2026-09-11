import { lazy, Suspense } from 'react'

const ChartRenderer = lazy(() => import('./ChartRenderer'))

export default function ChartBlock({ option }: { option: Record<string, unknown> }) {
  return <Suspense fallback={<div role="status">Loading chart…</div>}>
    <ChartRenderer option={option} />
  </Suspense>
}
