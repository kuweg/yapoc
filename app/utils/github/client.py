from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

import httpx
from loguru import logger

from app.config import settings


class GitHubError(Exception):
    """Only fixed, non-secret messages cross this boundary."""


_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_][A-Za-z0-9_.-]*\Z")
_TOKEN = re.compile(r"(?:github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9_]+)")


def redact(value):
    if isinstance(value, str):
        secret = settings.github_token.get_secret_value()
        if secret:
            for variant in (secret, quote(secret, safe=''), base64.b64encode(secret.encode()).decode()):
                value = value.replace(variant, '[REDACTED]')
        return _TOKEN.sub('[REDACTED]', value)
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, dict):
        return {redact(str(k)): redact(v) for k, v in value.items()}
    return value


def compact(value):
    return json.dumps(redact(value), separators=(',', ':'), ensure_ascii=False)


def allowed_repos():
    repos = {r.strip().lower() for r in settings.github_allowed_repos.split(',') if r.strip()}
    if not repos or any(not _REPO.fullmatch(r) or r.split('/')[1] in ('.', '..') for r in repos):
        raise GitHubError('Configure a valid GITHUB_ALLOWED_REPOS allowlist.')
    return repos


def repository(repo=None):
    if not settings.github_enabled:
        raise GitHubError('GitHub integration is disabled.')
    if not settings.github_token:
        raise GitHubError('GitHub credentials are not configured.')
    default = f'{settings.github_default_owner}/{settings.github_default_repo}'
    repo = repo or settings.github_self_repo or default
    if not isinstance(repo, str) or not _REPO.fullmatch(repo) or repo.lower() not in allowed_repos():
        raise GitHubError('Repository is invalid or is not allowed.')
    return repo.lower()


def validate_config():
    repo = repository()
    if bool(settings.github_default_owner) != bool(settings.github_default_repo):
        raise GitHubError('Configure both default owner and repository.')
    if settings.github_default_owner:
        repository(f'{settings.github_default_owner}/{settings.github_default_repo}')
    return repo


class GitHubClient:
    def __init__(self, transport=None):
        self.transport = transport
        from app.utils.github.logging import install_filter
        install_filter()

    async def request(self, repo, suffix='', *, method='GET', params=None, payload=None, text=False, search=False):
        repo = repository(repo)
        if method != 'GET' and not settings.github_write_enabled:
            raise GitHubError('GitHub writes are disabled.')
        path = '/search/code' if search else f'/repos/{repo}{suffix}'
        try:
            async with httpx.AsyncClient(
                base_url='https://api.github.com', timeout=20, follow_redirects=False,
                transport=self.transport,
                headers={'Authorization': f'Bearer {settings.github_token.get_secret_value()}',
                         'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'},
            ) as client:
                async with client.stream(method, path, params=params, json=payload) as response:
                    if response.status_code == 429 or (response.status_code == 403 and (
                        response.headers.get('x-ratelimit-remaining') == '0' or 'retry-after' in response.headers
                    )):
                        raise GitHubError('GitHub rate limit reached; retry later.')
                    errors = {401: 'GitHub authentication failed.', 403: 'GitHub permission denied.',
                              404: 'GitHub resource unavailable or permission denied.'}
                    if response.status_code >= 300:
                        raise GitHubError(errors.get(response.status_code, 'GitHub request failed.'))
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 2_000_000:
                            raise GitHubError('GitHub response exceeds the size limit; narrow the request.')
                    if text:
                        return redact(data.decode('utf-8', errors='replace'))
                    return redact(json.loads(data)) if data else {}
        except (httpx.HTTPError, ValueError, UnicodeError):
            raise GitHubError('GitHub connection failed or returned an invalid response.') from None

    async def job_logs(self, repo, job_id):
        repo = repository(repo)
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False, transport=self.transport) as http:
                response = await http.get(
                    f'https://api.github.com/repos/{repo}/actions/jobs/{job_id}/logs',
                    headers={'Authorization': f'Bearer {settings.github_token.get_secret_value()}'},
                )
                if response.status_code != 302:
                    raise GitHubError('GitHub job logs unavailable; check Actions permissions or log retention.')
                location = response.headers.get('location', '')
                url = urlsplit(location)
                if (url.scheme != 'https' or url.username or url.password or url.port not in (None, 443)
                    or not url.hostname or not url.hostname.endswith(('.blob.core.windows.net', '.actions.githubusercontent.com'))):
                    raise GitHubError('GitHub log download destination refused.')
                # Signed storage request has NO GitHub credentials and cannot redirect.
                async with http.stream('GET', location) as logs:
                    if logs.status_code != 200:
                        raise GitHubError('GitHub job logs unavailable.')
                    data = bytearray()
                    async for chunk in logs.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 200000:
                            break
                    return redact(data[:200000].decode('utf-8', errors='replace'))
        except (httpx.HTTPError, ValueError):
            raise GitHubError('GitHub job log download failed.') from None


