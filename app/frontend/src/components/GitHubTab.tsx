import { useEffect, useMemo, useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import hljs from 'highlight.js/lib/common'
import {
  RefreshCw,
  GitPullRequest,
  FolderTree,
  GitBranch,
  GitCommit,
  CircleDot,
  PlayCircle,
  Tag,
  ExternalLink,
  Search,
  AlertTriangle,
  Folder,
  File,
  ChevronRight,
  ArrowLeft,
  Eye,
  Code2,
  Columns2,
  Copy,
  Check,
  Download,
} from 'lucide-react'
import { GitHubIntegrationStatus } from './GitHubIntegrationStatus'
import {
  getGitHubHealth,
  getGitHubRepo,
  getGitHubTree,
  getGitHubContents,
  getGitHubBranches,
  getGitHubCommits,
  getGitHubPulls,
  getGitHubPullFiles,
  getGitHubPullReviews,
  getGitHubPullComments,
  getGitHubCommitChecks,
  getGitHubIssues,
  getGitHubIssue,
  getGitHubIssueComments,
  getGitHubWorkflowRuns,
  getGitHubWorkflowJobs,
  getGitHubJobLogs,
  getGitHubReleases,
  getGitHubTags,
  type GitHubHealthSummary,
  type GitHubTree,
  type GitHubFileContent,
  type GitHubBranch,
  type GitHubCommit,
  type GitHubPullRequest,
  type GitHubIssue,
  type GitHubWorkflowRun,
  type GitHubWorkflowJob,
  type GitHubRelease,
  type GitHubTag,
} from '../api/githubClient'

type View =
  | 'overview'
  | 'code'
  | 'branches'
  | 'commits'
  | 'pulls'
  | 'issues'
  | 'actions'
  | 'releases'

const inputClass =
  'w-full bg-zinc-900 text-zinc-100 text-sm border border-zinc-800 rounded px-3 py-2 focus:outline-none focus:ring-1 focus:ring-zinc-600 placeholder-zinc-600'

const VIEWS: { key: View; label: string; icon: typeof RefreshCw }[] = [
  { key: 'overview', label: 'Overview', icon: GitPullRequest },
  { key: 'code', label: 'Code', icon: FolderTree },
  { key: 'branches', label: 'Branches', icon: GitBranch },
  { key: 'commits', label: 'Commits', icon: GitCommit },
  { key: 'pulls', label: 'Pull Requests', icon: GitPullRequest },
  { key: 'issues', label: 'Issues', icon: CircleDot },
  { key: 'actions', label: 'Actions', icon: PlayCircle },
  { key: 'releases', label: 'Releases', icon: Tag },
]

function fmtTime(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString()
}

function fmtSize(size?: number): string {
  if (size === undefined || size === null) return '—'
  const n = Number(size)
  if (Number.isNaN(n)) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
  return `${(n / 1024 / 1024 / 1024).toFixed(1)} GB`
}

function shortSha(sha?: string | null): string {
  if (!sha) return '—'
  return sha.slice(0, 7)
}

function StateBadge({ state }: { state: string | null | undefined }) {
  const s = (state ?? 'unknown').toLowerCase()
  const tone =
    s === 'open' || s === 'success' || s === 'completed'
      ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
      : s === 'closed' || s === 'failure' || s === 'failed'
        ? 'bg-red-500/15 text-red-400 border-red-500/30'
        : s === 'merged'
          ? 'bg-purple-500/15 text-purple-400 border-purple-500/30'
          : 'bg-zinc-500/15 text-zinc-400 border-zinc-500/30'
  return (
    <span className={`inline-block rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${tone}`}>
      {s}
    </span>
  )
}

function DraftBadge({ draft }: { draft: boolean }) {
  if (!draft) return null
  return (
    <span className="inline-block rounded border border-amber-500/30 bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-400">
      draft
    </span>
  )
}

function ProtectedBadge({ protected: isProtected }: { protected: boolean }) {
  if (!isProtected) return null
  return (
    <span className="inline-block rounded border border-sky-500/30 bg-sky-500/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-sky-400">
      protected
    </span>
  )
}

function Loading() {
  return <div className="studio-loading" role="status">Loading…<div /><div /><div /></div>
}

function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="studio-error">
      <strong>Something went wrong.</strong>
      <span>{message}</span>
      {onRetry && <button onClick={onRetry}>Try again</button>}
    </div>
  )
}

function Empty({ icon: Icon, title, hint }: { icon: typeof RefreshCw; title: string; hint: string }) {
  return (
    <div className="studio-empty">
      <Icon size={24} />
      <h2>{title}</h2>
      <p>{hint}</p>
    </div>
  )
}

