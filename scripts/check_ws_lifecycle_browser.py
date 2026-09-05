"""Read-only browser regression against the Vite development UI.

Run: poetry run python scripts/check_ws_lifecycle_browser.py
Requires YAPOC at localhost:5173 and installed Playwright/Chromium.
Submits no tasks and does not restart the backend. Exercises React StrictMode
cleanup plus overlapping online/reconnect events using real WebSockets.
"""
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        context=await browser.new_context()
        await context.add_init_script('''(() => {
          const Native = window.WebSocket;
          window.testSockets = [];
          window.WebSocket = class extends Native {
            constructor(...args) {
              super(...args);
              if (new URL(args[0]).pathname === '/ws') window.testSockets.push(this);
            }
          };
        })()''')
        page=await context.new_page()
        await page.goto('http://localhost:5173')
        await asyncio.sleep(5)
        states=await page.evaluate('testSockets.map(s=>s.readyState)')
        print('Initial socket states:',states,flush=True)
        assert states.count(1)==1, 'multiple open task WebSockets after React mount'
        await page.evaluate('''() => {
          testSockets.filter(s=>s.readyState===1).forEach(s=>s.close());
          for(let i=0;i<10;i++) window.dispatchEvent(new Event('online'));
        }''')
        await asyncio.sleep(5)
        states=await page.evaluate('testSockets.map(s=>s.readyState)')
        print('Reconnect socket states:',states,flush=True)
        assert states.count(1)==1, 'multiple open task WebSockets after overlapping reconnect triggers'
        print('PASS: one current connection after mount and repeated reconnect triggers',flush=True)
        await browser.close()

asyncio.run(main())
