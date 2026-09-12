"""Read-only tools for source-grounded reading and design workflows."""
import json
from . import BaseTool


class BookListTool(BaseTool):
    name = 'book_list'
    description = 'List uploaded books, stable IDs, formats and saved reading positions.'
    input_schema = {'type':'object','properties':{}}

    async def execute(self, **params):
        from app.backend.services.books import list_books
        return json.dumps(list_books(), separators=(',', ':'))


class BookReadTool(BaseTool):
    name = 'book_read'
    description = 'Retrieve excerpts within an explicit book page/chapter range. Locations are physical PDF pages or EPUB spine chapters. Preserve source citations. Do not exceed the reader position without explicit user permission.'
    input_schema = {'type':'object','properties':{
        'book_id':{'type':'string'},'start':{'type':'integer','minimum':1},
        'end':{'type':'integer','minimum':1},'question':{'type':'string'},
    },'required':['book_id','start','end']}

    async def execute(self, **params):
        from app.backend.services.books import passages
        return json.dumps(passages(params['book_id'],params['start'],params['end'],params.get('question','')),separators=(',', ':'))