export function GitHubTab() {
  const [view, setView] = useState<View>('overview')
  const [reloadKey, setReloadKey] = useState(0)

  const refresh = useCallback(() => setReloadKey((k) => k + 1), [])

  return (
    <div className="studio-settings relative flex flex-col h-full bg-zinc-950 text-zinc-100 overflow-hidden">
      <div className="studio-section-header">
        <div>
          <h1>GitHub</h1>
          <p>Read-only observation of your repository: health, code, branches, commits, PRs, issues, actions and releases.</p>
        </div>
        <button className="studio-secondary-button" onClick={refresh} aria-label="Refresh">
          <RefreshCw size={16} />
        </button>
      </div>
      <div className="studio-settings-body">
        <GitHubIntegrationStatus />

        <nav className="flex flex-wrap gap-1 border-b border-zinc-800 mb-4" aria-label="GitHub views">
          {VIEWS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setView(key)}
              className={`px-3 py-2 text-sm flex items-center gap-1.5 ${
                view === key ? 'border-b-2 border-amber-400 text-zinc-100' : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              <Icon size={14} />
              {label}
            </button>
          ))}
        </nav>

        <div className="mt-4">
          {view === 'overview' && <OverviewView key={reloadKey} />}
          {view === 'code' && <CodeView key={reloadKey} />}
          {view === 'branches' && <BranchesView key={reloadKey} />}
          {view === 'commits' && <CommitsView key={reloadKey} />}
          {view === 'pulls' && <PullsView key={reloadKey} />}
          {view === 'issues' && <IssuesView key={reloadKey} />}
          {view === 'actions' && <ActionsView key={reloadKey} />}
          {view === 'releases' && <ReleasesView key={reloadKey} />}
        </div>
      </div>
    </div>
  )
}

/* ─────────────────────────── Overview ─────────────────────────── */

function OverviewView() {
  const [data, setData] = useState<GitHubHealthSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    getGitHubHealth()
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'failed'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <Loading />
  if (error) return <ErrorBox message={error} onRetry={load} />
  if (!data) return <Empty icon={GitPullRequest} title="No health data" hint="No health summary available." />

  const stats = [
    { label: 'Open PRs', value: data.open_pull_requests },
    { label: 'Open Issues', value: data.open_issues },
    { label: 'Stale PRs', value: data.stale_pull_requests },
    { label: 'Stale Issues', value: data.stale_issues },
    { label: 'Failed Runs', value: data.failed_runs.length },
    { label: 'Issues (7d)', value: data.open_issues_created_last_7_days },
  ]

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-3">
        {stats.map((s) => (
          <div key={s.label} className="flex-1 min-w-[140px] border border-zinc-800 bg-zinc-900 rounded p-4">
            <div className="text-2xl font-semibold text-zinc-100">{s.value}</div>
            <div className="text-xs text-zinc-500 mt-1">{s.label}</div>
          </div>
        ))}
      </div>

      {data.message && <p className="text-sm text-zinc-300">{data.message}</p>}

      <section>
        <h2 className="text-sm font-medium text-zinc-100 mb-2">Failed workflow runs</h2>
        {data.failed_runs.length === 0 ? (
          <p className="text-sm text-zinc-500">No failed runs.</p>
        ) : (
          <div className="space-y-2">
            {data.failed_runs.map((run) => (
              <div key={run.id} className="border border-zinc-800 bg-zinc-900 rounded p-3">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <span className="text-sm font-medium text-zinc-100">{run.name ?? `Run #${run.id}`}</span>
                  <div className="flex items-center gap-2">
                    <StateBadge state={run.conclusion} />
                    {run.url && (
                      <a className="studio-secondary-button" href={run.url} target="_blank" rel="noreferrer" aria-label="Open run">
                        <ExternalLink size={14} />
                      </a>
                    )}
                  </div>
                </div>
                {run.likely_cause && <p className="text-xs text-zinc-400 mt-1">{run.likely_cause}</p>}
                {run.failed_steps && run.failed_steps.length > 0 && (
                  <p className="text-xs text-zinc-500 mt-1">Failed steps: {run.failed_steps.join(', ')}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="text-sm font-medium text-zinc-100 mb-2">Pull request health</h2>
        {data.pull_request_health.length === 0 ? (
          <p className="text-sm text-zinc-500">No open pull requests.</p>
        ) : (
          <div className="studio-table-scroll">
            <table className="studio-table" aria-label="Pull request health">
              <thead><tr><th>PR</th><th>Draft</th><th>Blocked checks</th><th>Review states</th></tr></thead>
              <tbody>
                {data.pull_request_health.map((pr) => (
                  <tr key={pr.number}>
                    <td><strong>#{pr.number}</strong></td>
                    <td>{pr.draft ? 'Yes' : 'No'}</td>
                    <td>{pr.blocked_checks?.length ? pr.blocked_checks.join(', ') : '—'}</td>
                    <td>{pr.review_states?.length ? pr.review_states.join(', ') : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

/* ─────────────────────────── Code ─────────────────────────── */

function CodeView() {
  const [tree, setTree] = useState<GitHubTree | null>(null)
  const [repoName, setRepoName] = useState('Repository')
  const [defaultBranch, setDefaultBranch] = useState('')
  const [branch, setBranch] = useState('')
  const [branches, setBranches] = useState<GitHubBranch[]>([])
  const [currentPath, setCurrentPath] = useState('')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [content, setContent] = useState<GitHubFileContent | null>(null)
  const [contentLoading, setContentLoading] = useState(false)
  const [contentError, setContentError] = useState('')
  const [fileMode, setFileMode] = useState<FileMode>('rendered')
  const [readme, setReadme] = useState<GitHubFileContent | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [repo, branchList] = await Promise.all([getGitHubRepo(), getGitHubBranches()])
      setRepoName(repo.full_name)
      setDefaultBranch(repo.default_branch)
      setBranch(repo.default_branch)
      setBranches(branchList)
      const t = await getGitHubTree(repo.default_branch)
      setTree(t)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const directoryRows = useMemo(
    () => buildDirectoryRows(tree?.tree ?? [], currentPath),
    [tree, currentPath],
  )
  const rows = useMemo(
    () => directoryRows
      .filter((entry) => !query || entry.name.toLowerCase().includes(query.toLowerCase()))
      .sort((a, b) => (a.type === b.type ? a.name.localeCompare(b.name) : a.type === 'tree' ? -1 : 1)),
    [directoryRows, query],
  )
  const readmeEntry = directoryRows.find(
    (entry) => entry.type === 'blob' && /^readme(?:\.[^.]+)?$/i.test(entry.name),
  )

  useEffect(() => {
    let current = true
    setReadme(null)
    if (!readmeEntry) return () => { current = false }
    getGitHubContents(readmeEntry.path, undefined, branch || defaultBranch)
      .then((value) => { if (current && !Array.isArray(value)) setReadme(value) })
      .catch(() => undefined)
    return () => { current = false }
  }, [readmeEntry?.path, branch, defaultBranch])

  const changeBranch = async (nextBranch: string) => {
    setLoading(true)
    setError('')
    setContent(null)
    setCurrentPath('')
    setQuery('')
    setBranch(nextBranch)
    try {
      setTree(await getGitHubTree(nextBranch))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed')
    } finally {
      setLoading(false)
    }
  }

  const openFile = async (path: string) => {
    setContentLoading(true)
    setContentError('')
    setContent(null)
    try {
      const res = await getGitHubContents(path, undefined, branch || defaultBranch)
      if (Array.isArray(res)) {
        setContentError('This path is a directory, not a file.')
      } else {
        setContent(res)
        setFileMode('rendered')
      }
    } catch (e) {
      setContentError(e instanceof Error ? e.message : 'failed')
    } finally {
      setContentLoading(false)
    }
  }

  if (loading) return <Loading />
  if (error) return <ErrorBox message={error} onRetry={() => void load()} />
  if (!tree) return <Empty icon={FolderTree} title="No repository" hint="No repository tree available." />

  if (content || contentLoading || contentError) {
    return (
      <RepositoryFileView
        content={content}
        loading={contentLoading}
        error={contentError}
        mode={fileMode}
        branch={branch || defaultBranch}
        repository={repoName}
        onMode={setFileMode}
        onBack={() => { setContent(null); setContentError('') }}
        onOpenFolder={(path) => { setContent(null); setContentError(''); setCurrentPath(path) }}
      />
    )
  }

  const crumbs = currentPath.split('/').filter(Boolean)

  return (
    <div className="space-y-4" role="region" aria-label="Repository code browser">
      <div className="flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor="github-branch">Branch</label>
        <select
          id="github-branch"
          aria-label="Branch"
          value={branch}
          onChange={(event) => void changeBranch(event.target.value)}
          className="min-w-40 rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm font-medium text-zinc-100"
        >
          {branches.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
        </select>
        <input
          className={`${inputClass} min-w-52 flex-1`}
          value={query}
          aria-label="Filter files"
          placeholder="Go to file"
          onChange={(e) => setQuery(e.target.value)}
        />
        <button className="studio-secondary-button" onClick={() => setQuery('')} aria-label="Clear filter">
          <Search size={16} />
        </button>
      </div>

      {tree.truncated && (
        <p className="flex items-center gap-2 text-xs text-amber-400">
          <AlertTriangle size={14} /> Tree is truncated — only a subset of files is shown.
        </p>
      )}

      <nav aria-label="Repository path" className="flex min-h-10 flex-wrap items-center gap-1 rounded-t-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm">
        <button className="font-semibold text-sky-400 hover:underline" onClick={() => setCurrentPath('')}>{repoName}</button>
        {crumbs.map((crumb, index) => {
          const path = crumbs.slice(0, index + 1).join('/')
          return <span key={path} className="flex items-center gap-1">
            <ChevronRight size={14} className="text-zinc-600" />
            <button className={index === crumbs.length - 1 ? 'font-semibold text-zinc-100' : 'text-sky-400 hover:underline'} onClick={() => setCurrentPath(path)}>{crumb}</button>
          </span>
        })}
      </nav>

      {rows.length === 0 ? (
        <Empty icon={FolderTree} title="No files" hint="No files or folders match your filter." />
      ) : (
        <div className="studio-table-scroll -mt-4 rounded-b-lg border border-t-0 border-zinc-700">
          <table className="studio-table" aria-label="Repository files">
            <thead><tr><th>Name</th><th className="w-28 text-right">Size</th></tr></thead>
            <tbody>
              {currentPath && <tr className="hover:bg-zinc-800/50">
                <td colSpan={2}>
                  <button className="flex w-full items-center gap-2 text-left text-sky-400" onClick={() => setCurrentPath(crumbs.slice(0, -1).join('/'))}>
                    <ArrowLeft size={16} /> ..
                  </button>
                </td>
              </tr>}
              {rows.map((entry) => (
                <tr key={entry.path} className="hover:bg-zinc-800/50">
                  <td>
                    <button
                      className="flex w-full items-center gap-2 text-left text-sky-400 hover:underline"
                      onClick={() => entry.type === 'tree' ? setCurrentPath(entry.path) : void openFile(entry.path)}
                    >
                      {entry.type === 'tree' ? <Folder size={16} className="shrink-0 fill-sky-400/20" /> : <File size={16} className="shrink-0 text-zinc-500" />}
                      <span className="break-all">{entry.name}</span>
                    </button>
                  </td>
                  <td className="text-right text-zinc-500">{entry.type === 'blob' ? fmtSize(entry.size) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {readme && <section className="overflow-hidden rounded-lg border border-zinc-700 bg-zinc-900" aria-label={`${readme.name || 'README'} rendered`}>
        <header className="flex items-center gap-2 border-b border-zinc-700 px-4 py-3 text-sm font-semibold">
          <File size={16} /> {readme.name || 'README'}
        </header>
        <div className="vault-md-preview p-5 sm:p-8"><ReactMarkdown remarkPlugins={[remarkGfm]}>{readme.content}</ReactMarkdown></div>
      </section>}
    </div>
  )
}

type FileMode = 'rendered' | 'raw' | 'split'
type RepositoryBrowserEntry = GitHubTree['tree'][number] & { name: string }

function buildDirectoryRows(tree: GitHubTree['tree'], currentPath: string): RepositoryBrowserEntry[] {
  const prefix = currentPath ? `${currentPath}/` : ''
  const rows = new Map<string, RepositoryBrowserEntry>()
  for (const entry of tree) {
    if (!entry.path.startsWith(prefix) || entry.path === currentPath) continue
    const rest = entry.path.slice(prefix.length)
    const slash = rest.indexOf('/')
    if (slash >= 0) {
      const name = rest.slice(0, slash)
      const path = `${prefix}${name}`
      if (!rows.has(path)) rows.set(path, { name, path, type: 'tree', sha: entry.sha })
    } else {
      rows.set(entry.path, { ...entry, name: rest })
    }
  }
  return [...rows.values()]
}

function isMarkdownFile(path: string): boolean {
  return /\.(md|markdown|mdx)$/i.test(path)
}

function languageForPath(path: string): string | undefined {
  const extension = path.split('.').pop()?.toLowerCase() ?? ''
  const aliases: Record<string, string> = {
    py: 'python', ts: 'typescript', tsx: 'typescript', js: 'javascript', jsx: 'javascript',
    json: 'json', yaml: 'yaml', yml: 'yaml', css: 'css', html: 'xml', xml: 'xml',
    sh: 'bash', bash: 'bash', toml: 'ini', ini: 'ini', sql: 'sql', md: 'markdown',
  }
  const candidate = aliases[extension] || extension
  return candidate && hljs.getLanguage(candidate) ? candidate : undefined
}

function SourcePane({ content, highlighted, label }: { content: GitHubFileContent; highlighted: boolean; label: string }) {
  const lines = content.content.split('\n').length
  const html = useMemo(() => {
    if (!highlighted) return ''
    const language = languageForPath(content.path)
    return language ? hljs.highlight(content.content, { language }).value : hljs.highlightAuto(content.content).value
  }, [content.content, content.path, highlighted])

  return <div className="min-w-0 overflow-auto bg-[#0d1117]" aria-label={label}>
    <div className="flex min-w-max text-[12px] leading-5 sm:text-[13px]">
      <pre aria-hidden="true" className="sticky left-0 z-10 select-none border-r border-zinc-800 bg-[#0d1117] px-3 py-4 text-right text-zinc-600">
        {Array.from({ length: lines }, (_, index) => index + 1).join('\n')}
      </pre>
      {highlighted
        ? <pre className="m-0 min-w-full p-4 text-zinc-200"><code className="hljs !bg-transparent !p-0" dangerouslySetInnerHTML={{ __html: html }} /></pre>
        : <pre className="m-0 min-w-full whitespace-pre p-4 text-zinc-200"><code>{content.content || '(empty file)'}</code></pre>}
    </div>
  </div>
}

function RenderedPane({ content }: { content: GitHubFileContent }) {
  if (!isMarkdownFile(content.path)) return <SourcePane content={content} highlighted label="Rendered source" />
  return <article className="vault-md-preview min-w-0 overflow-auto bg-zinc-950 p-5 sm:p-8" aria-label="Rendered file">
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{content.content || ''}</ReactMarkdown>
  </article>
}

function RepositoryFileView({ content, loading, error, mode, branch, repository, onMode, onBack, onOpenFolder }: {
  content: GitHubFileContent | null
  loading: boolean
  error: string
  mode: FileMode
  branch: string
  repository: string
  onMode: (mode: FileMode) => void
  onBack: () => void
  onOpenFolder: (path: string) => void
}) {
  const [copied, setCopied] = useState(false)
  const parts = content?.path.split('/') ?? []
  const copy = async () => {
    if (!content) return
    await navigator.clipboard.writeText(content.content)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }
  const download = () => {
    if (!content) return
    const url = URL.createObjectURL(new Blob([content.content], { type: 'text/plain;charset=utf-8' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = content.name || parts[parts.length - 1] || 'file'
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return <section className="space-y-3" aria-label="Repository file viewer">
    <div className="flex flex-wrap items-center gap-1 text-sm">
      <button className="mr-2 flex items-center gap-1 text-zinc-400 hover:text-zinc-100" onClick={onBack}><ArrowLeft size={15} /> Code</button>
      <span className="font-semibold text-sky-400">{repository}</span>
      {parts.map((part, index) => <span key={`${part}-${index}`} className="flex items-center gap-1">
        <ChevronRight size={14} className="text-zinc-600" />
        {index < parts.length - 1
          ? <button className="text-sky-400 hover:underline" onClick={() => onOpenFolder(parts.slice(0, index + 1).join('/'))}>{part}</button>
          : <strong className="text-zinc-100">{part}</strong>}
      </span>)}
    </div>
    <div className="overflow-hidden rounded-lg border border-zinc-700 bg-zinc-900">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-700 px-3 py-2">
        <div className="min-w-0 text-xs text-zinc-400"><strong className="text-zinc-100">{content?.name || parts[parts.length - 1]}</strong>{content && <> · {fmtSize(content.size ?? new Blob([content.content]).size)} · {branch}</>}</div>
        <div className="flex flex-wrap items-center gap-1" role="group" aria-label="File view">
          <FileModeButton active={mode === 'rendered'} icon={Eye} label="Rendered" onClick={() => onMode('rendered')} />
          <FileModeButton active={mode === 'raw'} icon={Code2} label="Raw" onClick={() => onMode('raw')} />
          <FileModeButton active={mode === 'split'} icon={Columns2} label="Split" onClick={() => onMode('split')} />
          <button className="studio-secondary-button" onClick={() => void copy()} disabled={!content} aria-label="Copy file contents">{copied ? <Check size={14} /> : <Copy size={14} />}</button>
          <button className="studio-secondary-button" onClick={download} disabled={!content} aria-label="Download file"><Download size={14} /></button>
        </div>
      </header>
      {loading && <Loading />}
      {error && <ErrorBox message={error} onRetry={onBack} />}
      {content && mode === 'rendered' && <RenderedPane content={content} />}
      {content && mode === 'raw' && <SourcePane content={content} highlighted={false} label="Raw file" />}
      {content && mode === 'split' && <div className="grid min-h-[28rem] grid-cols-1 divide-y divide-zinc-700 lg:grid-cols-2 lg:divide-x lg:divide-y-0">
        <RenderedPane content={content} />
        <SourcePane content={content} highlighted={false} label="Raw file" />
      </div>}
    </div>
  </section>
}

function FileModeButton({ active, icon: Icon, label, onClick }: { active: boolean; icon: typeof Eye; label: string; onClick: () => void }) {
  return <button
    className={`flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-xs ${active ? 'border-zinc-600 bg-zinc-700 text-white' : 'border-transparent text-zinc-400 hover:bg-zinc-800 hover:text-white'}`}
    aria-pressed={active}
    onClick={onClick}
  ><Icon size={14} /> {label}</button>
}

/* ─────────────────────────── Branches ─────────────────────────── */

function BranchesView() {
  const [branches, setBranches] = useState<GitHubBranch[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    getGitHubBranches()
      .then(setBranches)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'failed'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <Loading />
  if (error) return <ErrorBox message={error} onRetry={load} />
  if (branches.length === 0) return <Empty icon={GitBranch} title="No branches" hint="No branches found." />

  return (
    <div className="studio-table-scroll">
      <table className="studio-table" aria-label="Branches">
        <thead><tr><th>Name</th><th>Commit</th><th>Protected</th></tr></thead>
        <tbody>
          {branches.map((b) => (
            <tr key={b.name}>
              <td><strong>{b.name}</strong></td>
              <td className="font-mono text-xs">{shortSha(b.commit.sha)}</td>
              <td><ProtectedBadge protected={b.protected} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ─────────────────────────── Commits ─────────────────────────── */

function CommitsView() {
  const [commits, setCommits] = useState<GitHubCommit[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    getGitHubCommits()
      .then(setCommits)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'failed'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <Loading />
  if (error) return <ErrorBox message={error} onRetry={load} />
  if (commits.length === 0) return <Empty icon={GitCommit} title="No commits" hint="No commits found." />

  return (
    <div className="space-y-2">
      {commits.map((c) => (
        <div key={c.sha} className="border border-zinc-800 bg-zinc-900 rounded p-3">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <span className="font-mono text-xs text-zinc-400">{shortSha(c.sha)}</span>
            <a className="studio-secondary-button" href={c.html_url} target="_blank" rel="noreferrer" aria-label="Open commit">
              <ExternalLink size={14} />
            </a>
          </div>
          <p className="text-sm text-zinc-100 mt-1">{c.commit.message.split('\n')[0]}</p>
          <p className="text-xs text-zinc-500 mt-1">
            {c.author?.login ?? c.commit.author?.name ?? 'unknown'} · {fmtTime(c.commit.author?.date)}
          </p>
        </div>
      ))}
    </div>
  )
}

/* ─────────────────────────── Pulls ─────────────────────────── */

interface PullDetail {
  files: { filename: string; status: string; additions: number; deletions: number; changes: number }[]
  reviews: { id: number; user: { login: string } | null; state: string; submitted_at: string | null; body: string | null }[]
  comments: { id: number; user: { login: string } | null; body: string; created_at: string; path: string | null }[]
  checks: { name: string; status: string; conclusion: string | null }[]
}

function PullDetailPanel({ pr }: { pr: GitHubPullRequest }) {
  const [detail, setDetail] = useState<PullDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    Promise.all([
      getGitHubPullFiles(pr.number),
      getGitHubPullReviews(pr.number),
      getGitHubPullComments(pr.number),
      getGitHubCommitChecks(pr.head.sha),
    ])
      .then(([files, reviews, comments, checksRes]) => {
        if (cancelled) return
        setDetail({ files, reviews, comments, checks: checksRes.check_runs })
      })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : 'failed') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [pr.number, pr.head.sha])

  if (loading) return <div className="mt-4"><Loading /></div>
  if (error) return <div className="mt-4"><ErrorBox message={error} /></div>
  if (!detail) return null

  return (
    <div className="border border-zinc-800 bg-zinc-900 rounded p-4 mt-4 space-y-4">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className="text-sm font-medium text-zinc-100">#{pr.number} — {pr.title}</h3>
        <StateBadge state={pr.state} />
      </div>

      <section>
        <h4 className="text-xs uppercase tracking-widest text-zinc-500 mb-2">Files changed</h4>
        <div className="studio-table-scroll">
          <table className="studio-table" aria-label="Changed files">
            <thead><tr><th>Filename</th><th>Status</th><th>+/-</th></tr></thead>
            <tbody>
              {detail.files.map((f) => (
                <tr key={f.filename}>
                  <td className="break-all">{f.filename}</td>
                  <td><StateBadge state={f.status} /></td>
                  <td className="font-mono text-xs">
                    <span className="text-emerald-400">+{f.additions}</span>{' '}
                    <span className="text-red-400">-{f.deletions}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h4 className="text-xs uppercase tracking-widest text-zinc-500 mb-2">Reviews</h4>
        {detail.reviews.length === 0 ? (
          <p className="text-sm text-zinc-500">No reviews.</p>
        ) : (
          <div className="space-y-1">
            {detail.reviews.map((r) => (
              <div key={r.id} className="flex items-center gap-2 text-sm">
                <StateBadge state={r.state} />
                <span className="text-zinc-300">{r.user?.login ?? 'unknown'}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h4 className="text-xs uppercase tracking-widest text-zinc-500 mb-2">Comments</h4>
        {detail.comments.length === 0 ? (
          <p className="text-sm text-zinc-500">No comments.</p>
        ) : (
          <div className="space-y-2">
            {detail.comments.map((c) => (
              <div key={c.id} className="text-sm">
                <span className="text-zinc-400">{c.user?.login ?? 'unknown'}</span>
                {c.path && <span className="text-zinc-600"> · {c.path}</span>}
                <p className="text-zinc-300 mt-0.5 whitespace-pre-wrap">{c.body}</p>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h4 className="text-xs uppercase tracking-widest text-zinc-500 mb-2">Check runs</h4>
        {detail.checks.length === 0 ? (
          <p className="text-sm text-zinc-500">No check runs.</p>
        ) : (
          <div className="space-y-1">
            {detail.checks.map((c, i) => (
              <div key={i} className="flex items-center gap-2 text-sm">
                <StateBadge state={c.conclusion ?? c.status} />
                <span className="text-zinc-300">{c.name}</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function PullsView() {
  const [pulls, setPulls] = useState<GitHubPullRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<GitHubPullRequest | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    getGitHubPulls()
      .then(setPulls)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'failed'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <Loading />
  if (error) return <ErrorBox message={error} onRetry={load} />
  if (pulls.length === 0) return <Empty icon={GitPullRequest} title="No pull requests" hint="No open pull requests found." />

  return (
    <div>
      <div className="studio-table-scroll">
        <table className="studio-table" aria-label="Pull requests">
          <thead><tr><th>#</th><th>Title</th><th>State</th><th>Draft</th><th>Author</th><th>Updated</th></tr></thead>
          <tbody>
            {pulls.map((p) => (
              <tr key={p.number} className="cursor-pointer hover:bg-zinc-800/50" onClick={() => setSelected(p)}>
                <td><strong>#{p.number}</strong></td>
                <td className="break-all">{p.title}</td>
                <td><StateBadge state={p.state} /></td>
                <td><DraftBadge draft={p.draft} /></td>
                <td>{p.user?.login ?? '—'}</td>
                <td>{fmtTime(p.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected && <PullDetailPanel pr={selected} />}
    </div>
  )
}

/* ─────────────────────────── Issues ─────────────────────────── */

interface IssueDetail {
  issue: GitHubIssue
  comments: { id: number; user: { login: string } | null; body: string; created_at: string }[]
}

function IssueDetailPanel({ number }: { number: number }) {
  const [detail, setDetail] = useState<IssueDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    Promise.all([getGitHubIssue(number), getGitHubIssueComments(number)])
      .then(([issue, comments]) => { if (!cancelled) setDetail({ issue, comments }) })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : 'failed') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [number])

  if (loading) return <div className="mt-4"><Loading /></div>
  if (error) return <div className="mt-4"><ErrorBox message={error} /></div>
  if (!detail) return null

  const { issue, comments } = detail

  return (
    <div className="border border-zinc-800 bg-zinc-900 rounded p-4 mt-4 space-y-4">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className="text-sm font-medium text-zinc-100">#{issue.number} — {issue.title}</h3>
        <StateBadge state={issue.state} />
      </div>

      {issue.labels.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {issue.labels.map((l) => (
            <span key={l.name} className="rounded border border-zinc-700 px-1.5 py-0.5 text-[10px] text-zinc-300">{l.name}</span>
          ))}
        </div>
      )}

      <p className="text-sm text-zinc-300 whitespace-pre-wrap">{issue.title}</p>

      <section>
        <h4 className="text-xs uppercase tracking-widest text-zinc-500 mb-2">Comments</h4>
        {comments.length === 0 ? (
          <p className="text-sm text-zinc-500">No comments.</p>
        ) : (
          <div className="space-y-2">
            {comments.map((c) => (
              <div key={c.id} className="text-sm">
                <span className="text-zinc-400">{c.user?.login ?? 'unknown'} · {fmtTime(c.created_at)}</span>
                <p className="text-zinc-300 mt-0.5 whitespace-pre-wrap">{c.body}</p>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function IssuesView() {
  const [issues, setIssues] = useState<GitHubIssue[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<number | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    getGitHubIssues()
      .then(setIssues)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'failed'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <Loading />
  if (error) return <ErrorBox message={error} onRetry={load} />
  if (issues.length === 0) return <Empty icon={CircleDot} title="No issues" hint="No open issues found." />

  return (
    <div>
      <div className="studio-table-scroll">
        <table className="studio-table" aria-label="Issues">
          <thead><tr><th>#</th><th>Title</th><th>State</th><th>Labels</th><th>Author</th><th>Comments</th></tr></thead>
          <tbody>
            {issues.map((i) => (
              <tr key={i.number} className="cursor-pointer hover:bg-zinc-800/50" onClick={() => setSelected(i.number)}>
                <td><strong>#{i.number}</strong></td>
                <td className="break-all">{i.title}</td>
                <td><StateBadge state={i.state} /></td>
                <td>
                  <div className="flex flex-wrap gap-1">
                    {i.labels.map((l) => (
                      <span key={l.name} className="rounded border border-zinc-700 px-1.5 py-0.5 text-[10px] text-zinc-300">{l.name}</span>
                    ))}
                  </div>
                </td>
                <td>{i.user?.login ?? '—'}</td>
                <td>{i.comments}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected !== null && <IssueDetailPanel number={selected} />}
    </div>
  )
}

/* ─────────────────────────── Actions ─────────────────────────── */

function RunJobsPanel({ run }: { run: GitHubWorkflowRun }) {
  const [jobs, setJobs] = useState<GitHubWorkflowJob[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [logs, setLogs] = useState<{ jobId: number; text: string } | null>(null)
  const [logsLoading, setLogsLoading] = useState(false)
  const [logsError, setLogsError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    getGitHubWorkflowJobs(run.id)
      .then((res) => { if (!cancelled) setJobs(res.jobs) })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : 'failed') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [run.id])

  const showLogs = async (jobId: number) => {
    setLogsLoading(true)
    setLogsError('')
    setLogs(null)
    try {
      const res = await getGitHubJobLogs(jobId)
      setLogs({ jobId, text: res.logs })
    } catch (e) {
      setLogsError(e instanceof Error ? e.message : 'failed')
    } finally {
      setLogsLoading(false)
    }
  }

  if (loading) return <div className="mt-4"><Loading /></div>
  if (error) return <div className="mt-4"><ErrorBox message={error} /></div>

  return (
    <div className="border border-zinc-800 bg-zinc-900 rounded p-4 mt-4 space-y-4">
      <h3 className="text-sm font-medium text-zinc-100">{run.name}</h3>
      {jobs.length === 0 ? (
        <p className="text-sm text-zinc-500">No jobs.</p>
      ) : (
        <div className="space-y-3">
          {jobs.map((job) => (
            <div key={job.id} className="border border-zinc-800 rounded p-3">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <span className="text-sm text-zinc-100">{job.name}</span>
                <div className="flex items-center gap-2">
                  <StateBadge state={job.conclusion ?? job.status} />
                  <button className="studio-secondary-button" onClick={() => void showLogs(job.id)} aria-label={`Logs for ${job.name}`}>
                    Logs
                  </button>
                </div>
              </div>
              {job.steps.length > 0 && (
                <div className="mt-2 space-y-1">
                  {job.steps.map((step, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <StateBadge state={step.conclusion ?? step.status} />
                      <span className="text-zinc-400">{step.name}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {logsLoading && <Loading />}
      {logsError && <ErrorBox message={logsError} />}
      {logs && !logsLoading && (
        <div className="border border-zinc-800 rounded p-3">
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-xs uppercase tracking-widest text-zinc-500">Job logs</h4>
            <button className="text-xs text-zinc-500 hover:text-zinc-300" onClick={() => setLogs(null)}>Close</button>
          </div>
          <pre className="text-xs text-zinc-300 whitespace-pre-wrap break-words max-h-96 overflow-y-auto">{logs.text}</pre>
        </div>
      )}
    </div>
  )
}

function ActionsView() {
  const [runs, setRuns] = useState<GitHubWorkflowRun[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<GitHubWorkflowRun | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    getGitHubWorkflowRuns()
      .then((res) => setRuns(res.workflow_runs))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'failed'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <Loading />
  if (error) return <ErrorBox message={error} onRetry={load} />
  if (runs.length === 0) return <Empty icon={PlayCircle} title="No workflow runs" hint="No workflow runs found." />

  return (
    <div>
      <div className="studio-table-scroll">
        <table className="studio-table" aria-label="Workflow runs">
          <thead><tr><th>Name</th><th>Status</th><th>Conclusion</th><th>Branch</th><th>Event</th><th>Updated</th></tr></thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} className="cursor-pointer hover:bg-zinc-800/50" onClick={() => setSelected(r)}>
                <td className="break-all">{r.name}</td>
                <td><StateBadge state={r.status} /></td>
                <td><StateBadge state={r.conclusion} /></td>
                <td>{r.head_branch}</td>
                <td>{r.event}</td>
                <td>{fmtTime(r.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected && <RunJobsPanel run={selected} />}
    </div>
  )
}

/* ─────────────────────────── Releases ─────────────────────────── */

function ReleasesView() {
  const [releases, setReleases] = useState<GitHubRelease[]>([])
  const [tags, setTags] = useState<GitHubTag[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    Promise.all([getGitHubReleases(), getGitHubTags()])
      .then(([rel, tgs]) => { setReleases(rel); setTags(tgs) })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'failed'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <Loading />
  if (error) return <ErrorBox message={error} onRetry={load} />

  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-sm font-medium text-zinc-100 mb-2">Releases</h2>
        {releases.length === 0 ? (
          <p className="text-sm text-zinc-500">No releases.</p>
        ) : (
          <div className="studio-table-scroll">
            <table className="studio-table" aria-label="Releases">
              <thead><tr><th>Tag</th><th>Name</th><th>Published</th><th>Prerelease</th><th><span className="sr-only">Open</span></th></tr></thead>
              <tbody>
                {releases.map((r) => (
                  <tr key={r.id}>
                    <td className="font-mono text-xs">{r.tag_name}</td>
                    <td className="break-all">{r.name ?? '—'}</td>
                    <td>{fmtTime(r.published_at)}</td>
                    <td>
                      {r.prerelease ? (
                        <span className="inline-block rounded border border-amber-500/30 bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-400">prerelease</span>
                      ) : (
                        <span className="text-zinc-600">—</span>
                      )}
                    </td>
                    <td>
                      <a className="studio-secondary-button" href={r.html_url} target="_blank" rel="noreferrer" aria-label="Open release">
                        <ExternalLink size={14} />
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h2 className="text-sm font-medium text-zinc-100 mb-2">Tags</h2>
        {tags.length === 0 ? (
          <p className="text-sm text-zinc-500">No tags.</p>
        ) : (
          <div className="studio-table-scroll">
            <table className="studio-table" aria-label="Tags">
              <thead><tr><th>Name</th><th>Commit</th></tr></thead>
              <tbody>
                {tags.map((t) => (
                  <tr key={t.name}>
                    <td className="font-mono text-xs">{t.name}</td>
                    <td className="font-mono text-xs">{shortSha(t.commit.sha)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
