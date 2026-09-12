"""Static previews on distinct loopback origins. No application APIs or secrets."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import unquote, urlsplit
from app.utils.secrets import credential_path

_servers = {}


class PreviewHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_): pass
    def permitted(self):
        root = Path(self.directory).resolve()
        candidate = (root / unquote(urlsplit(self.path).path).lstrip('/')).resolve()
        if candidate.is_dir(): candidate = (candidate / 'index.html').resolve()
        return candidate.is_relative_to(root) and not credential_path(candidate.relative_to(root)) and candidate.is_file()
    def do_GET(self):
        if not self.permitted(): self.send_error(404); return
        super().do_GET()
    def do_HEAD(self):
        if not self.permitted(): self.send_error(404); return
        super().do_HEAD()
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "connect-src 'none'; form-action 'none'; frame-ancestors 'self' http://localhost:* http://127.0.0.1:*")
        super().end_headers()


def start_preview(key, root):
    if not (root / 'index.html').is_file(): return None
    if key in _servers: return f'http://127.0.0.1:{_servers[key].server_port}'
    if len(_servers) >= 4:
        oldest = _servers.pop(next(iter(_servers)))
        oldest.shutdown(); oldest.server_close()
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(PreviewHandler, directory=str(root)))
    Thread(target=server.serve_forever, daemon=True).start()
    _servers[key] = server
    return f'http://127.0.0.1:{server.server_port}'


def stop_preview(key):
    server = _servers.pop(key, None)
    if server:
        server.shutdown()
        server.server_close()


def stop_previews():
    for server in _servers.values(): server.shutdown(); server.server_close()
    _servers.clear()


def preview_url(key):
    server = _servers.get(key)
    return f'http://127.0.0.1:{server.server_port}' if server else None
