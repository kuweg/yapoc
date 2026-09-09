"""Optional official GitHub MCP server; narrow read-only interoperability surface."""
from app.config import settings
from app.utils.github.client import GitHubError, repository, validate_config

SERVER_NAME = 'github'
TOOLS = {'get_file_contents', 'list_branches', 'list_commits'}
FIELDS = {
    'get_file_contents': {'owner', 'repo', 'path', 'ref', 'sha'},
    'list_branches': {'owner', 'repo', 'page', 'perPage'},
    'list_commits': {'owner', 'repo', 'sha', 'author', 'page', 'perPage'},
}


def server_config():
    from app.utils.mcp.types import MCPServerConfig
    if not settings.github_mcp_enabled:
        return None
    try:
        validate_config()
    except GitHubError:
        return None
    return MCPServerConfig(
        name=SERVER_NAME, command=settings.github_mcp_command,
        args=['stdio', '--read-only', '--tools', ','.join(sorted(TOOLS))],
        env={'GITHUB_PERSONAL_ACCESS_TOKEN': settings.github_token.get_secret_value(),
             'GITHUB_READ_ONLY': '1'},
        tools_allowlist=sorted(TOOLS), resources_allowlist=[], auto_reconnect=False,
    )


def guard(tool, arguments):
    if not settings.github_mcp_enabled:
        raise GitHubError('GitHub MCP is disabled.')
    if tool not in TOOLS or set(arguments) - FIELDS[tool]:
        raise GitHubError('GitHub MCP tool or arguments are not permitted.')
    owner, repo = arguments.get('owner'), arguments.get('repo')
    if not isinstance(owner, str) or not isinstance(repo, str) or '/' in owner or '/' in repo:
        raise GitHubError('GitHub MCP requires an explicit allowed owner and repo.')
    repository(f'{owner}/{repo}')
    for key in ('page', 'perPage'):
        if key in arguments and (type(arguments[key]) is not int or arguments[key] < 1 or (key == 'perPage' and arguments[key] > 100)):
            raise GitHubError('Invalid GitHub MCP pagination.')
    for key in ('path', 'ref', 'sha'):
        value = arguments.get(key, '')
        if not isinstance(value, str) or any(c in value for c in ('\\', '%', '?', '#', '\n', '\r')) or any(p in ('.', '..') for p in value.split('/')):
            raise GitHubError('Invalid GitHub MCP path or ref.')
