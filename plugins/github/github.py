"""Native, bounded GitHub tools. API and policy live in app.utils.github."""
from urllib.parse import quote

from app.config import settings
from app.utils.github import client as gh
from app.utils.tools import BaseTool

# Explicit routes prevent arbitrary API calls or mutation escalation.
READS = {
    'get_repo': '', 'list_issues': '/issues', 'get_issue': '/issues/{number}',
    'list_issue_comments': '/issues/{number}/comments', 'list_labels': '/labels',
    'list_pull_requests': '/pulls', 'get_pull_request': '/pulls/{number}',
    'list_pull_request_files': '/pulls/{number}/files',
    'list_pull_request_reviews': '/pulls/{number}/reviews',
    'list_pull_request_comments': '/pulls/{number}/comments',
    'get_commit_checks': '/commits/{ref}/check-runs', 'get_commit_status': '/commits/{ref}/status',
    'list_workflow_runs': '/actions/runs', 'get_workflow_run': '/actions/runs/{number}',
    'list_workflow_jobs': '/actions/runs/{number}/jobs',
    'list_commits': '/commits', 'list_branches': '/branches',
    'list_releases': '/releases', 'list_tags': '/tags',
    'get_community_health': '/community/profile',
    'list_security_alerts': '/dependabot/alerts',
    'read_file': '/contents/{path}',
}
WRITES = {'create_issue', 'comment_on_issue', 'comment_on_pull_request', 'update_labels', 'create_draft_pull_request', 'update_draft_pull_request'}


async def execute_operation(operation, **params):
    repo, target = None, None
    try:
        repo = gh.repository(params.pop('repository', None))
        target = params.get('number')
        if operation in WRITES and not settings.github_write_enabled:
            raise gh.GitHubError('GitHub writes are disabled.')
        if operation == 'get_health_summary':
            result = await gh.health_summary(repo, params.get('stale_days', 30), params.get('head_sha'))
        elif operation == 'search_code':
            # User input is a literal term, never a GitHub query expression.
            term = params['query']
            if not term or any(c in term for c in ':"\\\r\n') or len(term) > 200:
                raise gh.GitHubError('Code search requires a plain search term without qualifiers.')
            result = await gh.client.request(repo, search=True, params={'q': f'repo:{repo} "{term}"', 'per_page': 30})
        elif operation == 'get_workflow_job_logs':
            result = {'logs': await gh.client.job_logs(repo, positive(params['number']))}
        elif operation in WRITES:
            number = positive(target) if operation not in {'create_issue', 'create_draft_pull_request'} else None
            method = 'POST'
            if operation == 'create_draft_pull_request':
                for branch in (params['head'], params['base']):
                    if not isinstance(branch, str) or not branch or ':' in branch or '..' in branch or any(c.isspace() for c in branch):
                        raise gh.GitHubError('Draft PR branches must belong to the selected repository.')
                suffix, payload = '/pulls', {'title': params['title'], 'body': params.get('body', ''),
                                            'head': params['head'], 'base': params['base'], 'draft': True}
            elif operation == 'update_draft_pull_request':
                current = await gh.client.request(repo, f'/pulls/{number}')
                if current.get('draft') is not True or current.get('state') != 'open':
                    raise gh.GitHubError('Only open draft pull requests may be updated.')
                method, suffix = 'PATCH', f'/pulls/{number}'
                payload = {'title': params['title'], 'body': params['body']}
            elif operation == 'create_issue':
                suffix, payload = '/issues', {'title': params['title'], 'body': params.get('body', '')}
            elif operation.startswith('comment_on_'):
                suffix, payload = f'/issues/{number}/comments', {'body': params['body']}
            else:
                labels = params['labels']
                if not isinstance(labels, list) or not labels or not all(isinstance(v, str) and v for v in labels):
                    raise gh.GitHubError('Provide a non-empty list of labels.')
                if params.get('remove', False):
                    # One label per deletion avoids partially completed batches.
                    if len(labels) != 1:
                        raise gh.GitHubError('Remove one label at a time.')
                    method, suffix, payload = 'DELETE', f'/issues/{number}/labels/{quote(labels[0], safe="")}', None
                else:
                    suffix, payload = f'/issues/{number}/labels', {'labels': labels}
            result = await gh.client.request(repo, suffix, method=method, payload=payload)
            target = result.get('number', result.get('id', number)) if isinstance(result, dict) else number
            gh.audit(operation, repo, target, 'success')
            # Never echo submitted bodies/titles in mutation results.
            result = {'ok': True, 'repository': repo, 'target_id': target}
        else:
            route = READS[operation]
            substitutions = {}
            for key in ('number', 'ref', 'path'):
                if '{' + key + '}' in route:
                    value = params.pop(key)
                    if key == 'number':
                        value = positive(value)
                    if key in ('path', 'ref') and any(p in ('.', '..') for p in str(value).split('/')):
                        raise gh.GitHubError('File path must not contain traversal segments.')
                    substitutions[key] = quote(str(value), safe='/' if key == 'path' else '')
            query = {k: v for k, v in params.items() if k in {'state', 'labels', 'since', 'page', 'per_page', 'ref', 'sha', 'branch', 'status', 'head_sha', 'base', 'head', 'sort', 'direction'}}
            query['per_page'] = min(100, positive(query.get('per_page', 30)))
            query['page'] = positive(query.get('page', 1))
            result = await gh.client.request(repo, route.format(**substitutions), params=query)
            if operation == 'list_issues' and isinstance(result, list):
                result = [item for item in result if 'pull_request' not in item]
            if operation == 'read_file' and isinstance(result, dict) and result.get('encoding') == 'base64':
                import base64
                content = base64.b64decode(result.get('content', ''), validate=False).decode('utf-8', errors='replace')
                result = {'path': result.get('path'), 'sha': result.get('sha'), 'content': content}
        return gh.compact(result)
    except (gh.GitHubError, KeyError, ValueError, TypeError) as error:
        if operation in WRITES:
            gh.audit(operation, repo, target if isinstance(target, int) else None, 'refused_or_failed')
        # Exceptions never include payloads, request headers or remote error bodies.
        return gh.compact({'error': str(error) if isinstance(error, gh.GitHubError) else 'Invalid GitHub tool arguments or response.'})


