export interface CronJob {
  id: string
  cron: string
  task: string
  assign_to: string
  silent?: boolean
  script?: string
  context_from?: string
  run_only_after?: boolean
  last_run?: string | null
  consecutive_failures?: number
  disabled?: boolean
}

export interface CronHistoryEntry {
  id: string
  prompt: string
  status: string
  source: string
  assigned_agent: string | null
  cost_usd: number
  created_at: string
  completed_at: string | null
  error: string | null
}

async function parse_json_or_throw<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || fallback)
  }
  return res.json() as Promise<T>
}

export async function getCronJobs(): Promise<{ jobs: CronJob[]; agents: string[] }> {
  const res = await fetch('/api/cron')
  return parse_json_or_throw(res, 'Failed to fetch cron jobs')
}

export async function createCronJob(job: Partial<CronJob>): Promise<{ status: string; job: CronJob }> {
  const res = await fetch('/api/cron', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(job),
  })
  return parse_json_or_throw(res, 'Failed to create cron job')
}

export async function updateCronJob(id: string, job: Partial<CronJob>): Promise<{ status: string; job: CronJob }> {
  const res = await fetch(`/api/cron/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(job),
  })
  return parse_json_or_throw(res, 'Failed to update cron job')
}

export async function deleteCronJob(id: string): Promise<{ status: string }> {
  const res = await fetch(`/api/cron/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
  return parse_json_or_throw(res, 'Failed to delete cron job')
}

export async function runCronJob(id: string): Promise<{ status: string; task_id: string }> {
  const res = await fetch(`/api/cron/${encodeURIComponent(id)}/run`, {
    method: 'POST',
  })
  return parse_json_or_throw(res, 'Failed to run cron job')
}

export async function getCronHistory(): Promise<{ history: CronHistoryEntry[] }> {
  const res = await fetch('/api/cron/history')
  return parse_json_or_throw(res, 'Failed to fetch cron history')
}
