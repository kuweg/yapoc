"""Exercise Notes against the real notes API in a temporary vault, without agents.

poetry run python scripts/check_notes_browser.py --dist /tmp/yapoc-notes-build
"""
import argparse
import asyncio
import json
import socket
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from playwright.async_api import async_playwright, expect

from app.backend.routers.notes import router as notes_router
from app.backend.routers import tasks
from app.backend.services import notes, task_runtime


async def check(dist: Path):
    with tempfile.TemporaryDirectory(prefix='yapoc-notes-check-') as temporary:
        root = Path(temporary) / 'notes'
        notes._root = lambda: root
        project = notes.create_note('Project map', '# Project map\n\nA ==local-first== workspace for focused work.\n\n## Next steps\n\nSee [[Launch plan|the launch plan]] and [[Open questions]].\n\n> [!NOTE] Context that travels with your task.\n\n- [x] Create a plan\n- [ ] Review it\n\n| Topic | Owner |\n| --- | --- |\n| Launch | Master |\n\n```python\nprint("Hello YAPOC")\n```\n\n`[[This is code]]`\n')
        notes.create_note('Launch plan', '# Launch plan\n\nConnected to [[Project map#Next steps]].\n\nKeep the first release focused.\n')
        queue = {}
        def enqueue(**kwargs):
            row = {**kwargs, 'status': 'done'}
            queue[row['id']] = row
            return row
        tasks.create_queued_task = enqueue
        tasks.get_queued_task = lambda task_id: queue.get(task_id)
        task_runtime.read_events = lambda task_id, cursor: [{'seq': 1, 'type': 'text', 'text': 'The selected notes reached this task.'}] if cursor < 1 else []
        app = FastAPI()
        app.include_router(notes_router, prefix='/api')
        app.include_router(tasks.router, prefix='/api')
        app.mount('/', StaticFiles(directory=dist, html=True))
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        address = f'http://127.0.0.1:{listener.getsockname()[1]}'
        server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off'))
        worker = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        worker.start()
        errors = []
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                context = await browser.new_context(viewport={'width': 1512, 'height': 982}, reduced_motion='reduce')
                async def api(route):
                    path = urlsplit(route.request.url).path
                    if path.startswith('/api/notes') or path == '/api/task/stream':
                        await route.continue_()
                        return
                    fixtures = {'/api/auth/status': {'authenticated': True, 'configured': False}, '/api/health': {'status': 'ok'}, '/api/ping': {'status': 'ok'},
                        '/api/agents': [], '/api/tasks': [], '/api/plugins': {'plugins': []}, '/api/mcp-servers/servers': {'servers': []}}
                    if path in fixtures:
                        await route.fulfill(json=fixtures[path])
                    else:
                        await route.fulfill(status=404, json={'detail': 'Not used by this scenario'})
                await context.route('**/api/**', api)
                await context.route_web_socket('**/ws**', lambda ws: ws.on_message(lambda message: None))
                page = await context.new_page()
                page.on('pageerror', lambda error: (errors.append(str(error)), print('BROWSER ERROR:', error, flush=True)))
                await page.goto(address)
                await page.get_by_role('button', name='Notes', exact=True).click()
                await page.get_by_role('complementary', name='Notes library').get_by_role('button', name='Project map', exact=True).click()
                preview = page.get_by_role('article', name='Note preview')
                await expect(preview.get_by_role('heading', name='Project map', exact=True)).to_be_visible()
                await expect(preview.locator('mark')).to_have_text('local-first')
                await expect(preview.locator('table')).to_be_visible()
                await expect(preview.locator('blockquote[data-callout="note"]')).to_be_visible()
                await expect(preview.locator('code').filter(has_text='[[This is code]]')).to_be_visible()
                await preview.get_by_role('button', name='the launch plan', exact=True).click()
                await expect(page.locator('.notes-document-header h2')).to_have_text('Launch plan')
                await expect(page.locator('.notes-backlinks > div').first.get_by_role('button', name='Project map', exact=True)).to_be_visible()
                await preview.get_by_role('button', name='Project map#Next steps').click()
                await page.get_by_role('button', name='Split', exact=True).click()
                editor = page.get_by_role('textbox', name='Markdown editor')
                await editor.fill(project['content'] + '\nSaved from the browser.\n')
                await expect(page.get_by_text('Saved to disk', exact=True)).to_be_visible(timeout=10000)
                assert 'Saved from the browser.' in notes.read_note(project['id'])['content']
                await page.screenshot(path='/tmp/yapoc-notes-editor.png')
                # The preview stays live while editing, but an external edit must not be lost.
                current = notes.read_note(project['id'])
                notes.save_note(project['id'], current['content'] + '\nExternal agent edit.\n', current['revision'])
                await editor.fill(project['content'] + '\nUnsaved conflict draft.\n')
                await expect(page.get_by_role('alert').filter(has_text='changed elsewhere')).to_be_visible(timeout=10000)
                assert 'External agent edit.' in notes.read_note(project['id'])['content']
                await page.get_by_role('button', name='Discard draft and reload').click()
                await expect(editor).to_have_value(notes.read_note(project['id'])['content'])
                # Create through an unresolved link.
                await page.get_by_role('button', name='Preview', exact=True).click()
                await preview.get_by_role('button', name='Open questions', exact=True).click()
                dialog = page.get_by_role('dialog', name='Create note', exact=True)
                await expect(dialog.get_by_role('textbox', name='Note name')).to_have_value('Open questions')
                await dialog.get_by_role('button', name='Create note', exact=True).click()
                await expect(page.locator('.notes-document-header h2')).to_have_text('Open questions')
                await page.get_by_role('complementary', name='Notes library').get_by_role('button', name='Project map', exact=True).click()
                await page.get_by_role('button', name='Links graph', exact=False).click()
                await expect(page.locator('.notes-graph-canvas svg')).to_be_visible()
                await page.screenshot(path='/tmp/yapoc-notes-graph.png')
                await page.locator('.notes-graph-canvas').get_by_text('Project map', exact=True).click()
                await expect(page.locator('.notes-document-header h2')).to_have_text('Project map')
                await page.get_by_role('button', name='Pin as context', exact=True).click()
                await expect(page.get_by_role('button', name='Pinned to context')).to_be_visible()
                await page.get_by_role('button', name='Add to chat', exact=True).click()
                composer = page.get_by_role('textbox', name='Message YAPOC')
                await expect(composer).to_have_value('@note:Project%20map.md ')
                await expect(page.get_by_label('Pinned note context')).to_contain_text('Project map')
                await composer.fill('Use my notes to summarize the next step.')
                await composer.press('Enter')
                await expect(page.get_by_text('The selected notes reached this task.', exact=True)).to_be_visible(timeout=10000)
                row = next(iter(queue.values()))
                assert 'External agent edit.' in row['prompt']
                assert len(json.loads(row['metadata'])['notes']) == 1
                # Reverse integration: capture an assistant response as editable Markdown.
                await page.get_by_role('button', name='Save as note', exact=True).first.click()
                capture = page.get_by_role('dialog', name='Create note', exact=True)
                await capture.get_by_role('textbox', name='Note name').fill('Chat takeaway')
                await capture.get_by_role('button', name='Create note', exact=True).click()
                await expect(page.locator('.notes-document-header h2')).to_have_text('Chat takeaway')
                assert 'selected notes reached' in notes.read_note('Chat takeaway.md')['content']
                # Pins are isolated to the active conversation and survive refresh.
                await page.get_by_role('button', name='Conversation', exact=True).click()
                await page.reload()
                await expect(page.get_by_label('Pinned note context')).to_contain_text('Project map')
                await page.get_by_role('button', name='New conversation', exact=True).click()
                await expect(page.get_by_label('Pinned note context')).to_have_count(0)
                # Mobile stays within the viewport, with a usable editor and note strip.
                await page.get_by_role('button', name='Notes', exact=True).click()
                await page.set_viewport_size({'width': 390, 'height': 844})
                if await page.get_by_role('button', name='Close navigation', exact=True).is_visible():
                    await page.get_by_role('button', name='Close navigation', exact=True).click()
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                await page.screenshot(path='/tmp/yapoc-notes-mobile.png')
                assert not errors, errors
                print('PASS: real Notes CRUD, Markdown extensions, links/backlinks, graph view, autosave/conflicts, missing-note creation, task context, chat capture, pin persistence/isolation and mobile layout', flush=True)
                await browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=5)
            listener.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist', type=Path, required=True)
    asyncio.run(check(parser.parse_args().dist.resolve()))
