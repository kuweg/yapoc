import type { StatusFilterType, SortBy } from '../../types'
import { useAgentStore } from '../../store/agentStore'
import { useStatusCounts } from '../../store/selectors'

const FILTERS: { key: StatusFilterType; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'running', label: 'Running' },
  { key: 'idle', label: 'Idle' },
  { key: 'error', label: 'Error' },
]

const SORT_OPTIONS: { value: SortBy; label: string }[] = [
  { value: 'status', label: 'Status' },
  { value: 'name', label: 'Name' },
  { value: 'activity', label: 'Activity' },
  { value: 'health', label: 'Health' },
]

const FILTER_COLORS: Record<StatusFilterType, string> = {
  all: 'text-[#8B949E]',
  running: 'text-[#FFB633]',
  idle: 'text-[#8B949E]',
  error: 'text-[#F85149]',
}

export function FilterBar() {
  const { activeFilter, searchQuery, sortBy, setActiveFilter, setSearchQuery, setSortBy } = useAgentStore()
  const counts = useStatusCounts()

  return (
    <div className="sticky top-0 z-10 bg-[#161B22] border-b border-[#30363D] px-4 py-2 flex flex-wrap gap-3 items-center">
      {/* Status tabs */}
      <div className="flex items-center gap-1 overflow-x-auto" role="tablist" aria-label="Filter by status">
        {FILTERS.map(({ key, label }) => {
          const active = activeFilter === key
          return (
            <button
              key={key}
              role="tab"
              aria-selected={active}
              onClick={() => setActiveFilter(key)}
              className={`px-3 py-1 rounded-md text-xs font-medium whitespace-nowrap transition-colors ${
                active
                  ? `bg-[#21262D] ${FILTER_COLORS[key]} border border-[#30363D]`
                  : 'text-[#8B949E] hover:text-[#E6EDF3] hover:bg-[#21262D]'
              }`}
            >
              {label}
              <span className={`ml-1.5 tabular-nums ${active ? FILTER_COLORS[key] : 'text-[#484F58]'}`}>
                {counts[key]}
              </span>
            </button>
          )
        })}
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Search */}
      <div className="relative">
        <svg
          className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#484F58]"
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
        </svg>
        <input
          type="search"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search agents…"
          aria-label="Search agents"
          className="bg-[#21262D] border border-[#30363D] text-[#E6EDF3] text-xs rounded-md pl-7 pr-3 py-1.5
            placeholder-[#484F58] focus:outline-none focus:border-[#FFB633] w-44"
        />
      </div>

      {/* Sort */}
      <select
        value={sortBy}
        onChange={(e) => setSortBy(e.target.value as SortBy)}
        aria-label="Sort agents by"
        className="bg-[#21262D] border border-[#30363D] text-[#8B949E] text-xs rounded-md px-2 py-1.5
          focus:outline-none focus:border-[#FFB633]"
      >
        {SORT_OPTIONS.map(({ value, label }) => (
          <option key={value} value={value}>Sort: {label}</option>
        ))}
      </select>
    </div>
  )
}