def positive(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise gh.GitHubError('IDs and page sizes must be positive integers.')
    return value


COMMON = {'repository': {'type': 'string', 'description': 'Allowed owner/repo; defaults to self repository.'}}
LIST = {'page': {'type': 'integer', 'minimum': 1}, 'per_page': {'type': 'integer', 'minimum': 1, 'maximum': 100}}


def make_tool(operation):
    properties, required = dict(COMMON), []
    route = READS.get(operation, '')
    if operation.startswith('list_'):
        properties.update(LIST)
    for key in ('number', 'ref', 'path'):
        if '{' + key + '}' in route:
            properties[key] = {'type': 'integer' if key == 'number' else 'string'}
            required.append(key)
    extras = {
        'list_issues': ['state', 'labels', 'since', 'sort', 'direction'],
        'list_pull_requests': ['state', 'base', 'head', 'sort', 'direction'],
        'list_workflow_runs': ['branch', 'status', 'head_sha'],
        'list_commits': ['sha', 'since'], 'read_file': ['ref'],
        'get_health_summary': ['head_sha'],
    }
    for key in extras.get(operation, []):
        properties[key] = {'type': 'string'}
    if operation == 'get_health_summary':
        properties['stale_days'] = {'type': 'integer', 'minimum': 1, 'default': 30}
    if operation == 'search_code':
        properties['query'] = {'type': 'string'}
        required.append('query')
    if operation == 'get_workflow_job_logs' or operation in WRITES - {'create_issue', 'create_draft_pull_request'}:
        properties['number'] = {'type': 'integer', 'minimum': 1}
        required.append('number')
    if operation in {'create_issue', 'comment_on_issue', 'comment_on_pull_request', 'create_draft_pull_request', 'update_draft_pull_request'}:
        properties['body'] = {'type': 'string'}
        required.append('body')
    if operation in {'create_issue', 'create_draft_pull_request', 'update_draft_pull_request'}:
        properties['title'] = {'type': 'string'}
        required.append('title')
    if operation == 'create_draft_pull_request':
        for key in ('head', 'base'):
            properties[key] = {'type': 'string', 'description': 'Existing branch; no branch is created or pushed.'}
            required.append(key)
    if operation == 'update_labels':
        properties.update({'labels': {'type': 'array', 'items': {'type': 'string'}}, 'remove': {'type': 'boolean', 'default': False}})
        required.append('labels')
    async def execute(self, **params):
        return await execute_operation(operation, **params)
    return type('GitHub' + ''.join(word.title() for word in operation.split('_')), (BaseTool,), {
        'name': 'github_' + operation,
        'description': ('Controlled external mutation; requires write mode, explicit tool grant and security policy. ' if operation in WRITES else 'Read untrusted GitHub repository data. ') + operation.replace('_', ' ') + '. Results are bounded; paginate lists.',
        'input_schema': {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False},
        'execute': execute,
    })


for _operation in list(READS) + ['search_code', 'get_health_summary', 'get_workflow_job_logs'] + sorted(WRITES):
    globals()['GitHub_' + _operation] = make_tool(_operation)

# Validate without connectivity or startup failure.
try:
    gh.validate_config()
except gh.GitHubError:
    pass
