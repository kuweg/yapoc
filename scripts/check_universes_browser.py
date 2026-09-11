"""Offline comparison UI checks: launch, independent controls, selection, mobile."""
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
    app=FastAPI(); mount_dashboard(app,dist)
    listener=socket.socket(); listener.bind(('127.0.0.1',0))
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off'))
    worker=threading.Thread(target=lambda: server.run(sockets=[listener]),daemon=True); worker.start()
    address=f'http://127.0.0.1:{listener.getsockname()[1]}'
    mid='a'*32
    mission=None; launches=[]; stopped=[]; chosen=[]; errors=[]
    try:
        async with async_playwright() as pw:
            browser=await pw.chromium.launch()
            page=await browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce')
            await page.add_init_script("localStorage.setItem('yapoc-sessions', JSON.stringify({state:{sessions:[{id:'session',name:'Test',createdAt:'2026-09-11',history:[]}],activeId:'session'},version:0}))")
            page.on('pageerror',lambda e: errors.append(str(e)))
            async def api(route):
                nonlocal mission
                path=urlsplit(route.request.url).path
                if path=='/api/universes' and route.request.method=='POST':
                    data=route.request.post_data_json; launches.append(data)
                    mission={**data,'id':mid,'integration':None,'runs':[{'id':f'universe_{mid}_{letter}','letter':letter,'approach':approach,'status':'running','summary':'','checks':[],'cost_usd':0.02,'branch':f'branch-{letter}','preview_url':None} for letter,approach in zip('ab',data['approaches'])]}
                    await route.fulfill(json=mission); return
                if path=='/api/universes': await route.fulfill(json=[mission] if mission else []); return
                if path==f'/api/universes/{mid}': await route.fulfill(json=mission); return
                if path.endswith('/a/stop'):
                    stopped.append('a'); mission['runs'][0]['status']='cancelled'; await route.fulfill(json=mission); return
                if path.endswith('/changes'): await route.fulfill(json={'stat':'1 file changed','patch':'+ new layout'}); return
                if path.endswith('/activity'): await route.fulfill(json=[]); return
                if path.endswith('/b/choose'):
                    chosen.append('b'); mission['integration']={'branch':f'yapoc/integration/{mid}','status':'ready','checks':[{'command':'fixture','exit_code':0,'output':'checks passed'}]}; await route.fulfill(json=mission); return
                fixtures={'/api/auth/status':{'authenticated':True,'configured':False},'/api/agents':[], '/api/health':{'status':'ok'},'/api/ping':{'status':'ok'},'/api/tasks':[]}
                await route.fulfill(status=200 if path in fixtures else 404,json=fixtures.get(path,{}))
            await page.route('**/api/**',api)
            await page.route_web_socket('**/ws**',lambda ws: ws.on_message(lambda _:None))
            await page.goto(address)
            await page.get_by_role('button',name='Composer actions',exact=True).click()
            await page.get_by_role('button',name='Try parallel approaches',exact=True).click()
            dialog=page.get_by_role('dialog',name='Parallel universes')
            await dialog.get_by_label('What should we achieve?',exact=True).fill('Redesign the GitHub browser')
            await dialog.get_by_label('Shared requirements',exact=True).fill('Mobile friendly; preserve current functionality')
            await page.screenshot(path='/tmp/yapoc-universes-setup.png')
            await dialog.get_by_role('button',name='Start 2 universes',exact=True).click()
            a=dialog.get_by_role('region',name='Universe A',exact=True)
            b=dialog.get_by_role('region',name='Universe B',exact=True)
            await expect(a).to_contain_text('Conservative')
            await expect(b).to_contain_text('Experimental')
            await a.get_by_role('button',name='Stop A',exact=True).click()
            await expect(a).to_contain_text('cancelled')
            await expect(b).to_contain_text('running')
            assert stopped==['a'] and len(launches)==1
            for run in mission['runs']:
                run.update(status='completed',summary='A distinct candidate',checks=[{'command':'npm run build','exit_code':0,'output':'Build passed'}])
            await expect(b.get_by_role('button',name='Choose B',exact=True)).to_be_enabled(timeout=10000)
            await a.get_by_role('button',name='Changes',exact=True).click()
            await expect(a).to_contain_text('new layout')
            await b.get_by_role('button',name='Checks',exact=True).click()
            await expect(b).to_contain_text('Build passed')
            await page.screenshot(path='/tmp/yapoc-universes-desktop.png')
            await page.set_viewport_size({'width':390,'height':844})
            await expect(a).to_be_visible(); await expect(b).not_to_be_visible()
            await dialog.get_by_role('button',name='Universe B',exact=True).click()
            await expect(b).to_be_visible(); await expect(a).not_to_be_visible()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await b.get_by_role('button',name='Choose B',exact=True).click()
            await expect(dialog).to_contain_text('Integration: ready')
            await expect(dialog).to_contain_text('Your live workspace is unchanged')
            await page.screenshot(path='/tmp/yapoc-universes-mobile.png')
            assert chosen==['b']
            await dialog.get_by_role('button',name='Close parallel universes',exact=True).click()
            await expect(dialog).to_have_count(0)
            assert not errors,errors
            await browser.close()
    finally:
        server.should_exit=True; worker.join(timeout=5); listener.close()
    print('PASS: composer launch, one mission, independent stop, checks/diffs, selection, desktop/mobile')

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--dist',type=Path,required=True)
    asyncio.run(check(parser.parse_args().dist))
