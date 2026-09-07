"""Serve the release dashboard and API from the same port."""
from pathlib import Path

from fastapi.staticfiles import StaticFiles


class ApiPrefixMiddleware:
    """Match Vite's /api proxy in packaged installations."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and scope['path'].startswith('/api/'):
            scope = dict(scope)
            original_path = scope['path']
            scope['path'] = original_path[4:]
            raw_path = scope.get('raw_path', original_path.encode('utf-8'))
            query_start = raw_path.find(b'?')
            query = raw_path[query_start:] if query_start >= 0 else b''
            scope['raw_path'] = scope['path'].encode('utf-8') + query
        await self.app(scope, receive, send)


def mount_dashboard(app, directory: Path) -> None:
    # Must be called after API routes; the root mount is the final fallback.
    app.add_middleware(ApiPrefixMiddleware)
    if (directory / 'index.html').is_file():
        app.mount('/', StaticFiles(directory=str(directory), html=True), name='dashboard')
