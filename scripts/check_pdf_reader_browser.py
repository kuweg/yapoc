"""Validate the original PDF selection layer with disposable PDFs and mocked AI."""
import argparse
import io
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
from playwright.sync_api import sync_playwright,expect


def fixture():
    writer=PdfWriter()
    for title in ('Systems communicate through events.','A second page with a queue.'):
        page=writer.add_blank_page(width=400,height=500)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject();stream.set_data(f'BT /F1 14 Tf 30 430 Td ({title}) Tj 0 -30 Td (Read this original PDF with book actions.) Tj ET'.encode())
        page[NameObject('/Contents')]=writer._add_object(stream)
    data=io.BytesIO();writer.write(data);return data.getvalue()


def check(url='http://127.0.0.1:5173'):
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];asks=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(url)
        response=page.request.post(url+'/api/books',multipart={'file':{'name':'PDF browser fixture.pdf','mimeType':'application/pdf','buffer':fixture()}})
        assert response.ok,response.text()
        book=response.json();base=url+'/api/books/'+book['id']
        def answer(route):
            body=route.request.post_data_json;asks.append(body)
            route.fulfill(json={'id':str(len(asks)),'question':body['action'],'answer':'Original PDF selection works [S1].','scope':{'start':body['start'],'end':body['end'],'action':body['action']},'citations':[{'id':'S1','number':body['start'],'label':'1','excerpt':body['selection']}]})
        page.route('**/books/*/ask',answer)
        def select(number=1):
            span=page.locator(f'.original-pdf-page[data-section="{number}"] .pdf-text-layer span').first
            expect(span).to_be_attached()
            span.evaluate("""el=>{const range=document.createRange();range.selectNodeContents(el);const s=getSelection();s.removeAllRanges();s.addRange(range);el.dispatchEvent(new PointerEvent('pointerup',{bubbles:true}));}""")
            expect(page.get_by_role('toolbar',name='Passage actions')).to_be_visible()
            return span
        try:
            page.get_by_role('button',name='Books',exact=True).click()
            page.locator('.books-cover').filter(has_text=book['title']).click()
            page.get_by_role('button',name='Original PDF',exact=True).click()
            word=page.locator('.original-pdf-page[data-section="1"] .pdf-text-layer span').first
            word.dblclick(position={'x':12,'y':5})
            expect(page.get_by_role('toolbar',name='Passage actions')).to_be_visible()
            assert page.evaluate('getSelection().toString()').strip()=='Systems'
            select()
            page.get_by_role('toolbar',name='Passage actions').get_by_role('button',name='Translate',exact=True).click()
            expect(page.locator('.reading-turn')).to_have_count(1)
            assert 'Systems communicate' in asks[-1]['selection']
            assert asks[-1]['start']==1 and asks[-1]['action']=='translate'
            span=select()
            # The book menu cancels the browser's context menu only for selected PDF text.
            assert span.evaluate("el=>!el.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}))")
            page.get_by_role('toolbar',name='Passage actions').get_by_role('button',name='Highlight',exact=True).click()
            expect(page.locator('.pdf-highlight-layer span').first).to_be_attached()
            assert page.request.get(base+'/annotations').json()[0]['section']==1
            page.get_by_role('button',name='Zoom in PDF',exact=True).click()
            select()
            page.get_by_role('button',name='Dismiss passage actions',exact=True).click()
            page.get_by_role('button',name='Fit width',exact=True).click()
            page.get_by_role('button',name='Next',exact=True).click()
            select(2)
            page.get_by_role('toolbar',name='Passage actions').get_by_role('button',name='Explain',exact=True).click()
            expect(page.locator('.reading-turn')).to_have_count(2)
            assert asks[-1]['start']==2 and 'second page' in asks[-1]['selection']
            page.wait_for_timeout(1000)
            page.get_by_role('button',name='Library',exact=True).click()
            page.locator('.books-cover').filter(has_text=book['title']).click()
            expect(page.locator('.original-pdf-reader')).to_be_visible()
            expect(page.get_by_role('spinbutton',name='Reading location')).to_have_value('2')
            select(2)
            page.get_by_role('button',name='Dismiss passage actions',exact=True).click()
            page.screenshot(path='/tmp/yapoc-original-pdf.png')
            page.set_viewport_size({'width':390,'height':844})
            if page.get_by_role('button',name='Close navigation',exact=True).is_visible():page.get_by_role('button',name='Close navigation',exact=True).click()
            page.get_by_role('button',name='Close reading assistant',exact=True).click()
            select(2)
            box=page.get_by_role('toolbar',name='Passage actions').bounding_box()
            assert box['x']>=0 and box['x']+box['width']<=391,box
            page.screenshot(path='/tmp/yapoc-original-pdf-mobile.png')
            assert not errors,errors
            print('PASS: original PDF selection, context menu, AI sources, saved highlights, zoom, navigation/resume, mobile')
        finally:
            page.request.delete(base)
            browser.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:5173')
    check(parser.parse_args().url)
