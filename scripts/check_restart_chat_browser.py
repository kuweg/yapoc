"""Playwright regression over the built UI with a simulated backend restart.

Run: poetry run python scripts/check_restart_chat_browser.py --dist /tmp/yapoc-restart-build
All API/WebSocket traffic is intercepted. No real agent or provider runs.
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


async def check(dist: Path, screenshot: Path):
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(dist)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    address = f'http://127.0.0.1:{server.server_port}'
    phase = 0
    sockets = []
    errors = []
    trace = []
    page = None
    now = '2026-09-05T13:24:03Z'
    def result(number=1, owner='chat-a'):
        return {'id': f'resume-{number}', 'task_id': f'resume-{number}', 'source': 'resume',
                'status': 'done', 'prompt': 'Verify task outcome', 'session_id': owner, 'created_at': now, 'completed_at': now,
                'result': f'Restart complete. Belgrade forecast delivery {number}.',
                'structured_result': {'schema_version': 1, 'task_id': f'resume-{number}', 'status': 'succeeded',
                    'summary': 'Runtime outcome', 'changes': {'files': ['forecast.md']},
                    'verification_status': 'checks_passed', 'verification': [{'command': 'pytest tests/', 'status': 'passed', 'exit_code': 0, 'evidence_event_seq': number, 'evidence_url': ''}],
                    'artifacts': [], 'usage': {'input_tokens': 12, 'output_tokens': 0, 'estimated_cost_usd': None, 'scope': 'Direct task stream'}, 'limitations': []},
                'metadata': json.dumps({'messages': [f'Restart complete. Belgrade forecast delivery {number}.']})}
    def global_tasks():
        if phase == 1:
            return [result()]
        if phase == 3:
            return [{'id': f'unrelated-{i}', 'session_id': 'chat-b', 'status': 'done',
                     'source': 'cron', 'result': 'service work', 'metadata': '{"silent":true}'} for i in range(25)]
        return []
    async def api(route):
        path = urlsplit(route.request.url).path
        if phase == 5 and path == '/api/task/stream' and route.request.method == 'POST':
            request = route.request.post_data_json
            outcome = result(5)['structured_result']
            outcome['task_id'] = request['task_id']
            wire = ''.join('data: ' + json.dumps(e) + '\n\n' for e in [
                {'type': 'text', 'text': 'Live structured answer'}, {'type': 'task_result', 'result': outcome}]) + 'data: [DONE]\n\n'
            await route.fulfill(content_type='text/event-stream', body=wire)
            return
        if route.request.method not in {'GET', 'HEAD'}:
            # The scenario starts with the already persisted pre-restart turn.
            raise AssertionError(f'Unexpected mutation: {route.request.method} {path}')
        response = []
        if path == '/api/auth/status': response = {'authenticated': True, 'configured': False}
        elif path in {'/api/health', '/api/ping'}: response = {'status': 'ok', 'uptime': 100}
        elif path == '/api/tasks': response = global_tasks()
        elif path == '/api/agents': response = []
        else:
            # Unrelated panels should use their normal unavailable-data state,
            # not receive an incorrectly shaped successful mock response.
            await route.fulfill(status=404, content_type='application/json', body='{"detail":"Not used by this scenario"}')
            return
        await route.fulfill(status=200, content_type='application/json', body=json.dumps(response))
    def websocket(ws):
        if urlsplit(ws.url).path != '/ws':
            ws.on_message(lambda message: None)
            return
        sockets.append(ws)
        trace.append(["connect", phase])
        ws.send(json.dumps({'type': 'state_sync', 'tasks': global_tasks()}))
        def receive(raw):
            data = json.loads(raw)
            trace.append(['receive', data])
            if data.get('type') == 'subscribe':
                sid = data['session_id']
                tasks = [result(3)] if phase == 3 and sid == 'chat-a' else []
                ws.send(json.dumps({'type': 'session_sync', 'session_id': sid, 'tasks': tasks}))
            elif data.get('type') == 'ping': ws.send('{"type":"pong"}')
        ws.on_message(receive)
    async def subscribed(sid, after=0):
        for _ in range(500):
            if any(event[0] == 'receive' and event[1].get('type') == 'subscribe' and event[1].get('session_id') == sid for event in trace[after:]):
                return
            await asyncio.sleep(0.02)
        raise AssertionError(f'WebSocket did not subscribe to {sid}')

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(viewport={'width': 1440, 'height': 1050})
            await context.route('**/api/**', api)
            await context.route_web_socket('**/ws**', websocket)
            initial = {'state': {'sessions': [
                {'id': 'chat-a', 'name': 'Weather chat', 'createdAt': now, 'history': [
                    {'role': 'user', 'content': 'Restart yourself and give the weather forecast'},
                    {'role': 'assistant', 'content': 'Service is restarting now'}]},
                {'id': 'chat-b', 'name': 'Other chat', 'createdAt': now, 'history': []}], 'activeId': 'chat-a'}, 'version': 1}
            await context.add_init_script('''(value => {
              localStorage.setItem('yapoc-voice-settings', JSON.stringify({state:{voiceEnabled:false,voiceAutoSpeak:false},version:0}));
              if (!localStorage.getItem('yapoc-sessions')) localStorage.setItem('yapoc-sessions', JSON.stringify(value));
            })(''' + json.dumps(initial) + ')')
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('websocket', lambda ws: ws.on('framereceived', lambda data: trace.append(['frame', str(data)[:1000]])))
            await page.goto(address)
            chat = page.locator('.chat-history')
            await expect(chat.get_by_text('Service is restarting now', exact=True)).to_be_visible(timeout=20000)
            await subscribed('chat-a')
            # Backend goes away; completion happens before the browser reconnects.
            phase = 1
            await sockets[-1].close(code=1012, reason='simulated backend restart')
            await expect(chat.get_by_text(result()['result'], exact=True)).to_have_count(1, timeout=15000)
            await expect(chat.get_by_text(result()['result'], exact=True)).to_be_visible()
            await page.reload()
            await expect(chat.get_by_text(result()['result'], exact=True)).to_have_count(1, timeout=15000)
            card = chat.get_by_test_id('structured-result-card')
            await expect(card).to_have_count(1)
            await card.locator('summary').click()
            await expect(card.get_by_text('forecast.md', exact=True)).to_be_visible()
            await expect(card.get_by_role('link', name='View log')).to_have_attribute('href', '/api/tasks/resume-1/evidence/1')
            await expect(card.get_by_text('12 input tokens · 0 output tokens · Cost unknown', exact=True)).to_be_visible()
            await card.locator('summary').click()
            print('PASS: structured evidence card survives reload with unknown cost and zero output intact')
            print('PASS: restart disconnect, missed completion replay, normal chat bubble, reload without duplication')

            async def switch_chat(sid):
                mark = len(trace)
                await page.evaluate('''sid => {
                  const saved=JSON.parse(localStorage.getItem('yapoc-sessions'));
                  saved.state.activeId=sid;
                  localStorage.setItem('yapoc-sessions', JSON.stringify(saved));
                }''', sid)
                await page.reload()
                await expect(page.locator('.chat-history')).to_be_visible()
                await page.wait_for_function("JSON.parse(localStorage.getItem('yapoc-sessions')).state.activeId === '" + sid + "'")
                await subscribed(sid, mark)

            phase = 2
            await switch_chat('chat-b')
            sockets[-1].send(json.dumps({'type': 'task_complete', **result(2)}))
            await page.wait_for_function("JSON.parse(localStorage.getItem('yapoc-sessions')).state.sessions.find(s=>s.id==='chat-a').history.some(m=>m.completionId==='resume-2:0')")
            await expect(chat.get_by_text(result(2)['result'], exact=True)).to_have_count(0)
            await switch_chat('chat-a')
            await expect(chat.get_by_text(result(2)['result'], exact=True)).to_have_count(1)
            print('PASS: inactive owner receives resumed reply; unrelated active chat stays clean')

            phase = 3
            await page.reload()
            await expect(chat.get_by_text(result(3)['result'], exact=True)).to_have_count(1, timeout=15000)
            await page.reload()
            await expect(chat.get_by_text(result(3)['result'], exact=True)).to_have_count(1, timeout=15000)
            print('PASS: session replay recovers a completion outside the global task batch, exactly once')

            phase = 4
            wrong = result(4, 'invented-run-session')
            sockets[-1].send(json.dumps({'type': 'task_complete', **wrong}))
            await page.wait_for_timeout(100)
            await expect(chat.get_by_text(wrong['result'], exact=True)).to_have_count(0)
            sockets[-1].send(json.dumps({'type': 'task_complete', **result(4)}))
            await expect(chat.get_by_text(result(4)['result'], exact=True)).to_have_count(1)
            print('PASS: corrected ownership is deliverable after an earlier unowned completion')
            await page.screenshot(path=str(screenshot), full_page=True)
            # Display-history trimming must not erase the delivery receipt.
            await page.evaluate("""() => {
              const saved=JSON.parse(localStorage.getItem('yapoc-sessions'));
              const owner=saved.state.sessions.find(s=>s.id==='chat-a');
              owner.history=owner.history.filter(m=>m.completionId!=='resume-3:0');
              localStorage.setItem('yapoc-sessions', JSON.stringify(saved));
            }""")
            phase = 3
            mark = len(trace)
            await page.reload()
            await subscribed('chat-a', mark)
            await expect(chat.get_by_text(result(3)['result'], exact=True)).to_have_count(0)
            print('PASS: delivery receipts prevent replay after display history is trimmed')
            phase = 1
            await page.get_by_role('button', name='Tasks', exact=True).click()
            await page.get_by_text('Verify task outcome', exact=True).click()
            task_card = page.get_by_test_id('structured-result-card').filter(visible=True)
            await expect(task_card).to_have_count(1)
            await task_card.locator('summary').click()
            await expect(task_card.get_by_text('forecast.md', exact=True)).to_be_visible()
            print('PASS: Tasks displays the same structured evidence card')
            phase = 5
            await page.get_by_role('button', name='Conversation', exact=True).click()
            composer = page.locator('textarea').first
            await composer.fill('Run a structured task')
            await composer.press('Enter')
            await expect(chat.get_by_text('Live structured answer', exact=True)).to_be_visible()
            live_card = chat.get_by_test_id('structured-result-card').last
            await live_card.locator('summary').click()
            await expect(live_card.get_by_text('forecast.md', exact=True)).to_be_visible()
            await page.reload()
            await expect(chat.get_by_text('Live structured answer', exact=True)).to_have_count(1)
            await expect(chat.get_by_test_id('structured-result-card').last).to_be_visible()
            print('PASS: live SSE result card persists alongside the answer after reload')
            assert not errors, errors
            await browser.close()
    except Exception:
        print('BROWSER ERRORS:', errors, flush=True)
        print('WS TRACE:', trace[-30:], flush=True)
        raise
    finally:
        server.shutdown()
        server.server_close()


async def live_readonly(url: str, session_id: str, screenshot: Path):
    """Verify the repaired saved reply through live GETs/WS in a fresh profile."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1440, 'height': 1050})
        async def readonly(route):
            parsed = urlsplit(route.request.url)
            if route.request.method not in {'GET', 'HEAD'} or parsed.hostname not in {'localhost', '127.0.0.1'}:
                await route.abort()
            else:
                await route.continue_()
        await context.route('**/*', readonly)
        initial = {'state': {'sessions': [{'id': session_id, 'name': 'Recovered weather chat',
                   'createdAt': '2026-09-05T13:20:59Z', 'history': [
                     {'role': 'user', 'content': 'Restart yourself and give the weather forecast'},
                     {'role': 'assistant', 'content': 'Service is restarting now'}]}],
                   'activeId': session_id}, 'version': 2}
        await context.add_init_script("""(value => {
          if (!localStorage.getItem('yapoc-sessions')) localStorage.setItem('yapoc-sessions', JSON.stringify(value));
        })(""" + json.dumps(initial) + ')')
        page = await context.new_page()
        await page.goto(url)
        chat = page.locator('.chat-history')
        reply = chat.get_by_text("Restart complete — I'm back up.", exact=True)
        await expect(reply).to_have_count(1, timeout=20000)
        await expect(reply).to_be_visible()
        await page.reload()
        await expect(page.get_by_role('status', name='Connection: Live', exact=True).first).to_be_visible(timeout=20000)
        await expect(reply).to_have_count(1, timeout=20000)
        await reply.scroll_into_view_if_needed()
        await expect(reply).to_be_in_viewport()
        await page.screenshot(path=str(screenshot), full_page=True)
        print('PASS: actual saved forecast appears in its owning chat through the live backend, once after reload')
        await browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--screenshot', type=Path, default=Path('/tmp/yapoc-restart-chat-pass.png'))
    parser.add_argument('--live-url')
    parser.add_argument('--session-id')
    args = parser.parse_args()
    if args.live_url:
        if not args.session_id: parser.error('--session-id is required with --live-url')
        asyncio.run(live_readonly(args.live_url, args.session_id, args.screenshot))
    else:
        asyncio.run(check(args.dist.resolve(), args.screenshot))
