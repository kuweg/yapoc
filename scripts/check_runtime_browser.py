"""Exercise shared progress and on-demand diagnostics at desktop/mobile widths."""
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


async def check(dist):
    app = FastAPI()
    mount_dashboard(app, dist)
    listener = socket.socket(); listener.bind(('127.0.0.1', 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off'))
    worker = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True); worker.start()
    address = f'http://127.0.0.1:{listener.getsockname()[1]}'
    timestamp = '2026-09-11T00:00:00Z'
    task = {'id': 'fixture', 'prompt': 'Build the requested change', 'status': 'done', 'session_id': 'fixture-session',
            'created_at': timestamp, 'progress': {'state': 'waiting', 'waiting_on': ['builder'],
            'last_activity_at': timestamp, 'last_activity': 'Finished wait_for_agent',
            'next_action': 'Delegated work continues; its result will return here.', 'recovery_count': 1}}
    report = {'runtime': {'boot_id': 'fixture', 'started_at': timestamp, 'restart_required': False},
              'network_enabled': True, 'workers': [], 'last_check': None}
    checks = []; errors = []
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            await context.add_init_script("localStorage.setItem('yapoc-sessions', JSON.stringify({state:{sessions:[{id:'fixture-session',name:'Test session',createdAt:'2026-09-11',history:[]}],activeId:'fixture-session'},version:0}))")
            async def api(route):
                path = urlsplit(route.request.url).path
                if path == '/api/health/runtime/check':
                    checks.append(True)
                    report['last_check'] = {'checked_at': timestamp, 'status': 'ok', 'checks': [
                        {'name': name, 'status': 'ok', 'detail': 'Probe succeeded.'} for name in ['dns', 'https', 'poetry', 'backend']]}
                    await route.fulfill(json=report); return
                fixtures = {'/api/auth/status': {'authenticated': True, 'configured': False},
                    '/api/health': {'status': 'ok'}, '/api/ping': {'status': 'ok'}, '/api/agents': [],
                    '/api/tasks': [dict(task, id='handoff', prompt="Original user request: Build the requested change You stopped waiting for 'builder' earlier and ended your turn; here is the result"), task], '/api/health/runtime': report,
                    '/api/plugins': {'plugins': []}, '/api/mcp-servers/servers': {'servers': []}}
                await route.fulfill(status=200 if path in fixtures else 404, json=fixtures.get(path, {}))
            await context.route('**/api/**', api)
            await context.route_web_socket('**/ws**', lambda ws: ws.on_message(lambda message: None))
            page = await context.new_page(); page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(address)
            progress = page.get_by_role('region', name='Task progress')
            await expect(progress).to_contain_text('Waiting for task results')
            await expect(progress).not_to_contain_text('wait_for_agent')
            assert (await progress.bounding_box())['height'] < 60
            await page.screenshot(path='/tmp/yapoc-progress-desktop.png')
            await progress.get_by_role('button').click()
            await expect(progress.get_by_text('Build the requested change', exact=True)).to_have_count(1)
            await expect(progress).not_to_contain_text('You stopped waiting')
            await page.set_viewport_size({'width': 390, 'height': 844})
            close = page.get_by_role('button', name='Close navigation', exact=True)
            if await close.is_visible():
                await close.click()
            assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            await page.get_by_role('button', name='Close agent team', exact=True).click()
            await expect(progress).to_be_visible()
            await page.screenshot(path='/tmp/yapoc-progress-mobile.png')
            await page.set_viewport_size({'width': 1440, 'height': 1000})
            task['progress']['state'] = 'unknown'
            await expect(progress).to_contain_text('Past task status unavailable', timeout=10000)
            await expect(progress).not_to_contain_text('Builder is working')
            task['progress']['state'] = 'completed'
            await expect(progress).to_have_count(0, timeout=10000)
            task['progress']['state'] = 'waiting'
            await page.get_by_role('button', name='Tasks', exact=True).click()
            await expect(page.get_by_test_id('task-progress').last).to_contain_text('waiting')
            await page.get_by_role('button', name='Observability', exact=True).click()
            diagnostics = page.get_by_role('region', name='Runtime diagnostics')
            await expect(diagnostics).to_contain_text('Diagnostics have not run since startup.')
            assert not checks
            await diagnostics.get_by_role('button', name='Run diagnostics').click()
            await expect(diagnostics).to_contain_text('https: ok')
            assert len(checks) == 1
            await page.screenshot(path='/tmp/yapoc-runtime-desktop.png')
            await page.set_viewport_size({'width': 390, 'height': 844})
            close = page.get_by_role('button', name='Close navigation', exact=True)
            if await close.is_visible():
                await close.click()
            await expect(diagnostics).to_be_visible()
            assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            await page.screenshot(path='/tmp/yapoc-runtime-mobile.png')
            assert not errors, errors
            await browser.close()
    finally:
        server.should_exit = True; worker.join(timeout=5); listener.close()
    print('Runtime diagnostics and task progress: desktop/mobile passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--dist', type=Path, required=True)
    asyncio.run(check(parser.parse_args().dist))
