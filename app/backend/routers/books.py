"""Books library and reader API."""
import json
from typing import Literal
from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from app.backend.services import books, book_maps
from app.utils.db import get_db

router = APIRouter(prefix='/books', tags=['books'])


class Progress(BaseModel):
    position: int = Field(ge=1)
    offset: float = Field(default=0, ge=0, le=1)
    finished: bool = False
    preferences: dict = Field(default_factory=dict)


class Annotation(BaseModel):
    section: int = Field(ge=1)
    kind: Literal['bookmark', 'highlight', 'note'] = 'highlight'
    quote: str = Field(default='', max_length=10000)
    note: str = Field(default='', max_length=10000)
    color: Literal['amber', 'mint', 'rose'] = 'amber'


class Question(BaseModel):
    question: str = Field(default='', max_length=8000)
    start: int = Field(ge=1)
    end: int = Field(ge=1)
    selection: str = Field(default='', max_length=10000)
    action: Literal['ask','explain','summarize','quiz','guide','flashcards','connect','translate','example'] = 'ask'
    explanation_style: Literal['beginner','technical','analogy','worked_example'] = 'beginner'
    language: str = Field(default='English', min_length=1, max_length=60)
    avoid_spoilers: bool = True


@router.get('')
def library(): return books.list_books()


@router.get('/shelf')
def shelf(q: str = '', offset: int = 0):
    return books.knowledge_shelf(q, max(0, offset))


@router.post('', status_code=201)
async def upload(file: UploadFile = File(...)):
    data = await file.read(50_000_001)
    try: return await run_in_threadpool(books.import_book, data, file.filename or '')
    finally: await file.close()


@router.get('/{book_id}')
def detail(book_id: str): return books.book(book_id)


@router.get('/{book_id}/contents')
def contents(book_id: str): return books.contents(book_id)


@router.get('/{book_id}/sections/{number}')
def section(book_id: str, number: int): return books.section(book_id, number)


@router.get('/{book_id}/original')
def original(book_id: str):
    b = books.book(book_id)
    return FileResponse(books.library_root() / f'{b["id"]}.{b["format"]}',
                        media_type='application/pdf' if b['format']=='pdf' else 'application/epub+zip',
                        headers={'X-Content-Type-Options':'nosniff'})


@router.put('/{book_id}/progress')
def progress(book_id: str, request: Progress): return books.save_progress(book_id, **request.model_dump())


@router.get('/{book_id}/annotations')
def annotations(book_id: str): return books.annotations(book_id)


@router.post('/{book_id}/annotations', status_code=201)
def annotate(book_id: str, request: Annotation):
    return books.annotate(book_id, request.section, request.kind, request.quote, request.note, request.color)


@router.delete('/{book_id}/annotations/{annotation_id}', status_code=204)
def remove_annotation(book_id: str, annotation_id: str):
    books.book(book_id)
    with get_db() as db: db.execute('DELETE FROM book_annotations WHERE book_id=? AND id=?', (book_id,annotation_id))
    return Response(status_code=204)


@router.get('/{book_id}/search')
def search(book_id: str, q: str = ''):
    books.book(book_id)
    if not q.strip(): return []
    return [dict(r) for r in get_db().execute('SELECT number,label,title,substr(text,max(1,instr(lower(text),lower(?))-80),300) excerpt FROM book_sections WHERE book_id=? AND instr(lower(text),lower(?))>0 ORDER BY number LIMIT 100', (q,book_id,q))]


@router.get('/{book_id}/messages')
def messages(book_id: str): return books.history(book_id)


@router.post('/{book_id}/ask')
async def ask(book_id: str, request: Question): return await books.ask(book_id, **request.model_dump())


@router.get('/{book_id}/export')
def export(book_id: str):
    b = books.book(book_id)
    return Response(json.dumps({'book':b,'annotations':books.annotations(book_id),'conversations':books.history(book_id)},ensure_ascii=False,indent=2),
                    media_type='application/json', headers={'Content-Disposition':f'attachment; filename="reading-{b["id"]}.json"'})


@router.post('/{book_id}/artifact')
def export_artifact(book_id: str):
    from app.backend.services.artifacts import register_artifact
    b = books.book(book_id)
    from uuid import uuid4
    path = books.settings.project_root / 'data' / 'generated' / 'books' / f'reading-{uuid4().hex}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'book': b, 'annotations': books.annotations(book_id), 'conversations': books.history(book_id)},ensure_ascii=False,indent=2),encoding='utf-8')
    return register_artifact(path, source_agent='reader', metadata={'book_id':book_id})


@router.delete('/{book_id}', status_code=204)
def remove(book_id: str):
    b = books.book(book_id)
    with get_db() as db:
        for table in ('book_sections','book_annotations','book_messages'):
            db.execute(f'DELETE FROM {table} WHERE book_id=?', (book_id,))
        db.execute('DELETE FROM books WHERE id=?', (book_id,))
    (books.library_root() / f'{b["id"]}.{b["format"]}').unlink(missing_ok=True)
    return Response(status_code=204)


@router.post('/{book_id}/map/preview')
async def map_preview(book_id: str, request: book_maps.MapRequest):
    return await book_maps.preview(book_id, **request.model_dump())


@router.post('/{book_id}/map', status_code=201)
def map_create(book_id: str, request: book_maps.MapDraft):
    return book_maps.create(book_id, request)
