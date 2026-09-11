"""Read-only GitHub observation endpoints for the frontend GitHub tab.

These endpoints expose a bounded, read-only view of the configured GitHub
repository (and any repository in the allowlist) for the UI: repo metadata,
file tree and contents, branches, commits, pull requests (with reviews,
checks, files, and comments), issues (with comments), Actions runs/jobs/logs,
releases/tags, and a concise health overview.

Security model (mirrors plugins/github/github.py):
  - Every request is validated against the repository allowlist via
    ``gh.repository()`` — arbitrary repos are refused.
  - Only GET requests are served; there are no write endpoints here.
  - Paths/refs are sanitized against traversal and control characters.
  - Responses are redacted (tokens stripped) and bounded in size by the
    underlying ``gh.client.request`` 2 MB cap.
  - No GitHub requests are made during normal dashboard polling — only the
    status endpoint is cheap; everything else is on-demand.
"""
from __future__ import annotations

import asyncio
import base64
import time
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query

from app.utils.github import client as gh

router = APIRouter(prefix='/integrations/github', tags=['integrations'])

# On-demand health check throttle (mirrors the original /check behaviour).
_lock = asyncio.Lock()
_last_attempt = 0.0

# Read-only route templates. Keys are operation names; values are GitHub API
# suffixes with {placeholders}. This is the single source of truth for what
# the UI may fetch — no arbitrary suffix is ever accepted.
READ_ROUTES = {
    'repo': '',
    'tree': '/git/trees/{sha}',
    'contents': '/contents/{path}',
    'branches': '/branches',
    'branch': '/branches/{branch}',
    'commits': '/commits',
    'commit': '/commits/{sha}',
    'pull_requests': '/pulls',
    'pull_request': '/pulls/{number}',
    'pull_request_files': '/pulls/{number}/files',
    'pull_request_reviews': '/pulls/{number}/reviews',
    'pull_request_comments': '/pulls/{number}/comments',
    'commit_checks': '/commits/{ref}/check-runs',
    'commit_status': '/commits/{ref}/status',
    'issues': '/issues',
    'issue': '/issues/{number}',
    'issue_comments': '/issues/{number}/comments',
    'workflow_runs': '/actions/runs',
    'workflow_run': '/actions/runs/{run_id}',
    'workflow_jobs': '/actions/runs/{run_id}/jobs',
    'releases': '/releases',
    'tags': '/tags',
    'labels': '/labels',
}

# Query params allowed per operation (whitelist; everything else dropped).
ALLOWED_QUERY = {
    'tree': {'recursive'},
    'contents': {'ref'},
    'commits': {'sha', 'path', 'since', 'until', 'per_page', 'page'},
    'pull_requests': {'state', 'head', 'base', 'sort', 'direction', 'per_page', 'page'},
    'issues': {'state', 'labels', 'since', 'sort', 'direction', 'per_page', 'page'},
    'workflow_runs': {'branch', 'status', 'event', 'head_sha', 'per_page', 'page'},
    'releases': {'per_page', 'page'},
    'tags': {'per_page', 'page'},
    'branches': {'per_page', 'page'},
    'labels': {'per_page', 'page'},
}

# Placeholder -> sanitizer. Every placeholder value is validated before use.
_PLACEHOLDER_KINDS = {
    'number': 'int',
    'run_id': 'int',
    'sha': 'ref',
    'ref': 'ref',
    'branch': 'ref',
    'path': 'path',
}


def _positive(value, name='id'):
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f'{name} must be a positive integer.')
    if value < 1:
        raise HTTPException(status_code=422, detail=f'{name} must be a positive integer.')
    return value


