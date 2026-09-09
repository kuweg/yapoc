"""Check live and saved chat alignment against a local, simulated SSE response.

Run: poetry run python scripts/check_chat_column_browser.py --dist /tmp/yapoc-chat-build
No real agents or provider calls are used.
"""
import argparse
import asyncio
import functools
import json
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.async_api import async_playwright, expect


async def check(dist):
    from app.backend.routers.models import list_models
    model_catalog = (await list_models()).model_dump()
    finish = threading.Event()
    more = threading.Event()
    report = threading.Event()

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path != '/api/task/stream':
                self.send_error(404)
                return
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()

            def emit(event):
                self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
                self.wfile.flush()

            emit({'type': 'text', 'text': 'I am checking the workspace files and their available actions.'})
            for _ in range(2):
                emit({'type': 'tool_start', 'name': 'file_read', 'input': {'path': 'example.md'}})
                emit({'type': 'tool_done', 'name': 'file_read', 'result': 'Example file contents.'})
            emit({'type': 'text', 'text': '\n\nThe files are ready for review.'})
            more.wait(20)
            emit({'type': 'thinking', 'text': 'Checking the remaining file metadata. ' * 20})
            report.wait(20)
            emit({'type': 'usage_stats', 'input_tokens': 1000, 'output_tokens': 120, 'tokens_per_second': 30, 'context_window': 100000})
            finish.wait(20)
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(dist)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(viewport={'width': 2048, 'height': 1152}, reduced_motion='reduce')
            await context.add_init_script('localStorage.setItem("yapoc-voice-settings", JSON.stringify({state:{voiceEnabled:false,voiceAutoSpeak:false},version:0}))')

            async def api(route):
                path = route.request.url.split('/api/')[-1]
                if path == 'task/stream':
                    await route.continue_()
                    return
                fixtures = {'auth/status': {'authenticated': True, 'configured': False},
                            'health': {'status': 'ok'}, 'ping': {'status': 'ok'}, 'tasks': [],
                            'models': model_catalog,
                            'agents': [{'name': 'master', 'status': 'idle', 'model': 'deepseek-v4-pro',
                                        'adapter': 'deepseek', 'memory_entries': 0, 'health_errors': 0,
                                        'has_task': False}]}
                await route.fulfill(status=200 if path in fixtures else 404, json=fixtures.get(path, {}))

            await context.route('**/api/**', api)
            await context.route_web_socket('**/ws**', lambda ws: ws.on_message(lambda message: None))
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(f'http://127.0.0.1:{server.server_port}')
            composer = page.get_by_role('textbox', name='Message YAPOC')
            await expect(page.get_by_label('Master model and usage')).to_be_visible()
            await expect(page.get_by_test_id('usage-output')).to_have_text('— out')
            await composer.fill('Check workspace actions')
            await composer.press('Enter')
            await expect(page.locator('.chat-history').get_by_text('The files are ready for review.', exact=False)).to_be_visible()
            live_turn = page.locator('.chat-history > .space-y-1')
            await expect(live_turn).to_have_count(1)
            usage = page.get_by_test_id('live-usage')
            await expect(usage).to_have_attribute('data-estimated', 'true')
            await expect(page.get_by_test_id('usage-input')).to_have_text('— in')
            await expect(usage.get_by_text('Cost —')).to_be_visible()
            await page.wait_for_timeout(350)  # Allow the numeric display animation to settle.
            before = await page.get_by_test_id('usage-output').inner_text()
            more.set()
            await expect(page.get_by_test_id('usage-output')).not_to_have_text(before)

            async def aligned():
                result = await page.evaluate('''() => {
                  const c = document.querySelector('.studio-composer-controls').getBoundingClientRect();
                  const rows = [...document.querySelectorAll('.chat-history > *, .studio-composer > *, .studio-chat-usage > *')]
                    .filter(el => el.getBoundingClientRect().height > 0);
                  return {width:c.width, bad:rows.map(el => {
                    const r=el.getBoundingClientRect();
                    return {left:r.left, right:r.right, className:el.className};
                  }).filter(r => Math.abs(r.left-c.left)>2 || Math.abs(r.right-c.right)>2),
                    overflow:document.documentElement.scrollWidth>innerWidth};
                }''')
                assert result['width'] <= 861 and not result['bad'] and not result['overflow'], result

            for width in [2048, 1512, 977, 390]:
                await page.set_viewport_size({'width': width, 'height': 1152})
                await aligned()
            await page.set_viewport_size({'width': 2048, 'height': 1152})
            await page.screenshot(path='/tmp/yapoc-chat-column-streaming.png')
            await expect(live_turn).to_have_count(1)
            report.set()
            await expect(usage).to_have_attribute('data-estimated', 'false')
            await expect(page.get_by_test_id('usage-input')).to_have_text('1.0k in')
            await expect(page.get_by_test_id('usage-output')).to_have_text('120 out')
            await expect(usage.get_by_text('30 tok/s')).to_be_visible()
            await expect(page.get_by_test_id('usage-cost')).to_have_text('≈$0.0018')
            await expect(page.get_by_test_id('usage-cost')).to_have_attribute('title', re.compile('api-docs.deepseek.com'))
            finish.set()
            await expect(live_turn).to_have_count(0)
            await expect(page.get_by_label('Master model and usage')).to_be_visible()
            await expect(page.get_by_test_id('usage-output')).to_have_text('120 out')
            await aligned()
            await page.screenshot(path='/tmp/yapoc-master-usage-header.png')
            # A second request must retain the last reported input/context while streaming.
            more.clear()
            report.clear()
            finish.clear()
            await composer.fill('Check another file')
            await composer.press('Enter')
            await expect(live_turn).to_have_count(1)
            await expect(usage).to_have_attribute('data-estimated', 'true')
            await expect(page.get_by_test_id('usage-input')).to_have_text('≈1.0k in')
            await expect(page.get_by_test_id('usage-cost')).not_to_have_text('Cost —')
            await expect(page.get_by_test_id('usage-context')).to_be_visible()
            more.set()
            report.set()
            finish.set()
            await expect(live_turn).to_have_count(0)
            assert not errors, errors
            await browser.close()
            print('PASS: live text/thinking usage increases before provider counts, exact reconciliation, unknown pricing; chat column at 2048/1512/977/390; no browser errors')
    finally:
        finish.set()
        more.set()
        report.set()
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist', type=Path, required=True)
    asyncio.run(check(parser.parse_args().dist.resolve()))
