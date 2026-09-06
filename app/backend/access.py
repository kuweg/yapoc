"""Access control for HTTP and WebSocket surfaces, including proxied callers."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from starlette.responses import JSONResponse
from app.config import settings

router = APIRouter()


def is_loopback(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return value == 'localhost'


def cookie_value() -> str:
    return hmac.new(settings.backend_api_token.encode(), b'yapoc-browser-access', hashlib.sha256).hexdigest()


def authorized(scope: dict) -> bool:
    headers = {k.decode().lower(): v.decode() for k, v in scope.get('headers', [])}
    secret = settings.backend_api_token
    if secret:
        bearer = headers.get('authorization', '')
        if bearer.startswith('Bearer ') and hmac.compare_digest(bearer[7:], secret):
            return True
        cookies = SimpleCookie()
        try:
            cookies.load(headers.get('cookie', ''))
            token = cookies.get('yapoc_access')
            if token and hmac.compare_digest(token.value, cookie_value()):
                origin = headers.get('origin')
                return not origin or urlsplit(origin).netloc == headers.get('host')
        except Exception:
            pass
        return False
    # An unconfigured backend is usable locally only. Treat forwarded client
    # claims conservatively; they can restrict local access but never grant it.
    client = scope.get('client') or ('', 0)
    host = urlsplit('//' + headers.get('host', '')).hostname or ''
    origin = headers.get('origin', '')
    forwarded = headers.get('x-forwarded-for', '').split(',')[0].strip()
    return (is_loopback(client[0]) and is_loopback(host)
            and (not origin or is_loopback(urlsplit(origin).hostname or ''))
            and (not forwarded or is_loopback(forwarded)))


class AccessMiddleware:
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] not in {'http', 'websocket'}:
            return await self.app(scope, receive, send)
        path = scope.get('path', '')
        # Static assets and the login form contain no runtime data.
        public = path in {'/', '/index.html', '/health', '/auth/login', '/auth/status'} or path.startswith(('/assets/', '/webhook/', '/admin/'))
        if not public and not authorized(scope):
            if scope['type'] == 'websocket':
                await send({'type': 'websocket.close', 'code': 4401})
            else:
                await JSONResponse({'detail': 'Backend authentication required'}, status_code=401)(scope, receive, send)
            return
        return await self.app(scope, receive, send)


class Login(BaseModel):
    token: str


@router.get('/auth/status')
async def auth_status(request: Request):
    return {'authenticated': authorized(request.scope), 'configured': bool(settings.backend_api_token)}


@router.post('/auth/login')
async def login(body: Login, request: Request, response: Response):
    if not settings.backend_api_token or not hmac.compare_digest(body.token, settings.backend_api_token):
        raise HTTPException(401, 'Invalid backend token')
    response.set_cookie('yapoc_access', cookie_value(), httponly=True, samesite='strict',
                        secure=request.url.scheme == 'https', max_age=86400, path='/')
    return {'authenticated': True}
