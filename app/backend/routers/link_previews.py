"""Bounded public-web previews with DNS-rebinding and local-network protection."""
import asyncio
import hashlib
import ipaddress
import socket
import ssl
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from fastapi import APIRouter, Query, Response

router = APIRouter(prefix="/link-previews", tags=["previews"])
_slots = asyncio.Semaphore(4)
_cache: dict[str, tuple[float, dict]] = {}


def validate_target(url: str, addresses: list[tuple]):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Unsupported URL")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in (80, 443):
        raise ValueError("Unsupported port")
    if not addresses or any(not ipaddress.ip_address(item[4][0].split("%", 1)[0]).is_global for item in addresses):
        raise ValueError("Public addresses only")
    return parsed, port, addresses[0]


async def resolve_target(url: str):
    parsed = urlsplit(url)
    if not parsed.hostname:
        raise ValueError("Unsupported URL")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = await asyncio.get_running_loop().getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    return validate_target(url, addresses)


async def read_chunked(reader: asyncio.StreamReader, limit: int) -> bytes:
    body = bytearray()
    while True:
        line = await reader.readline()
        size = int(line.split(b";", 1)[0].strip(), 16)
        if not size:
            while await reader.readline() not in (b"\r\n", b"\n", b""):
                pass
            return bytes(body)
        if len(body) + size > limit:
            raise ValueError("Preview too large")
        body.extend(await reader.readexactly(size))
        if await reader.readexactly(2) != b"\r\n":
            raise ValueError("Invalid response")


async def read_response(reader: asyncio.StreamReader, limit: int):
    header = await reader.readuntil(b"\r\n\r\n")
    if len(header) > 65_536:
        raise ValueError("Invalid response")
    lines = header.decode("latin-1").split("\r\n")
    status = int(lines[0].split(" ", 2)[1])
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.lower()] = value.strip()
    if headers.get("transfer-encoding", "").lower() == "chunked":
        body = await read_chunked(reader, limit)
    elif "content-length" in headers:
        length = int(headers["content-length"])
        if length > limit:
            raise ValueError("Preview too large")
        body = await reader.readexactly(length)
    else:
        body = await reader.read(limit + 1)
        if len(body) > limit:
            raise ValueError("Preview too large")
    return status, headers, body


async def fetch_public(url: str, limit: int):
    for _ in range(4):
        parsed, port, address = await resolve_target(url)
        context = ssl.create_default_context() if parsed.scheme == "https" else None
        async with asyncio.timeout(6):
            reader, writer = await asyncio.open_connection(
                address[4][0], port, family=address[0], ssl=context,
                server_hostname=parsed.hostname if context else None,
            )
            try:
                target = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
                host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
                request = (
                    f"GET {target} HTTP/1.1\r\nHost: {host}\r\n"
                    "User-Agent: YAPOC-LinkPreview/1.0\r\nAccept-Encoding: identity\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("ascii")
                writer.write(request)
                await writer.drain()
                status, headers, body = await read_response(reader, limit)
            finally:
                writer.close()
                await writer.wait_closed()
        if status in (301, 302, 303, 307, 308):
            location = headers.get("location")
            if not location:
                raise ValueError("Invalid redirect")
            url = urljoin(url, location)
            continue
        if status != 200:
            raise ValueError("Preview unavailable")
        mime = headers.get("content-type", "").split(";", 1)[0].lower()
        return url, mime, body
    raise ValueError("Too many redirects")


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values: dict[str, str] = {}
        self.title = ""
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            key = attrs.get("property") or attrs.get("name")
            if key in ("og:title", "og:description", "description", "og:image"):
                self.values[key] = (attrs.get("content") or "")[:2000]

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title = (self.title + data)[:300]


async def metadata(url: str):
    final, mime, body = await fetch_public(url, 512_000)
    if mime not in ("text/html", "application/xhtml+xml"):
        return {}
    parser = Metadata()
    parser.feed(body.decode("utf-8", errors="replace"))
    image = urljoin(final, parser.values["og:image"]) if parser.values.get("og:image") else None
    return {
        "title": (parser.values.get("og:title") or parser.title).strip()[:300],
        "description": (parser.values.get("og:description") or parser.values.get("description") or "").strip()[:500],
        "image": image,
    }


@router.get("")
async def preview(url: str = Query(max_length=2048)):
    key = hashlib.sha256(url.encode()).hexdigest()
    cached = _cache.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    async with _slots:
        try:
            result = await metadata(url)
        except Exception:
            result = {}
    if len(_cache) >= 200:
        _cache.pop(next(iter(_cache)))
    _cache[key] = (time.monotonic() + 600, result)
    return result


@router.get("/image")
async def image(url: str = Query(max_length=2048)):
    async with _slots:
        try:
            _, mime, body = await fetch_public(url, 2_000_000)
            if mime not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
                raise ValueError()
            return Response(body, media_type=mime, headers={
                "Cache-Control": "private, max-age=600",
                "X-Content-Type-Options": "nosniff",
            })
        except Exception:
            return Response(status_code=404)
