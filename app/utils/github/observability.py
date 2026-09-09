"""Optional scheduler hook. Emits only changed, compact health signals."""
import asyncio
from loguru import logger
from app.utils.github import client as gh

_last_signal = None
_lock = asyncio.Lock()


async def check_health():
    global _last_signal
    if _lock.locked():
        return
    async with _lock:
        try:
            summary = await asyncio.wait_for(gh.health_summary(), timeout=90)
            signal = gh.compact({'repository': summary['repository'], 'failed_runs': [r['id'] for r in summary['failed_runs']],
                                 'stale_issues': summary['stale_issues'], 'stale_pull_requests': summary['stale_pull_requests']})
        except (gh.GitHubError, TimeoutError):
            signal = 'GitHub health check unavailable.'
        if signal != _last_signal:
            logger.info('github_health {}', signal)
            _last_signal = signal
