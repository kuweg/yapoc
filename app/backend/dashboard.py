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
            scope['path'] = scope['path'][4:]
            scope['raw_path'] = scope['path'].encode('utf-8')
        await self.app(scope, receive, send)


def mount_dashboard(app, directory: Path) -> None:
    # Must be called after API routes; the root mount is the final fallback.
    app.add_middleware(ApiPrefixMiddleware)
    if (directory / 'index.html').is_file():
        app.mount('/', StaticFiles(directory=str(directory), html=True), name='dashboard')
