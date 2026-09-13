"""Exercise Projects without modifying user resources or starting real agents."""
import copy
import json
from playwright.sync_api import sync_playwright, expect


def check():
    projects=[]; submissions=[]; unexpected=[]; errors=[]
    note={'id':'Design.md','title':'Design','content':'Use local services.','revision':'v1','updated_at':'2026-09-12','links':[],'excerpt':'Use local services.','path':'app/projects/notes/Design.md'}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda e:errors.append(str(e)))
        def api(route):
            path=route.request.url.split('/api',1)[-1].split('?')[0];method=route.request.method
            if path=='/projects' and method=='GET':route.fulfill(json=projects)
            elif path.startswith('/projects') and method in ('POST','PUT'):
                p=route.request.post_data_json;p={**p,'id':p.get('id','fixture-project'),'revision':p.get('revision',0)+1,'updated_at':'2026-09-12'}
                projects[:]=[p];route.fulfill(json=p,status=201 if method=='POST' else 200)
            elif path.startswith('/projects/') and method=='DELETE':projects.clear();route.fulfill(status=204)
            elif path=='/task/stream':
                submissions.append(copy.deepcopy(route.request.post_data_json))
                route.fulfill(content_type='text/event-stream',body='data: {"type":"status","state":"queued"}\n\ndata: {"type":"done","text":"Mock completion"}\n\n')
            elif method not in ('GET','HEAD','OPTIONS'):unexpected.append(path);route.abort()
            elif path=='/notes':route.fulfill(json={'notes':[note],'skipped':[]})
            elif path=='/notes/Design.md':route.fulfill(json=note)
            elif path in ('/books','/tasks'):route.fulfill(json=[])
            elif path=='/whiteboard/boards':route.fulfill(json={'boards':[]})
            elif path=='/artifacts':route.fulfill(json={'artifacts':[]})
            else:route.continue_()
        page.route('**/api/**',api)
        try:
            page.goto('http://127.0.0.1:5173')
            page.get_by_role('button',name='Projects',exact=True).click()
            page.get_by_role('button',name='New project',exact=True).click()
            dialog=page.get_by_role('dialog',name='Edit project')
            dialog.get_by_label('Name',exact=True).fill('Home automation')
            dialog.get_by_label('Description').fill('An offline home system')
            dialog.get_by_label('Brief').fill('Prefer Python and local services.')
            dialog.get_by_role('button',name='Save project').click()
            expect(page.locator('.projects-tab h1')).to_have_text('Home automation')
            page.get_by_role('button',name='Sources',exact=True).click()
            page.get_by_label('Link existing source').select_option(label='note · Design')
            page.get_by_label('Always include').check()
            expect(page.get_by_label('Always include')).to_be_checked()
            assert projects[0]['sources'][0]['always']
            page.get_by_role('button',name='Overview',exact=True).click()
            page.get_by_role('button',name='New project conversation').click()
            context=page.locator('.project-context')
            expect(context).to_contain_text('Home automation')
            context.locator('summary').first.click()
            context.get_by_label('Project brief',exact=False).uncheck()
            page.get_by_role('textbox',name='Message YAPOC').fill('Review the plan')
            page.get_by_role('textbox',name='Message YAPOC').press('Enter')
            page.wait_for_timeout(500)
            assert submissions and submissions[0]['project_id']=='fixture-project',submissions
            assert submissions[0]['project_excluded']==['__brief__'],submissions
            assert submissions[0]['session_id'] in projects[0]['sessions']
            expect(context.get_by_label('Project brief',exact=False)).to_be_checked()
            page.get_by_label('Workspace layout').select_option('designing')
            page.get_by_role('button',name='Projects',exact=True).click()
            page.get_by_role('button',name='Continue workspace ↗').click()
            expect(page.get_by_label('Workspace layout')).to_have_value('designing')
            page.get_by_role('button',name='Projects',exact=True).click()
            page.screenshot(path='/tmp/yapoc-projects-desktop.png')
            page.set_viewport_size({'width':390,'height':844})
            if page.get_by_role('button',name='Close navigation',exact=True).is_visible():page.get_by_role('button',name='Close navigation',exact=True).click()
            page.screenshot(path='/tmp/yapoc-projects-mobile.png')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Page overflows horizontally'
            page.get_by_role('button',name='Delete project…').click()
            page.get_by_role('dialog',name='Delete project').get_by_role('button',name='Delete project',exact=True).click()
            expect(page.locator('.projects-tab h1')).to_have_text('Projects')
            assert not projects
            assert not unexpected,unexpected
            assert not errors,errors
            print('PASS: create, edit, source linking, default note, project conversation, request context/exclusion reset, layout resume, mobile, deletion preserves sources')
        finally:browser.close()


if __name__=='__main__':check()
