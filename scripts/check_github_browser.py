"""Verify GitHub navigation, repository browsing, and file views without credentials.

poetry run python scripts/check_github_browser.py --dist app/frontend/dist
"""
import argparse
import asyncio
import socket
import threading
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI
from playwright.async_api import async_playwright, expect

from app.backend.dashboard import mount_dashboard
from app.backend.routers import github


async def check(dist):
    state = {'enabled': True, 'repositories': ['example/fork'], 'connection': 'not_checked',
             'last_successful_check': None, 'write_enabled': False, 'mcp_enabled': False, 'summary': None}
    checks = []
    async def health_summary(repository=None):
        checks.append(True)
        state.update(connection='connected', last_successful_check='2026-09-09T12:00:00Z',
                     summary={'message': 'example/fork: 1 failed run; 2 open PRs; 3 open issues (sampled).',
                              'stale_issues': 1, 'stale_pull_requests': 0})
    github.gh.status = lambda: dict(state)
    github.gh.health_summary = health_summary
    github._last_attempt = 0
    app = FastAPI()
    app.include_router(github.router)
    mount_dashboard(app, dist)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    address = f'http://127.0.0.1:{listener.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off'))
    worker = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    worker.start()
    unavailable = False
    errors = []
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            async def api(route):
                path = urlsplit(route.request.url).path
                if path.startswith('/api/integrations/github'):
                    if unavailable:
                        await route.fulfill(status=503, json={'error': 'unavailable'})
                    elif path == '/api/integrations/github/repo':
                        await route.fulfill(json={
                            'full_name': 'example/fork', 'name': 'fork', 'description': 'Example repository',
                            'html_url': 'https://github.com/example/fork', 'default_branch': 'main',
                            'open_issues_count': 3, 'stargazers_count': 4, 'forks_count': 1,
                            'language': 'TypeScript', 'pushed_at': '2026-09-09T12:00:00Z',
                            'updated_at': '2026-09-09T12:00:00Z', 'private': False,
                        })
                    elif path == '/api/integrations/github/branches':
                        await route.fulfill(json=[
                            {'name': 'main', 'commit': {'sha': 'abc1234', 'url': ''}, 'protected': True},
                            {'name': 'feature/files', 'commit': {'sha': 'def5678', 'url': ''}, 'protected': False},
                        ])
                    elif path == '/api/integrations/github/tree':
                        await route.fulfill(json={'sha': 'abc1234', 'truncated': False, 'tree': [
                            {'path': 'README.md', 'type': 'blob', 'sha': 'readme1', 'size': 150},
                            {'path': 'package.json', 'type': 'blob', 'sha': 'pkg1', 'size': 82},
                            {'path': 'src', 'type': 'tree', 'sha': 'src1'},
                            {'path': 'src/components', 'type': 'tree', 'sha': 'cmp1'},
                            {'path': 'src/components/App.tsx', 'type': 'blob', 'sha': 'app1', 'size': 117},
                            {'path': 'src/main.ts', 'type': 'blob', 'sha': 'main1', 'size': 94},
                        ]})
                    elif path == '/api/integrations/github/contents':
                        requested = dict(item.split('=', 1) for item in urlsplit(route.request.url).query.split('&')).get('path', '')
                        if requested == 'README.md':
                            await route.fulfill(json={'path': 'README.md', 'name': 'README.md', 'sha': 'readme1',
                                                      'size': 150, 'type': 'file', 'content': '# Example fork\n\nRepository documentation.\n\n| Feature | Status |\n| --- | --- |\n| Browser | Ready |'})
                        else:
                            await route.fulfill(json={'path': 'src/main.ts', 'name': 'main.ts', 'sha': 'main1',
                                                      'size': 94, 'type': 'file', 'content': "import { start } from './app'\n\nconst repository = 'example/fork'\nstart(repository)\n"})
                    else:
                        await route.continue_()
                    return
                fixtures = {'/api/auth/status': {'authenticated': True, 'configured': False},
                            '/api/health': {'status': 'ok'}, '/api/ping': {'status': 'ok'}, '/api/agents': [],
                            '/api/tasks': [], '/api/plugins': {'plugins': []}, '/api/mcp-servers/servers': {'servers': []}}
                await route.fulfill(status=200 if path in fixtures else 404, json=fixtures.get(path, {}))
            await context.route('**/api/**', api)
            await context.route_web_socket('**/ws**', lambda ws: ws.on_message(lambda message: None))
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(address)
            nav = page.get_by_role('button', name='GitHub', exact=True)
            await nav.click()
            await expect(nav).to_have_attribute('aria-current', 'page')
            await expect(page.get_by_role('heading', name='GitHub', exact=True)).to_be_visible()
            panel = page.get_by_role('region', name='GitHub integration')
            await expect(panel).to_contain_text('example/fork')
            checks_before = len(checks)
            await page.get_by_role('button', name='Check GitHub', exact=True).click()
            await expect(panel).to_contain_text('1 failed run')
            assert len(checks) == checks_before + 1
            views = page.get_by_role('navigation', name='GitHub views')
            await views.get_by_role('button', name='Code', exact=True).click()
            browser_panel = page.get_by_role('region', name='Repository code browser')
            await expect(browser_panel.get_by_role('button', name='src', exact=True)).to_be_visible()
            await expect(browser_panel.get_by_role('button', name='README.md', exact=True)).to_be_visible()
            await expect(page.get_by_role('region', name='README.md rendered')).to_contain_text('Example fork')
            await browser_panel.get_by_role('button', name='src', exact=True).click()
            await expect(browser_panel.get_by_role('button', name='components', exact=True)).to_be_visible()
            await browser_panel.get_by_role('button', name='main.ts', exact=True).click()
            file_viewer = page.get_by_role('region', name='Repository file viewer')
            await expect(file_viewer).to_contain_text('main.ts')
            await expect(file_viewer.get_by_label('Rendered source')).to_be_visible()
            await file_viewer.get_by_role('button', name='Raw', exact=True).click()
            await expect(file_viewer.get_by_label('Raw file')).to_contain_text("const repository = 'example/fork'")
            await file_viewer.get_by_role('button', name='Split', exact=True).click()
            await expect(file_viewer.get_by_label('Rendered source')).to_be_visible()
            await expect(file_viewer.get_by_label('Raw file')).to_be_visible()
            await page.screenshot(path='/tmp/yapoc-github-desktop.png')
            await page.set_viewport_size({'width': 390, 'height': 844})
            if await page.get_by_role('button', name='Close navigation', exact=True).is_visible():
                await page.get_by_role('button', name='Close navigation', exact=True).click()
            await page.get_by_role('button', name='Toggle navigation', exact=True).click()
            await page.get_by_role('button', name='Conversation', exact=True).click()
            await page.get_by_role('button', name='Toggle navigation', exact=True).click()
            await nav.click()
            await expect(page.get_by_role('heading', name='GitHub', exact=True)).to_be_visible()
            await views.get_by_role('button', name='Code', exact=True).click()
            await expect(page.get_by_role('region', name='Repository code browser')).to_be_visible()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.screenshot(path='/tmp/yapoc-github-mobile.png')
            # Reopening the tab loads fresh status; errors can be retried in place.
            unavailable = True
            await page.get_by_role('button', name='Toggle navigation', exact=True).click()
            await page.get_by_role('button', name='Conversation', exact=True).click()
            await page.get_by_role('button', name='Toggle navigation', exact=True).click()
            await nav.click()
            await expect(page.get_by_role('status').filter(has_text='GitHub integration status unavailable')).to_be_visible()
            unavailable = False
            await page.get_by_role('button', name='Retry connection', exact=True).click()
            await expect(panel).to_contain_text('connected')
            assert not errors, errors
            await browser.close()
            print('PASS: desktop/mobile GitHub navigation, folder browsing, rendered/raw/split file views, health check, and retry')
    finally:
        server.should_exit = True
        worker.join(timeout=5)
        listener.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist', type=Path, required=True)
    asyncio.run(check(parser.parse_args().dist.resolve()))
