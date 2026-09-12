"""Exercise reading tools against the running app, with fake AI and disposable books/maps."""
import argparse
import io
import json
import zipfile
from playwright.sync_api import sync_playwright, expect


def fixture():
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:
        z.writestr('META-INF/container.xml','<container><rootfiles><rootfile full-path="book.opf"/></rootfiles></container>')
        z.writestr('book.opf','<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata><dc:title>Reading tools browser fixture</dc:title></metadata><manifest><item id="one" href="one.xhtml"/><item id="two" href="two.xhtml"/></manifest><spine><itemref idref="one"/><itemref idref="two"/></spine></package>')
        z.writestr('one.xhtml','<h1>Connected systems</h1><p>Systems communicate through events.</p><p>A queue lets producers and consumers work independently.</p>')
        z.writestr('two.xhtml','<h1>Putting it together</h1><p>Readers build understanding by connecting ideas.</p>')
    return data.getvalue()


def check(continuous=False):
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];asks=[];boards=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto('http://127.0.0.1:5173')
        r=page.request.post('http://127.0.0.1:5173/api/books',multipart={'file':{'name':'reading-tools.epub','mimeType':'application/epub+zip','buffer':fixture()}})
        assert r.ok,r.text()
        book=r.json();base='http://127.0.0.1:5173/api/books/'+book['id']
        quote='Systems communicate through events.'
        def answer(route):
            body=route.request.post_data_json;asks.append(body)
            route.fulfill(json={'id':str(len(asks)),'question':body.get('question') or body['action'],'answer':'Events connect systems [S1].','scope':{'start':1,'end':1,'action':body['action']},'citations':[{'id':'S1','number':1,'label':'1','excerpt':quote}]})
        page.route('**/books/*/ask',answer)
        page.route('**/books/*/map/preview',lambda route:route.fulfill(json={'name':'Browser reading map','nodes':[{'key':'events','title':'Events','body':'Events connect systems [S1].','number':1,'excerpt':quote},{'key':'systems','title':'Systems','body':'Systems communicate [S1].','number':1,'excerpt':quote}],'edges':[{'source':'events','target':'systems','label':'connect'}]}))
        def track(response):
            if response.request.method=='POST' and response.url.endswith('/map') and response.ok:
                boards.append(response.json()['canvas']['id'])
        page.on('response',track)
        def select():
            page.locator('.reading-page p').filter(has_text=quote).first.evaluate("""el=>{const range=document.createRange();range.selectNodeContents(el);const s=window.getSelection();s.removeAllRanges();s.addRange(range);el.dispatchEvent(new PointerEvent('pointerup',{bubbles:true}));}""")
            expect(page.get_by_role('toolbar',name='Passage actions')).to_be_visible()
        try:
            page.get_by_role('button',name='Books',exact=True).click()
            page.locator('.books-cover').filter(has_text=book['title']).click()
            if continuous: page.get_by_role('button',name='Vertical scroll',exact=True).click()
            page.get_by_role('button',name='Study desk off',exact=True).click()
            expect(page.get_by_role('img',name='Pixel study desk:',exact=False)).to_be_visible()
            page.get_by_role('button',name='Analogy',exact=True).click()
            select()
            page.get_by_role('toolbar',name='Passage actions').get_by_role('button',name='Explain',exact=True).click()
            expect(page.locator('.reading-turn')).to_have_count(1)
            assert asks[-1]['selection']==quote and asks[-1]['explanation_style']=='analogy'
            page.get_by_role('textbox',name='Translation language').fill('Serbian')
            select()
            page.get_by_role('toolbar',name='Passage actions').get_by_role('button',name='Translate',exact=True).click()
            expect(page.locator('.reading-turn')).to_have_count(2)
            assert asks[-1]['language']=='Serbian' and asks[-1]['action']=='translate'
            select()
            page.get_by_role('toolbar',name='Passage actions').get_by_role('button',name='Highlight',exact=True).click()
            expect(page.get_by_role('button',name='Open annotated location 1')).to_be_visible()
            select()
            page.get_by_role('toolbar',name='Passage actions').get_by_role('button',name='Save',exact=True).click()
            page.get_by_role('textbox',name='Your explanation').fill('My understanding: events reduce coupling.')
            page.get_by_role('button',name='Save to knowledge shelf',exact=True).click()
            expect(page.get_by_role('dialog',name='Save idea')).not_to_be_visible()
            page.get_by_role('slider',name='Jump through book').fill('2')
            expect(page.get_by_role('spinbutton',name='Reading location')).to_have_value('2')
            page.get_by_role('button',name='Open annotated location 1').click()
            expect(page.get_by_role('spinbutton',name='Reading location')).to_have_value('1')
            page.get_by_role('button',name='Create Whiteboard concept map',exact=False).click()
            page.get_by_role('button',name='Generate preview',exact=True).click()
            expect(page.locator('.reading-map-preview article')).to_have_count(2)
            page.get_by_role('button',name='Create new Whiteboard',exact=True).click()
            expect(page.get_by_role('button',name='Read source',exact=False).first).to_be_visible()
            page.get_by_role('button',name='Read source',exact=False).first.click()
            expect(page.get_by_role('spinbutton',name='Reading location')).to_have_value('1')
            page.get_by_role('button',name='Library',exact=True).click()
            page.get_by_role('button',name='Knowledge shelf',exact=True).click()
            page.get_by_role('textbox',name='Search saved ideas').fill('reduce coupling')
            expect(page.locator('.knowledge-grid article')).to_have_count(1)
            page.get_by_role('button',name='Read source',exact=False).click()
            expect(page.get_by_role('spinbutton',name='Reading location')).to_have_value('1')
            page.screenshot(path='/tmp/yapoc-reading-tools.png')
            page.set_viewport_size({'width':390,'height':844})
            if page.get_by_role('button',name='Close navigation',exact=True).is_visible():page.get_by_role('button',name='Close navigation',exact=True).click()
            page.get_by_role('button',name='Close reading assistant',exact=True).click()
            select()
            bubble=page.get_by_role('toolbar',name='Passage actions').bounding_box()
            assert bubble['x']>=0 and bubble['x']+bubble['width']<=391,bubble
            page.screenshot(path='/tmp/yapoc-reading-tools-mobile.png')
            page.emulate_media(reduced_motion='reduce')
            assert page.locator('.study-cat b').evaluate('el=>getComputedStyle(el).animationName')=='none'
            assert not errors,errors
            print('PASS: selection actions, styles, translation, timeline, notes/shelf, map preview/create/source, mobile, reduced motion')
        finally:
            page.request.delete(base)
            for board in boards:page.request.delete('http://127.0.0.1:5173/api/whiteboard/boards/'+board)
            browser.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scroll',action='store_true')
    check(parser.parse_args().scroll)
