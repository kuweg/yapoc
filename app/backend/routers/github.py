"""On-demand health; no GitHub requests during normal dashboard polling."""
import asyncio
import time

from fastapi import APIRouter
from app.utils.github import client as gh

router = APIRouter(prefix='/api/integrations/github', tags=['integrations'])
_lock = asyncio.Lock()
_last_attempt = 0.0


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
