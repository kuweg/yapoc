"""Browser checks for paired panes, Resume home, context chips and the shared room.

Uses mocked data and prevents API mutations; run against the frontend dev server.
"""
import json
from playwright.sync_api import sync_playwright,expect


def check():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1512,'height':1000})
        errors=[];writes=[]
        page.add_init_script("localStorage.setItem('yapoc-sessions',JSON.stringify({version:2,state:{activeId:'room-session',sessions:[{id:'room-session',name:'Workspace session',createdAt:'2026-09-12',history:[]}]}}))")
        page.on('pageerror',lambda e:errors.append(str(e)))
        book={'id':'test-book','title':'Workspace reading','author':'Reader','format':'epub','status':'ready','total':2,'position':2,'offset':.3,'finished':False,'updated_at':'2026-09-12','preferences':{}}
        note={'id':'work-note','title':'Workspace notes','path':'app/projects/notes/work-note.md','revision':'v1','updated_at':'2026-09-12','links':[],'excerpt':'Keep this thought.','content':'# Workspace notes\n\nKeep this thought.'}
        canvas={'id':'test-canvas','name':'Workspace design','description':'A saved design','created_by':'user','created_at':'2026-09-12','updated_at':'2026-09-12','card_count':0}
        artifact={'id':'delivery','name':'generated.txt','path':'artifacts/generated.txt','kind':'text','mime':'text/plain','size':16,'sha256':'fixture','version':1,'source_agent':'builder','source_session':'room-session','source_task':'room-task','created_at':'2026-09-12','updated_at':'2026-09-12'}
        def api(route):
            path=route.request.url.split('/api',1)[-1].split('?')[0]
            if route.request.method not in ('GET','HEAD','OPTIONS'):
                writes.append(path)
                # Only the reader's normal progress autosave is expected in this test.
                if path=='/books/test-book/progress':route.fulfill(json={**book,**route.request.post_data_json});return
                route.abort();return
            if path=='/books':route.fulfill(json=[book])
            elif path=='/books/test-book':route.fulfill(json=book)
            elif path=='/books/test-book/contents':route.fulfill(json=[{'number':i,'label':str(i),'title':f'Section {i}'} for i in (1,2)])
            elif path.startswith('/books/test-book/sections/'):
                i=int(path.rsplit('/',1)[1]);route.fulfill(json={'number':i,'label':str(i),'title':f'Section {i}','text':f'Section {i}\n\nSaved reading content.'})
            elif path in ('/books/test-book/annotations','/books/test-book/messages'):route.fulfill(json=[])
            elif path=='/notes':route.fulfill(json={'notes':[note],'skipped':[]})
            elif path=='/notes/work-note':route.fulfill(json=note)
            elif path=='/whiteboard/boards':route.fulfill(json={'boards':[canvas]})
            elif path.startswith('/whiteboard/boards/'):route.fulfill(json={'canvas':canvas,'revision':0,'updated_at':None,'cards':[],'edges':[]})
            elif path=='/tasks':route.fulfill(json=[{'id':'room-task','session_id':'room-session','assigned_agent':'builder','status':'running','prompt':'Room fixture'},{'id':'other-task','session_id':'other-session','assigned_agent':'doctor','status':'running','prompt':'Unrelated'}])
            elif path=='/artifacts':route.fulfill(json={'artifacts':[artifact,{**artifact,'id':'other','name':'unrelated.txt','source_session':'other-session','source_task':'other-task'}]})
            elif path=='/files/preview':route.fulfill(json={'path':artifact['path'],'name':artifact['name'],'size':16,'kind':'text','ext':'.txt','content':'Fixture delivery'})
            else:route.continue_()
        page.route('**/api/**',api)
        try:
            page.goto('http://127.0.0.1:5173')
            page.get_by_role('button',name='Conversation',exact=True).click()
            composer=page.get_by_role('textbox',name='Message YAPOC')
            composer.fill('Discuss @book:"Workspace reading":pages:1-2 and @note:"Workspace notes"')
            page.get_by_role('button',name='Inspect @book:"Workspace reading":pages:1-2',exact=True).click()
            expect(page.get_by_role('dialog',name='Inspect context')).to_contain_text('Chapters 1–2')
            page.get_by_role('button',name='Close context preview').click()
            page.get_by_role('button',name='Remove @note:"Workspace notes"',exact=True).click()
            expect(composer).to_have_value('Discuss @book:"Workspace reading":pages:1-2 and ')
            layout=page.get_by_role('combobox',name='Workspace layout')
            layout.select_option('designing')
            expect(page.locator('[data-tab=chat]')).to_be_visible()
            expect(page.locator('[data-tab=whiteboard]')).to_be_visible()
            assert page.get_by_role('textbox',name='Message YAPOC').count()==1
            expect(composer).to_have_value('Discuss @book:"Workspace reading":pages:1-2 and ')
            divider=page.get_by_role('separator',name='Resize workspace panes')
            divider.focus();divider.press('ArrowLeft')
            expect(divider).to_have_attribute('aria-valuenow','53')
            layout.select_option('reviewing')
            page.get_by_role('button',name='Preview generated.txt',exact=True).click()
            expect(page.get_by_role('complementary',name='File viewer')).to_have_count(1)
            expect(page.get_by_role('complementary',name='File viewer')).to_contain_text('Fixture delivery')
            page.get_by_role('button',name='Close file viewer').click()
            layout.select_option('reading')
            expect(page.locator('[data-tab=books]')).to_be_visible()
            expect(page.locator('[data-tab=notes]')).to_be_visible()
            page.locator('.books-cover').filter(has_text='Workspace reading').click()
            expect(page.get_by_role('spinbutton',name='Reading location')).to_have_value('2')
            page.locator('.notes-list-item').filter(has_text='Workspace notes').click()
            expect(page.locator('.notes-document-header')).to_contain_text('Workspace notes')
            page.get_by_role('button',name='Home',exact=True).click()
            expect(page.locator('.resume-home')).to_contain_text('Workspace reading')
            page.get_by_role('button',name='Continue reading',exact=False).click()
            expect(page.get_by_role('spinbutton',name='Reading location')).to_have_value('2')
            page.screenshot(path='/tmp/yapoc-split-workspace.png')
            page.set_viewport_size({'width':390,'height':844})
            if page.get_by_role('button',name='Close navigation',exact=True).is_visible():page.get_by_role('button',name='Close navigation',exact=True).click()
            panes=page.get_by_role('group',name='Visible workspace pane')
            panes.get_by_role('button',name='Notes',exact=True).click()
            expect(page.locator('[data-tab=notes]')).to_be_visible()
            expect(page.locator('[data-tab=books]')).not_to_be_visible()
            panes.get_by_role('button',name='Book',exact=True).click()
            expect(page.locator('[data-tab=books]')).to_be_visible()
            expect(page.locator('[data-tab=notes]')).not_to_be_visible()
            page.screenshot(path='/tmp/yapoc-split-workspace-mobile.png')
            layout.select_option('single')
            page.set_viewport_size({'width':1512,'height':1000})
            page.get_by_role('button',name='Conversation',exact=True).click()
            expect(composer).to_have_value('Discuss @book:"Workspace reading":pages:1-2 and ')
            expect(page.get_by_role('region',name='Conversation shared room')).to_be_visible()
            room=page.get_by_role('region',name='Conversation shared room')
            expect(room.get_by_role('button',name='generated.txt builder')).to_be_visible()
            expect(room).not_to_contain_text('unrelated.txt')
            expect(room.locator('.office-resident[aria-label^=builder]')).to_have_count(1)
            expect(room.locator('.office-resident[aria-label^=doctor]')).to_have_count(0)
            page.get_by_role('button',name='Home',exact=True).click()
            page.screenshot(path='/tmp/yapoc-resume-home.png')
            assert not errors,errors
            assert all(path=='/books/test-book/progress' for path in writes),writes
            print('PASS: context range inspect/remove, paired panes, one composer, draft preserved, resize, resume, mobile pane switching, shared room')
        finally:browser.close()


if __name__=='__main__':check()
