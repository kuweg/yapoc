"""Inspector layout regression with an isolated browser and mocked backend.

Run after a frontend build:
  poetry run python scripts/check_inspector_layout_browser.py --dist /tmp/yapoc-inspector-build
No real agents, files, or integrations are changed.
"""
import argparse
import asyncio
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect


async def check(dist: Path):
    from app.backend.routers.models import list_models
    model_catalog = (await list_models()).model_dump()
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(dist)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    mutations = []
    sockets = []
    now = '2026-09-08T18:00:00Z'
    agents = [{'name': name, 'status': 'idle', 'model': 'example', 'adapter': 'example', 'memory_entries': 0,
        'health_errors': 0, 'has_task': False, 'process_state': 'idle', 'state': 'idle', 'pid': None,
        'task_summary': '', 'health': 'ok', 'started_at': None, 'updated_at': now, 'idle_since': None,
        'last_memory_entry': None, 'tokens_per_second': None, 'input_tokens': 0, 'output_tokens': 0}
        for name in ['master', 'builder']]

    async def api(route):
        path = urlsplit(route.request.url).path
        if route.request.method not in ['GET', 'HEAD']:
            mutations.append(path)
            await route.abort()
            return
        fixtures = {
            '/api/models': model_catalog,
            '/api/auth/status': {'authenticated': True, 'configured': False},
            '/api/health': {'status': 'ok'}, '/api/ping': {'status': 'ok'},
            '/api/agents': agents, '/api/tasks': [],
            '/api/agents/master/activity': {'events': [
                {'agent': 'master', 'timestamp': now, 'type': 'message_delta', 'text': 'I found the calendar renderer. The empty week view can use the same chat block pattern.'},
                {'agent': 'master', 'timestamp': now, 'type': 'tool_call', 'name': 'file_read', 'input': {'path': 'app/frontend/src/components/CalendarBlock.tsx'}},
                {'agent': 'master', 'timestamp': now, 'type': 'tool_result', 'name': 'file_read', 'result': 'Calendar component loaded.'},
            ]},
            '/api/plugins': {'plugins': []}, '/api/mcp-servers/servers': {'servers': []},
            '/api/artifacts': {'artifacts': [{'id': 'report', 'name': 'Example report.md', 'path': '/example/report.md',
                'kind': 'text', 'size': 300, 'version': 1, 'source_agent': 'builder', 'updated_at': now}]},
            '/api/upload': {'files': [{'id': 'upload', 'name': 'Example document.pdf', 'mime': 'application/pdf', 'size': 1234}]},
            '/api/files/preview': {'path': '/example/report.md', 'name': 'Example report.md', 'kind': 'text', 'ext': '.md', 'size': 300, 'content': 'A readable file preview.'},
        }
        if path in fixtures:
            await route.fulfill(json=fixtures[path])
        else:
            await route.fulfill(status=404, json={'detail': 'Not used by this layout scenario'})

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(viewport={'width': 1512, 'height': 982}, reduced_motion='reduce')
            await context.route('**/api/**', api)
            def websocket(ws):
                sockets.append(ws)
                ws.on_message(lambda message: None)
            await context.route_web_socket('**/ws**', websocket)
            saved = {'state': {'activeId': 'layout', 'sessions': [{'id': 'layout', 'name': 'Layout check', 'createdAt': now,
                'history': [{'role': 'user', 'content': 'Show me the calendar.'}, {'role': 'assistant', 'content': 'Your calendar has no events this week. The conversation should remain readable when inspecting agent activity or workspace files.'}]}]}, 'version': 2}
            await context.add_init_script('localStorage.setItem("yapoc-sessions", ' + json.dumps(json.dumps(saved)) + '); localStorage.setItem("yapoc-agentflow-width", "2000");')
            page = await context.new_page()
            page.on('pageerror', lambda error: (errors.append(str(error)), print('BROWSER ERROR:', error, flush=True)))
            await page.goto(f'http://127.0.0.1:{server.server_port}')
            composer = page.get_by_role('textbox', name='Message YAPOC')
            await composer.fill('Keep this draft while inspecting files')
            await page.locator('.studio-agent-card[data-agent="master"]').click()
            await page.get_by_role('button', name='Agent flow →', exact=True).click()
            await expect(page.get_by_role('tab', name='master flow', exact=True)).to_have_attribute('aria-selected', 'true')
            await expect(page.get_by_text('I found the calendar renderer.', exact=False)).to_be_visible()

            async def geometry():
                return await page.evaluate('''() => {
                  const chat = document.querySelector('.studio-conversation-content');
                  const dock = document.querySelector('.studio-inspector');
                  const main = document.querySelector('.studio-conversation-layout');
                  const c = chat.getBoundingClientRect(), d = dock.getBoundingClientRect(), m = main.getBoundingClientRect();
                  return {chatWidth:c.width, dockWidth:d.width, mainWidth:m.width, hidden:getComputedStyle(chat).visibility === 'hidden',
                    overlap:c.right > d.left + 1, contained:d.left >= m.left - 1 && d.right <= m.right + 1,
                    overflow:document.documentElement.scrollWidth > innerWidth};
                }''')

            async def assert_layout():
                g = await geometry()
                assert g['contained'] and not g['overflow'], g
                if g['mainWidth'] >= 800:
                    assert not g['hidden'] and g['chatWidth'] >= 439 and not g['overlap'], g
                    await expect(composer).to_be_visible()
                else:
                    assert g['hidden'] and abs(g['dockWidth'] - g['mainWidth']) < 2, g
                    await expect(page.get_by_role('button', name='Back to conversation')).to_be_visible()

            await assert_layout()  # Oversized persisted width must still leave readable chat.
            seam = page.get_by_role('separator', name='Resize inspector')
            await seam.focus()
            await page.keyboard.press('ArrowLeft')
            await assert_layout()
            await page.get_by_role('button', name='Artifacts', exact=True).click()
            await page.get_by_role('textbox', name='Filter artifacts').fill('Example')
            await page.get_by_role('button', name='Workspace files', exact=True).click()
            await expect(page.get_by_role('tab', name='Workspace files', exact=True)).to_have_attribute('aria-selected', 'true')
            await expect(page.get_by_role('complementary', name='Artifacts browser')).to_be_hidden()
            await expect(page.get_by_role('complementary', name='Workspace uploads')).to_be_visible()
            await assert_layout()
            await page.screenshot(path='/tmp/yapoc-inspector-files.png')
            await page.get_by_role('tab', name='Artifacts', exact=True).click()
            await expect(page.get_by_role('textbox', name='Filter artifacts')).to_have_value('Example')
            await page.get_by_role('button', name='TEXT Example report.md', exact=False).click()
            await expect(page.get_by_role('complementary', name='File viewer')).to_be_visible()
            await assert_layout()
            await page.get_by_role('button', name='Close file viewer').click()
            await expect(page.get_by_role('complementary', name='Workspace uploads')).to_be_visible()
            await page.get_by_role('tab', name='master flow', exact=True).click()
            await page.screenshot(path='/tmp/yapoc-inspector-desktop.png')

            await page.set_viewport_size({'width': 2048, 'height': 1100})
            await page.locator('.studio-agent-card[data-agent="builder"]').click()
            await page.locator('.studio-agent-card[data-agent="builder"]').get_by_role('button', name='Agent flow →', exact=True).click()
            master_flow = page.locator('[data-agent-flow="master"]')
            builder_flow = page.locator('[data-agent-flow="builder"]')
            await expect(master_flow).to_be_visible()
            await expect(builder_flow).to_be_visible()
            a, b = await master_flow.bounding_box(), await builder_flow.bounding_box()
            assert a['width'] >= 320 and b['width'] >= 320 and a['x'] + a['width'] <= b['x'] + 1, (a, b)
            await assert_layout()
            for agent, count in [('master', 123), ('builder', 456)]:
                sockets[-1].send(json.dumps({'type': 'agent_event', 'agent': agent, 'event': {
                    'type': 'usage_stats', 'agent': agent, 'timestamp': now, 'input_tokens': 2000,
                    'output_tokens': count, 'tokens_per_second': 24, 'context_window': 100000,
                    'model': 'deepseek-v4-pro', 'adapter': 'deepseek'}}))
            await expect(master_flow.get_by_test_id('usage-output')).to_have_text('123 out')
            await expect(builder_flow.get_by_test_id('usage-output')).to_have_text('456 out')
            await expect(builder_flow.locator('.agent-chat-flow-header').get_by_test_id('live-usage')).to_be_visible()
            await expect(master_flow.locator('.agent-chat-flow-header').get_by_test_id('live-usage')).to_be_visible()
            await expect(builder_flow.locator('.agent-chat-flow-msg-count')).to_have_count(0)
            await expect(builder_flow.locator(':scope > [data-testid="live-usage"]')).to_have_count(0)
            await expect(builder_flow.get_by_test_id('usage-cost')).not_to_have_text('Cost —')
            header_before = await builder_flow.locator('.agent-chat-flow-header').bounding_box()
            for event in [{'type': 'turn_start'}, {'type': 'thinking_delta', 'text': 'Reviewing the next change.'}]:
                sockets[-1].send(json.dumps({'type': 'agent_event', 'agent': 'builder', 'event': {
                    **event, 'agent': 'builder', 'timestamp': now}}))
            await expect(builder_flow.get_by_test_id('live-usage')).to_have_attribute('data-estimated', 'true')
            await expect(builder_flow.get_by_test_id('usage-input')).to_have_text('≈2.0k in')
            await expect(builder_flow.get_by_test_id('usage-cost')).not_to_have_text('Cost —')
            await expect(builder_flow.get_by_test_id('usage-context')).to_be_visible()
            await expect(builder_flow.get_by_test_id('usage-speed')).to_be_visible()
            header_after = await builder_flow.locator('.agent-chat-flow-header').bounding_box()
            assert abs(header_after['height'] - header_before['height']) < 2, (header_before, header_after)
            await page.screenshot(path='/tmp/yapoc-agent-flows-side-by-side.png')
            await page.get_by_role('button', name='Close builder flow', exact=True).click()
            await expect(builder_flow).to_have_count(0)
            await expect(master_flow).to_be_visible()

            for width in [1230, 977, 768, 390]:
                await page.set_viewport_size({'width': width, 'height': 982})
                if width <= 700:
                    await page.get_by_role('button', name='Close navigation', exact=True).click()
                team_close = page.get_by_role('button', name='Close agent team', exact=True)
                if width <= 1000 and await team_close.is_visible():
                    await team_close.click()
                await assert_layout()
                await page.screenshot(path=f'/tmp/yapoc-inspector-{width}.png')
            await page.get_by_role('button', name='Back to conversation').click()
            await expect(composer).to_be_visible()
            await expect(composer).to_have_value('Keep this draft while inspecting files')
            assert not errors, errors
            assert not mutations, mutations
            print('PASS: agent flow + team, simultaneous inspectors, preview, retained filters/draft, bounded resize, widths 1512/1230/977/768/390; no browser errors or mutations')
            await browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist', type=Path, required=True)
    asyncio.run(check(parser.parse_args().dist.resolve()))
