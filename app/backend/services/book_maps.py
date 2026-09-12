"""Bounded, source-linked reading maps; never replace an existing canvas."""
import json
from pydantic import BaseModel, Field, ValidationError
from fastapi import HTTPException
from app.backend.services import books
from app.utils import whiteboard


class Concept(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(max_length=3000)
    number: int = Field(ge=1)
    excerpt: str = Field(min_length=1, max_length=10000)


class Connection(BaseModel):
    source: str = Field(min_length=1, max_length=40)
    target: str = Field(min_length=1, max_length=40)
    label: str = Field(default='related to', max_length=80)


class MapDraft(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    nodes: list[Concept] = Field(min_length=1, max_length=12)
    edges: list[Connection] = Field(default_factory=list, max_length=24)


class MapRequest(BaseModel):
    start: int = Field(ge=1)
    end: int = Field(ge=1)
    avoid_spoilers: bool = True


def validate_sources(book_id, draft):
    keys = {n.key for n in draft.nodes}
    if len(keys) != len(draft.nodes) or any(e.source not in keys or e.target not in keys or e.source == e.target for e in draft.edges):
        raise HTTPException(422, 'Map connections must link distinct, existing concepts.')
    for node in draft.nodes:
        if node.excerpt not in books.section(book_id, node.number)['text']:
            raise HTTPException(422, 'A map source does not match its book location.')


async def preview(book_id, start, end, avoid_spoilers=True):
    turn = await books.ask(book_id, 'Map the main ideas and their relationships.', start, end,
                           action='concept_map', avoid_spoilers=avoid_spoilers)
    try:
        payload = json.loads(turn['answer'])
        citations = {c['id']: c for c in turn['citations']}
        nodes = []
        for node in payload['nodes']:
            citation = citations[node['source_id']]
            nodes.append({**node, 'number': citation['number'], 'excerpt': citation['excerpt']})
        draft = MapDraft(name=f"{books.book(book_id)['title'][:65]} · {start}–{end}", nodes=nodes, edges=payload.get('edges', []))
    except (ValueError, TypeError, KeyError, ValidationError):
        raise HTTPException(502, 'The assistant returned an invalid concept map. Retry with a smaller range.') from None
    validate_sources(book_id, draft)
    return draft.model_dump()


def create(book_id, draft):
    validate_sources(book_id, draft)
    book = books.book(book_id)
    board = whiteboard.create_board(draft.name, f"Reading map from {book['title']}", created_by='reader')
    try:
        cards = [dict(key=n.key, title=n.title, body=n.body, kind='note', color='mint',
                      x=80+(i%3)*320, y=80+(i//3)*270, width=280, height=220,
                      details={'book_id': book_id, 'source_location': n.number,
                               'source_reference': f'@book:{book_id}:pages:{n.number}-{n.number}',
                               'source_excerpt': n.excerpt}) for i,n in enumerate(draft.nodes)]
        return whiteboard.apply_design(board['id'], cards, [e.model_dump() for e in draft.edges], 'reader')
    except Exception:
        whiteboard.delete_board(board['id'])
        raise HTTPException(500, 'The reading map could not be saved. Please retry.') from None
