#!/usr/bin/env python3
"""Gmail OAuth2 helper — obtain a refresh token for the Gmail plugin.

Reads client_id/client_secret from data/plugins/gmail/config.json, runs a
loopback OAuth2 flow (Google's supported flow for installed/desktop apps),
and writes the resulting refresh_token + access_token back into the plugin
config.

The deprecated `urn:ietf:wg:oauth:2.0:oob` out-of-band flow is no longer
supported by Google for new clients, so this uses a local HTTP server on
http://localhost:8765/ as the redirect target. The browser is opened
automatically; the authorization code is captured from the redirect and
exchanged for tokens without any manual copy/paste.

Usage:
    poetry run python scripts/gmail_oauth.py
"""

import json
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "data" / "plugins" / "gmail" / "config.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

# Loopback redirect for "Desktop app" OAuth clients. Must match the redirect
# URI registered on the Google Cloud OAuth client.
REDIRECT_URI = "http://localhost:8765/"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"[!] Config not found: {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)
    return json.loads(CONFIG_PATH.read_text())


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def build_auth_url(client_id: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    resp = httpx.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"[!] Token exchange failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)
    return resp.json()


def run_loopback_server() -> tuple[HTTPServer, dict]:
    """Start a local HTTP server to capture the OAuth redirect. Returns the
    server and a shared dict that will hold the captured authorization code."""
    captured: dict = {"code": None}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            code = params.get("code", [None])[0]
            error = params.get("error", [None])[0]

            if error:
                captured["error"] = error
                body = f"<h1>Authorization failed</h1><p>{error}</p>".encode()
            elif code:
                captured["code"] = code
                body = b"<h1>Authorization successful</h1><p>You can close this window.</p>"
            else:
                body = b"<h1>No authorization code received</h1>"

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass  # silence request logging

    server = HTTPServer(("localhost", 8765), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, captured


def main() -> None:
    cfg = load_config()
    client_id = cfg.get("client_id", "")
    client_secret = cfg.get("client_secret", "")

    if not client_id or not client_secret:
        print("[!] client_id and client_secret must be set in the plugin config first.", file=sys.stderr)
        sys.exit(1)

    server, captured = run_loopback_server()

    url = build_auth_url(client_id)
    print("Opening your browser to authorize Gmail access...\n")
    print(url)
    print()
    webbrowser.open(url)

    print("Waiting for authorization (browser will redirect to localhost:8765)...")
    while captured["code"] is None and captured.get("error") is None:
        # Block until the redirect arrives.
        import time
        time.sleep(0.5)

    server.shutdown()

    if captured.get("error"):
        print(f"[!] Authorization failed: {captured['error']}", file=sys.stderr)
        sys.exit(1)

    code = captured["code"]
    tokens = exchange_code(client_id, client_secret, code)
    cfg["refresh_token"] = tokens.get("refresh_token", "")
    cfg["access_token"] = tokens.get("access_token", "")
    save_config(cfg)

    print("\n[OK] Tokens saved to", CONFIG_PATH)
    print("     refresh_token:", "SET" if cfg["refresh_token"] else "MISSING")
    print("     access_token: ", "SET" if cfg["access_token"] else "MISSING")


if __name__ == "__main__":
    main()
