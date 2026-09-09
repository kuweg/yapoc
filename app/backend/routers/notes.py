from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.backend.services import notes

router = APIRouter(prefix='/notes', tags=['notes'])


class CreateNote(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    content: str | None = Field(default=None, max_length=200_000)


class SaveNote(BaseModel):
    content: str = Field(max_length=200_000)
    revision: str


class TrashNote(BaseModel):
    revision: str


@router.get('')
def index():
    return notes.list_notes()


@router.post('', status_code=201)
def create(request: CreateNote):
    return notes.create_note(request.title, request.content)


@router.get('/{note_id}')
def read(note_id: str):
    return notes.read_note(note_id)


@router.put('/{note_id}')
def save(note_id: str, request: SaveNote):
    return notes.save_note(note_id, request.content, request.revision)


@router.post('/{note_id}/trash')
def trash(note_id: str, request: TrashNote):
    notes.trash_note(note_id, request.revision)
    return {'status': 'trashed'}