def _sanitize_ref(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise HTTPException(status_code=422, detail='ref must be a non-empty string.')
    if any(c in value for c in ('\\', '%', '?', '#', '\n', '\r', '\x00')):
        raise HTTPException(status_code=422, detail='ref contains invalid characters.')
    if any(p in ('.', '..') for p in value.split('/')):
        raise HTTPException(status_code=422, detail='ref must not contain traversal segments.')
    return value


def _sanitize_path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise HTTPException(status_code=422, detail='path must be a non-empty string.')
    if any(c in value for c in ('\\', '%', '?', '#', '\n', '\r', '\x00')):
        raise HTTPException(status_code=422, detail='path contains invalid characters.')
    if any(p in ('.', '..') for p in value.split('/')):
        raise HTTPException(status_code=422, detail='path must not contain traversal segments.')
    return value


def _resolve_repo(repository: str | None) -> str:
    """Validate the requested repo against the allowlist; default to self repo."""
    try:
        return gh.repository(repository or None)
    except gh.GitHubError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


async def _read(repository: str | None, operation: str, **params):
    """Execute a whitelisted read operation and return redacted JSON."""
    repo = _resolve_repo(repository)
    route = READ_ROUTES[operation]
    substitutions = {}
    for key in ('number', 'run_id', 'sha', 'ref', 'branch', 'path'):
        if '{' + key + '}' in route:
            raw = params.pop(key, None)
            if raw is None:
                raise HTTPException(status_code=422, detail=f'missing required parameter: {key}')
            kind = _PLACEHOLDER_KINDS.get(key, 'ref')
            if kind == 'int':
                substitutions[key] = _positive(raw, key)
            elif kind == 'path':
                substitutions[key] = quote(_sanitize_path(str(raw)), safe='/')
            else:
                substitutions[key] = quote(_sanitize_ref(str(raw)), safe='')
    # Build the query string from the whitelist.
    query = {}
    allowed = ALLOWED_QUERY.get(operation, set())
    for k, v in params.items():
        if k in allowed and v is not None and v != '':
            query[k] = v
    if 'per_page' in query:
        query['per_page'] = min(100, _positive(query['per_page'], 'per_page'))
    if 'page' in query:
        query['page'] = _positive(query['page'], 'page')
    try:
        result = await gh.client.request(repo, route.format(**substitutions), params=query or None)
    except gh.GitHubError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    # Decode file contents for the UI (base64 -> text) when reading a file.
    if operation == 'contents' and isinstance(result, dict) and result.get('encoding') == 'base64':
        try:
            content = base64.b64decode(result.get('content', ''), validate=False).decode('utf-8', errors='replace')
        except Exception:
            content = ''
        result = {'path': result.get('path'), 'sha': result.get('sha'),
                  'name': result.get('name'), 'size': result.get('size'),
                  'type': result.get('type'), 'content': content}
    # Filter PRs out of the issues list (issues endpoint returns both).
    if operation == 'issues' and isinstance(result, list):
        result = [item for item in result if 'pull_request' not in item]
    return gh.redact(result)


@router.get('')
async def github_status():
    result = gh.status()
    from app.utils.mcp import mcp_host_manager
    result['mcp_connection'] = mcp_host_manager.get_state('github')
    return result


@router.post('/check')
async def github_check():
    global _last_attempt
    async with _lock:
        if time.monotonic() - _last_attempt >= 60:
            _last_attempt = time.monotonic()
            try:
                await asyncio.wait_for(gh.health_summary(), timeout=90)
            except (gh.GitHubError, TimeoutError):
                pass
    return await github_status()


@router.get('/health')
async def github_health(repository: str | None = Query(default=None)):
    """Concise health overview: failed runs, open PRs, open issues, staleness."""
    try:
        repo = _resolve_repo(repository)
        summary = await asyncio.wait_for(gh.health_summary(repo), timeout=90)
    except gh.GitHubError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except TimeoutError:
        raise HTTPException(status_code=504, detail='GitHub health check timed out.') from None
    return summary


@router.get('/repo')
async def github_repo(repository: str | None = Query(default=None)):
    return await _read(repository, 'repo')


@router.get('/tree')
async def github_tree(repository: str | None = Query(default=None),
                      sha: str = Query(...),
                      recursive: bool = Query(default=True)):
    return await _read(repository, 'tree', sha=sha, recursive='1' if recursive else None)


@router.get('/contents')
async def github_contents(repository: str | None = Query(default=None),
                          path: str = Query(...),
                          ref: str | None = Query(default=None)):
    return await _read(repository, 'contents', path=path, ref=ref)


@router.get('/branches')
async def github_branches(repository: str | None = Query(default=None),
                          per_page: int = Query(default=30),
                          page: int = Query(default=1)):
    return await _read(repository, 'branches', per_page=per_page, page=page)


@router.get('/branches/{branch}')
async def github_branch(branch: str, repository: str | None = Query(default=None)):
    return await _read(repository, 'branch', branch=branch)


@router.get('/commits')
async def github_commits(repository: str | None = Query(default=None),
                         sha: str | None = Query(default=None),
                         path: str | None = Query(default=None),
                         since: str | None = Query(default=None),
                         until: str | None = Query(default=None),
                         per_page: int = Query(default=30),
                         page: int = Query(default=1)):
    return await _read(repository, 'commits', sha=sha, path=path, since=since, until=until,
                       per_page=per_page, page=page)


@router.get('/commits/{sha}')
async def github_commit(sha: str, repository: str | None = Query(default=None)):
    return await _read(repository, 'commit', sha=sha)


@router.get('/pulls')
async def github_pulls(repository: str | None = Query(default=None),
                       state: str = Query(default='open'),
                       head: str | None = Query(default=None),
                       base: str | None = Query(default=None),
                       sort: str | None = Query(default=None),
                       direction: str | None = Query(default=None),
                       per_page: int = Query(default=30),
                       page: int = Query(default=1)):
    return await _read(repository, 'pull_requests', state=state, head=head, base=base,
                       sort=sort, direction=direction, per_page=per_page, page=page)


@router.get('/pulls/{number}')
async def github_pull(number: int, repository: str | None = Query(default=None)):
    return await _read(repository, 'pull_request', number=number)


@router.get('/pulls/{number}/files')
async def github_pull_files(number: int, repository: str | None = Query(default=None)):
    return await _read(repository, 'pull_request_files', number=number)


@router.get('/pulls/{number}/reviews')
async def github_pull_reviews(number: int, repository: str | None = Query(default=None)):
    return await _read(repository, 'pull_request_reviews', number=number)


@router.get('/pulls/{number}/comments')
async def github_pull_comments(number: int, repository: str | None = Query(default=None)):
    return await _read(repository, 'pull_request_comments', number=number)


@router.get('/commits/{ref}/check-runs')
async def github_commit_checks(ref: str, repository: str | None = Query(default=None)):
    return await _read(repository, 'commit_checks', ref=ref)


@router.get('/commits/{ref}/status')
async def github_commit_status(ref: str, repository: str | None = Query(default=None)):
    return await _read(repository, 'commit_status', ref=ref)


@router.get('/issues')
async def github_issues(repository: str | None = Query(default=None),
                        state: str = Query(default='open'),
                        labels: str | None = Query(default=None),
                        since: str | None = Query(default=None),
                        sort: str | None = Query(default=None),
                        direction: str | None = Query(default=None),
                        per_page: int = Query(default=30),
                        page: int = Query(default=1)):
    return await _read(repository, 'issues', state=state, labels=labels, since=since,
                       sort=sort, direction=direction, per_page=per_page, page=page)


@router.get('/issues/{number}')
async def github_issue(number: int, repository: str | None = Query(default=None)):
    return await _read(repository, 'issue', number=number)


@router.get('/issues/{number}/comments')
async def github_issue_comments(number: int, repository: str | None = Query(default=None)):
    return await _read(repository, 'issue_comments', number=number)


@router.get('/actions/runs')
async def github_workflow_runs(repository: str | None = Query(default=None),
                               branch: str | None = Query(default=None),
                               status: str | None = Query(default=None),
                               event: str | None = Query(default=None),
                               head_sha: str | None = Query(default=None),
                               per_page: int = Query(default=30),
                               page: int = Query(default=1)):
    return await _read(repository, 'workflow_runs', branch=branch, status=status, event=event,
                       head_sha=head_sha, per_page=per_page, page=page)


@router.get('/actions/runs/{run_id}')
async def github_workflow_run(run_id: int, repository: str | None = Query(default=None)):
    return await _read(repository, 'workflow_run', run_id=run_id)


@router.get('/actions/runs/{run_id}/jobs')
async def github_workflow_jobs(run_id: int, repository: str | None = Query(default=None)):
    return await _read(repository, 'workflow_jobs', run_id=run_id)


@router.get('/actions/jobs/{job_id}/logs')
async def github_workflow_job_logs(job_id: int, repository: str | None = Query(default=None)):
    repo = _resolve_repo(repository)
    try:
        logs = await gh.client.job_logs(repo, _positive(job_id, 'job_id'))
    except gh.GitHubError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return {'job_id': job_id, 'logs': logs}


@router.get('/releases')
async def github_releases(repository: str | None = Query(default=None),
                          per_page: int = Query(default=30),
                          page: int = Query(default=1)):
    return await _read(repository, 'releases', per_page=per_page, page=page)


@router.get('/tags')
async def github_tags(repository: str | None = Query(default=None),
                      per_page: int = Query(default=30),
                      page: int = Query(default=1)):
    return await _read(repository, 'tags', per_page=per_page, page=page)


@router.get('/labels')
async def github_labels(repository: str | None = Query(default=None),
                        per_page: int = Query(default=100),
                        page: int = Query(default=1)):
    return await _read(repository, 'labels', per_page=per_page, page=page)
