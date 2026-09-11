// Typed read-only client for the GitHub observation endpoints.
// All endpoints are GET-only and validated against the repository allowlist
// server-side. No write operations are exposed here.

export interface GitHubStatus {
  enabled: boolean
  repository: string | null
  repositories: string[]
  write_enabled: boolean
  connection: string
  last_successful_check: string | null
  summary: GitHubHealthSummary | null
  mcp_enabled: boolean
  mcp_connection: string
}

export interface GitHubHealthSummary {
  repository: string
  sampled: boolean
  open_issues: number
  open_pull_requests: number
  stale_issues: number
  stale_pull_requests: number
  issue_labels: Record<string, number>
  open_issues_created_last_7_days: number
  failed_runs: GitHubFailedRun[]
  pull_request_health: GitHubPRHealth[]
  message: string
}

export interface GitHubFailedRun {
  id: number
  name?: string
  conclusion?: string | null
  head_sha?: string
  url?: string
  updated_at?: string
  failed_steps?: string[]
  likely_cause?: string
}

export interface GitHubPRHealth {
  number: number
  draft: boolean
  blocked_checks?: string[]
  review_states?: string[]
  inspection?: string
}

export interface GitHubRepo {
  full_name: string
  name: string
  description: string | null
  html_url: string
  default_branch: string
  open_issues_count: number
  stargazers_count: number
  forks_count: number
  language: string | null
  pushed_at: string | null
  updated_at: string | null
  license?: { name: string } | null
  private: boolean
}

export interface GitHubTreeEntry {
  path: string
  type: 'blob' | 'tree'
  sha: string
  size?: number
  url?: string
}

export interface GitHubTree {
  sha: string
  truncated: boolean
  tree: GitHubTreeEntry[]
}

export interface GitHubFileContent {
  path: string
  sha: string
  name?: string
  size?: number
  type?: string
  content: string
}

export interface GitHubBranch {
  name: string
  commit: { sha: string; url: string }
  protected: boolean
}

export interface GitHubCommit {
  sha: string
  commit: {
    message: string
    author: { name: string; date: string } | null
  }
  author: { login: string; avatar_url: string } | null
  html_url: string
}

export interface GitHubPullRequest {
  number: number
  title: string
  state: string
  draft: boolean
  user: { login: string } | null
  created_at: string
  updated_at: string
  html_url: string
  head: { ref: string; sha: string }
  base: { ref: string }
  merged: boolean
}

export interface GitHubIssue {
  number: number
  title: string
  state: string
  user: { login: string } | null
  created_at: string
  updated_at: string
  html_url: string
  labels: { name: string }[]
  comments: number
}

export interface GitHubWorkflowRun {
  id: number
  name: string
  status: string
  conclusion: string | null
  head_branch: string
  head_sha: string
  event: string
  created_at: string
  updated_at: string
  html_url: string
}

export interface GitHubWorkflowJob {
  id: number
  name: string
  status: string
  conclusion: string | null
  started_at: string
  completed_at: string | null
  steps: { name: string; status: string; conclusion: string | null }[]
}

export interface GitHubRelease {
  id: number
  tag_name: string
  name: string | null
  published_at: string | null
  html_url: string
  prerelease: boolean
}

export interface GitHubTag {
  name: string
  commit: { sha: string }
}

async function get<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const qs = new URLSearchParams()
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
    }
  }
  const q = qs.toString()
  const res = await fetch(`/api/integrations/github${path}${q ? `?${q}` : ''}`)
  if (!res.ok) {
    let detail = ''
    try { detail = (await res.json()).detail ?? '' } catch { /* ignore */ }
    throw new Error(detail || `GitHub request failed (${res.status})`)
  }
  return res.json()
}

export const getGitHubStatus = () => get<GitHubStatus>('')
export const checkGitHub = async (): Promise<GitHubStatus> => {
  const response = await fetch('/api/integrations/github/check', { method: 'POST' })
  if (!response.ok) throw new Error(`GitHub check failed (${response.status})`)
  return response.json()
}
export const getGitHubHealth = (repository?: string) => get<GitHubHealthSummary>('/health', { repository })
export const getGitHubRepo = (repository?: string) => get<GitHubRepo>('/repo', { repository })
export const getGitHubTree = (sha: string, repository?: string, recursive = true) =>
  get<GitHubTree>('/tree', { sha, repository, recursive })
export const getGitHubContents = (path: string, repository?: string, ref?: string) =>
  get<GitHubFileContent | GitHubTreeEntry[]>('/contents', { path, repository, ref })
export const getGitHubBranches = (repository?: string) => get<GitHubBranch[]>('/branches', { repository, per_page: 100 })
export const getGitHubCommits = (repository?: string, sha?: string, path?: string) =>
  get<GitHubCommit[]>('/commits', { repository, sha, path, per_page: 50 })
export const getGitHubPulls = (repository?: string, state = 'open') =>
  get<GitHubPullRequest[]>('/pulls', { repository, state, per_page: 50 })
export const getGitHubPull = (number: number, repository?: string) =>
  get<GitHubPullRequest>(`/pulls/${number}`, { repository })
export const getGitHubPullFiles = (number: number, repository?: string) =>
  get<{ filename: string; status: string; additions: number; deletions: number; changes: number }[]>(`/pulls/${number}/files`, { repository })
export const getGitHubPullReviews = (number: number, repository?: string) =>
  get<{ id: number; user: { login: string } | null; state: string; submitted_at: string | null; body: string | null }[]>(`/pulls/${number}/reviews`, { repository })
export const getGitHubPullComments = (number: number, repository?: string) =>
  get<{ id: number; user: { login: string } | null; body: string; created_at: string; path: string | null }[]>(`/pulls/${number}/comments`, { repository })
export const getGitHubCommitChecks = (ref: string, repository?: string) =>
  get<{ check_runs: { name: string; status: string; conclusion: string | null }[] }>(`/commits/${encodeURIComponent(ref)}/check-runs`, { repository })
export const getGitHubIssues = (repository?: string, state = 'open') =>
  get<GitHubIssue[]>('/issues', { repository, state, per_page: 50 })
export const getGitHubIssue = (number: number, repository?: string) =>
  get<GitHubIssue>(`/issues/${number}`, { repository })
export const getGitHubIssueComments = (number: number, repository?: string) =>
  get<{ id: number; user: { login: string } | null; body: string; created_at: string }[]>(`/issues/${number}/comments`, { repository })
export const getGitHubWorkflowRuns = (repository?: string, status?: string, branch?: string) =>
  get<{ workflow_runs: GitHubWorkflowRun[] }>('/actions/runs', { repository, status, branch, per_page: 50 })
export const getGitHubWorkflowJobs = (runId: number, repository?: string) =>
  get<{ jobs: GitHubWorkflowJob[] }>(`/actions/runs/${runId}/jobs`, { repository })
export const getGitHubJobLogs = (jobId: number, repository?: string) =>
  get<{ job_id: number; logs: string }>(`/actions/jobs/${jobId}/logs`, { repository })
export const getGitHubReleases = (repository?: string) => get<GitHubRelease[]>('/releases', { repository, per_page: 30 })
export const getGitHubTags = (repository?: string) => get<GitHubTag[]>('/tags', { repository, per_page: 30 })
export const getGitHubLabels = (repository?: string) => get<{ name: string; color: string; description: string | null }[]>('/labels', { repository, per_page: 100 })