client = GitHubClient()


def audit(action, repo, target, outcome):
    logger.info('github_audit {}', compact({'action': action, 'repository': repo,
                                          'target_id': target, 'outcome': outcome}))


last_summary = None
last_success = None
connection = 'not_checked'


def status():
    error = None
    try:
        repo = validate_config()
        repos = sorted(allowed_repos())
    except GitHubError as exc:
        repo, repos, error = None, [], str(exc)
    return redact({'enabled': settings.github_enabled, 'repository': repo, 'repositories': repos,
                   'write_enabled': settings.github_write_enabled, 'connection': error or connection,
                   'last_successful_check': last_success, 'summary': last_summary,
                   'mcp_enabled': settings.github_mcp_enabled})


async def health_summary(repo=None, stale_days=30, head_sha=None):
    global last_summary, last_success, connection
    repo = repository(repo)
    try:
        runs = await client.request(repo, '/actions/runs', params={'per_page': 30, **({'head_sha': head_sha} if head_sha else {})})
        issues = await client.request(repo, '/issues', params={'state': 'open', 'per_page': 100})
        prs = await client.request(repo, '/pulls', params={'state': 'open', 'per_page': 100})
        now = datetime.now(timezone.utc)
        def stale(item):
            try:
                return (now - datetime.fromisoformat(item['updated_at'].replace('Z', '+00:00'))).days >= stale_days
            except (KeyError, ValueError, TypeError):
                return False
        issues = [i for i in issues if 'pull_request' not in i]
        failed = [{'id': r['id'], 'name': r.get('name'), 'conclusion': r.get('conclusion'),
                   'head_sha': r.get('head_sha'), 'url': r.get('html_url'), 'updated_at': r.get('updated_at')}
                  for r in runs.get('workflow_runs', []) if r.get('conclusion') in ('failure', 'timed_out', 'action_required')]
        labels = {}
        for issue in issues:
            for label in issue.get('labels', []):
                name = label.get('name', '')
                labels[name] = labels.get(name, 0) + 1
        pr_health = []
        for pr in prs[:5]:
            detail = {'number': pr['number'], 'draft': pr.get('draft', False)}
            try:
                sha = quote(pr['head']['sha'], safe='')
                checks = await client.request(repo, f'/commits/{sha}/check-runs', params={'per_page': 100})
                reviews = await client.request(repo, f'/pulls/{pr["number"]}/reviews', params={'per_page': 100})
                detail['blocked_checks'] = [c.get('name') for c in checks.get('check_runs', [])
                                            if c.get('status') != 'completed' or c.get('conclusion') not in ('success', 'neutral', 'skipped')]
                latest = {}
                for review in reviews:
                    if review.get('state') != 'COMMENTED':
                        latest[review.get('user', {}).get('login', '')] = review.get('state')
                detail['review_states'] = list(latest.values())
            except (GitHubError, KeyError, TypeError):
                detail['inspection'] = 'unavailable'
            pr_health.append(detail)
        for run in failed[:3]:
            try:
                jobs = await client.request(repo, f'/actions/runs/{run["id"]}/jobs', params={'per_page': 100})
                run['failed_steps'] = [step.get('name') for job in jobs.get('jobs', [])
                                       for step in job.get('steps', []) if step.get('conclusion') == 'failure']
                run['likely_cause'] = 'Inspect failed steps: ' + ', '.join(run['failed_steps']) if run['failed_steps'] else 'No cause inferred; inspect job logs.'
            except GitHubError:
                run['likely_cause'] = 'Job details unavailable.'
        created_recently = 0
        for item in issues:
            try:
                created_recently += (now - datetime.fromisoformat(item['created_at'].replace('Z', '+00:00'))).days < 7
            except (KeyError, ValueError, TypeError):
                pass
        summary = {'repository': repo, 'sampled': True, 'sample_limits': {'runs': 30, 'issues': 100, 'pull_requests': 100},
                   'open_issues': len(issues), 'open_pull_requests': len(prs),
                   'stale_issues': sum(map(stale, issues)), 'stale_pull_requests': sum(map(stale, prs)),
                   'issue_labels': labels, 'open_issues_created_last_7_days': created_recently,
                   'pull_request_health': pr_health, 'inspected_pr_limit': 5, 'failed_runs': failed,
                   'message': f'{repo}: {len(failed)} failed runs; {len(prs)} open PRs; {len(issues)} open issues (sampled).'}
        connection = 'connected'
        if repo == repository():
            last_success, last_summary = now.isoformat(), redact(summary)
        return summary
    except (GitHubError, KeyError, TypeError, AttributeError):
        connection = 'check_failed'
        raise GitHubError('GitHub health check failed; inspect permissions or retry later.') from None
