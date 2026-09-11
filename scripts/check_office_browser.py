"""Exercise the agent building with independent resident states and mobile layout."""
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
    agents = [dict(name=name, office_role=role, runtime_state=state, status=state,
                   process_state=state, state=state, model='fixture', has_task=True,
                   memory_entries=0, health_errors=0, task_summary='Build the preview', pid=123, adapter='openai', health='ok', started_at=None, updated_at=None, idle_since=None, last_memory_entry=None, tokens_per_second=None, input_tokens=None, output_tokens=None)
              for name, role, state in [('master', 'master', 'idle'), ('builder_a', 'builder', 'running'),
                                        ('builder_b', 'builder', 'waiting'), ('keeper', 'keeper', 'error')]]
    errors = []
    disconnected = False
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            page.on('pageerror', lambda e: (errors.append(str(e)), print(str(e), flush=True)))
            async def api(route):
                path = urlsplit(route.request.url).path
                if path == '/api/agents':
                    await route.fulfill(status=503 if disconnected else 200, json=[] if disconnected else agents)
                    return
                data = {'/api/auth/status': {'authenticated': True, 'configured': False}, '/api/tasks': [],
                        '/api/health': {'status': 'ok'}, '/api/ping': {'status': 'ok'}, '/api/agents/active-times': {'agents': []}}
                await route.fulfill(status=200 if path in data else 404, json=data.get(path, {}))
            await page.route('**/api/**', api)
            await page.route_web_socket('**/ws**', lambda ws: ws.on_message(lambda _: None))
            await page.goto(f'http://127.0.0.1:{listener.getsockname()[1]}')
            floor = page.get_by_role('region', name='builder floor', exact=True)
            await expect(floor.locator('.office-resident')).to_have_count(2)
            await expect(floor.get_by_role('button', name='builder_a: Working. Open agent flow')).to_be_visible()
            await expect(floor.get_by_role('button', name='builder_b: Waiting. Open agent flow')).to_be_visible()
            assert await floor.locator('.office-arm').first.evaluate("e => getComputedStyle(e).animationName") == 'none'
            await page.emulate_media(reduced_motion='no-preference')
            assert await floor.locator('.is-working .office-arm').evaluate("e => getComputedStyle(e).animationName") == 'office-type'
            await page.emulate_media(reduced_motion='reduce')
            await page.screenshot(path='/tmp/yapoc-office-desktop.png')
            agents[1]['runtime_state'] = 'idle'
            await expect(floor.get_by_role('button', name='builder_a: Idle. Open agent flow')).to_be_visible(timeout=10000)
            await floor.get_by_role('button', expanded=True).click()
            await expect(floor.locator('.office-resident')).to_have_count(0)
            await floor.get_by_role('button', expanded=False).click()
            await floor.get_by_role('button', name='builder_a: Idle. Open agent flow').click()
            await expect(page.get_by_role('region', name='Conversation inspector')).to_contain_text('builder_a flow')
            await page.get_by_role('button', name='Close builder_a flow', exact=True).first.click()
            await page.get_by_role('button', name='List', exact=True).click()
            await page.reload()
            await expect(page.get_by_role('button', name='List', exact=True)).to_have_attribute('aria-pressed', 'true')
            await page.get_by_role('button', name='Building', exact=True).click()
            await page.set_viewport_size({'width': 390, 'height': 844})
            close = page.get_by_role('button', name='Close navigation', exact=True)
            if await close.is_visible(): await close.click()
            await expect(floor).to_be_visible()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.screenshot(path='/tmp/yapoc-office-mobile.png')
            disconnected = True
            await expect(floor.get_by_role('button', name='builder_a: Status unavailable. Open agent flow')).to_be_visible(timeout=10000)
            await floor.get_by_role('button', name='builder_a: Status unavailable. Open agent flow').click()
            await expect(page.get_by_role('region', name='Conversation inspector')).to_be_visible()
            await expect(page.get_by_role('complementary', name='Agent team')).not_to_be_visible()
            assert not errors, errors
            await browser.close()
    finally:
        server.should_exit = True; worker.join(timeout=5); listener.close()
    print('PASS: grouped residents, independent states, collapse, activity, persisted view, reduced motion, mobile, disconnect')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--dist', type=Path, required=True)
    asyncio.run(check(parser.parse_args().dist))
