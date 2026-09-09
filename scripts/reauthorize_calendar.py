"""Re-authorize the shared Google OAuth app to include the Calendar scope.

The Gmail and Calendar plugins share one OAuth app (same client_id/client_secret)
and one refresh token, persisted at data/plugins/gmail/config.json. The existing
refresh token was granted only for the Gmail scope, so the Calendar API returns
403 (insufficient scope).

This script walks you through re-authorizing the SAME app with BOTH scopes:

  1. Prints a Google consent URL (with gmail.modify + calendar scopes).
  2. You open it in a browser, approve, and paste back the `code` from the
     redirect URL (the `code=...` query param).
  3. The script exchanges the code for a NEW refresh token carrying both scopes
     and writes it back into data/plugins/gmail/config.json.

Usage:
    python scripts/reauthorize_calendar.py

Requirements: httpx (already a project dependency).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "data" / "plugins" / "gmail" / "config.json"

TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"

# Scopes: keep Gmail (existing) + add Calendar.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]

# Redirect URI must match one configured in the Google Cloud OAuth client.
# "Installed app" clients use urn:ietf:wg:oauth:2.0:oob (out-of-band) or
# http://localhost. Adjust if your client uses a different redirect URI.
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"ERROR: no config at {CONFIG_PATH}")
        print("Configure the Gmail plugin first (Plugins tab).")
        sys.exit(1)
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def build_consent_url(client_id: str) -> str:
    params = httpx.QueryParams(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",   # force a refresh token
            "prompt": "consent",        # force re-consent so new scopes are granted
        }
    )
    return f"{AUTH_URL}?{params}"


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
        print(f"ERROR exchanging code: {resp.status_code} {resp.text}")
        sys.exit(1)
    return resp.json()


def main() -> None:
    cfg = load_config()
    client_id = cfg.get("client_id") or ""
    client_secret = cfg.get("client_secret") or ""
    if not (client_id and client_secret):
        print("ERROR: client_id/client_secret missing from gmail config.")
        sys.exit(1)

    url = build_consent_url(client_id)
    print("=" * 72)
    print("Open this URL in your browser and approve BOTH scopes:")
    print()
    print(url)
    print()
    print("After approving, Google redirects you to a URL containing `code=...`.")
    print("Copy the value of the `code` parameter (everything after `code=`,")
    print("up to the next `&` or end of URL).")
    print("=" * 72)

    code = input("\nPaste the authorization code: ").strip()
    if not code:
        print("No code provided — aborting.")
        sys.exit(1)

    token_data = exchange_code(client_id, client_secret, code)
    refresh_token = token_data.get("refresh_token") or ""
    access_token = token_data.get("access_token") or ""

    if not refresh_token:
        print(
            "WARNING: no refresh_token returned. This happens if the app was "
            "already authorized (Google only issues a refresh token on first "
            "consent). Re-run with prompt=consent, or revoke access first at "
            "https://myaccount.google.com/permissions and try again."
        )
        # Still save the access token so the Calendar call can be tested now.
    else:
        print("Got a new refresh token carrying both scopes.")

    cfg["refresh_token"] = refresh_token or cfg.get("refresh_token", "")
    cfg["access_token"] = access_token
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"\nSaved to {CONFIG_PATH}")
    print("Restart the backend (or reload plugins) and test calendar_list_events.")


if __name__ == "__main__":
    main()
