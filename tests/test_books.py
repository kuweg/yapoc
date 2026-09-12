import io
import json
import threading
import zipfile
from types import SimpleNamespace
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.backend.services import books


@pytest.fixture
def library(tmp_path, monkeypatch):
    from app.utils import db
    monkeypatch.setattr(db, '_DB_PATH', tmp_path/'books.db')
    monkeypatch.setattr(db, '_local', threading.local())
    monkeypatch.setattr(books, 'settings', SimpleNamespace(project_root=tmp_path, default_adapter='test',default_model='test'))
    db.init_schema()
    from app.backend.routers.books import router
    app=FastAPI(); app.include_router(router)
    yield TestClient(app)
    db.get_db().close()


def epub():
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:
        z.writestr('META-INF/container.xml','<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
        z.writestr('OPS/book.opf','''<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/">
        <metadata><dc:title>Test Book</dc:title><dc:creator>Reader</dc:creator></metadata>
        <manifest><item id="two" href="two.xhtml"/><item id="one" href="one.xhtml"/></manifest>
        <spine><itemref idref="one"/><itemref idref="two"/></spine></package>''')
        z.writestr('OPS/one.xhtml','<h1>Beginning</h1><p>Systems communicate through events.</p><script>bad()</script>')
        z.writestr('OPS/two.xhtml','<h1>Later</h1><p>The secret ending is a queue.</p>')
    return data.getvalue()


def test_import_reader_progress_annotations_and_export(library):
    response=library.post('/books',files={'file':('sample.epub',epub(),'application/epub+zip')})
    assert response.status_code==201,response.text
    b=response.json(); base=f'/books/{b["id"]}'
    assert b['title']=='Test Book' and b['total']==2
    page=library.get(base+'/sections/1').json()
    assert page['title']=='Beginning' and 'bad()' not in page['text']
    assert library.put(base+'/progress',json={'position':2,'offset':.4,'preferences':{'theme':'dark'}}).status_code==200
    assert library.get(base).json()['offset']==.4
    assert library.get(base).json()['preferences']['theme']=='dark'
    assert library.post(base+'/annotations',json={'section':1,'quote':'Systems communicate through events.','kind':'highlight'}).status_code==201
    assert library.post(base+'/annotations',json={'section':1,'quote':'invented'}).status_code==400
    exported=library.get(base+'/export').json()
    assert len(exported['annotations'])==1
    assert library.get(base+'/search',params={'q':'events'}).json()[0]['number']==1
    assert library.put(base+'/progress',json={'position':3}).status_code==400
    assert library.delete(base).status_code==204
    assert library.get(base).status_code==404


def test_scanned_pdf_and_bad_files(library):
    from pypdf import PdfWriter
    writer=PdfWriter();writer.add_blank_page(width=300,height=400);out=io.BytesIO();writer.write(out)
    b=library.post('/books',files={'file':('scan.pdf',out.getvalue())}).json()
    assert b['status']=='needs_ocr'
    assert library.get(f'/books/{b["id"]}/original').content.startswith(b'%PDF')
    assert library.post('/books',files={'file':('broken.epub',b'bad')}).status_code==400
    assert library.post('/books',files={'file':('bad.exe',b'bad')}).status_code==400


async def test_scoped_ai_citations_history_and_spoilers(library,monkeypatch):
    from app.utils import adapters
    from app.utils import agent_settings
    captured={}
    class Adapter:
        async def complete(self,**kwargs):
            captured.update(kwargs)
            return 'Events connect systems [S1]. Unsupported [S99].'
    monkeypatch.setattr(adapters,'get_adapter',lambda _:Adapter())
    monkeypatch.setattr(agent_settings,'resolve_agent',lambda _:None)
    b=books.import_book(epub(),'sample.epub')
    answer=await books.ask(b['id'],'What connects systems?',1,2)
    assert 'secret ending' not in captured['user_message']
    assert answer['citations'][0]['number']==1
    assert '[S99]' not in answer['answer']
    assert len(books.history(b['id']))==1
    with pytest.raises(HTTPException):
        await books.ask(b['id'],'Later?',2,2)
    with pytest.raises(HTTPException):
        books.passages(b['id'],1,1,selection='Not in book')
    context=books.build_book_context('Read @book:"Test Book":pages:1-1')
    assert b['id'] in context and 'secret ending' not in context


async def test_ai_error_does_not_leak_provider_secrets(library,monkeypatch):
    from app.utils import adapters,agent_settings
    class Adapter:
        async def complete(self,**kwargs): raise RuntimeError('private-token')
    monkeypatch.setattr(adapters,'get_adapter',lambda _:Adapter())
    monkeypatch.setattr(agent_settings,'resolve_agent',lambda _:None)
    b=books.import_book(epub(),'book.epub')
    with pytest.raises(HTTPException) as exc: await books.ask(b['id'],'Explain',1,1)
    assert exc.value.status_code==502 and 'private-token' not in exc.value.detail
    assert books.history(b['id'])==[]


def test_pdf_text_range_citations_and_ambiguous_mentions(library):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer=PdfWriter()
    for text in ('First page about apples','Second page about oranges'):
        page=writer.add_blank_page(width=400,height=500)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject();stream.set_data(f'BT /F1 12 Tf 30 400 Td ({text}) Tj ET'.encode())
        page[NameObject('/Contents')]=writer._add_object(stream)
    data=io.BytesIO();writer.write(data)
    b=books.import_book(data.getvalue(),'Citrus.pdf')
    evidence=books.passages(b['id'],2,2,'oranges')
    assert all(p['number']==2 for p in evidence)
    assert 'oranges' in evidence[0]['text'] and 'apples' not in evidence[0]['text']
    books.import_book(data.getvalue(),'Citrus.pdf')
    with pytest.raises(HTTPException,match='ambiguous'):
        books.build_book_context('@book:Citrus:pages:1-1')
