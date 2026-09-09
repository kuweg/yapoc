"""Gmail plugin — real Gmail API integration via OAuth2.

Tools:
  - gmail_send   : send an email
  - gmail_list   : list recent messages in the inbox
  - gmail_read   : read a single message by id
  - gmail_search : search messages with a Gmail query

Configuration is read from data/plugins/gmail/config.json (persisted via the
Plugins tab). Required fields: client_id, client_secret, refresh_token.
The access token is refreshed automatically using the refresh token when it
is missing or expired.

The Gmail API is called directly over HTTPS with httpx (no google client
library dependency).
"""

from __future__ import annotations

import base64
import json
from email.message import EmailMessage
from typing import Any

import httpx

from app.utils.tools import BaseTool
from app.utils.tools.plugin_loader import load_plugin_config, save_plugin_config

_GMAIL_API = "https://gmail.googleapis.com"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPES = "https://www.googleapis.com/auth/gmail.modify"


def _get_config() -> dict:
    return load_plugin_config("gmail")


def _get_access_token() -> str:
    """Return a valid access token, refreshing it from the refresh token if needed."""
    cfg = _get_config()
    access = cfg.get("access_token") or ""
    if access:
        return access

    refresh = cfg.get("refresh_token") or ""
    client_id = cfg.get("client_id") or ""
    client_secret = cfg.get("client_secret") or ""
    if not (refresh and client_id and client_secret):
        raise RuntimeError(
            "Gmail plugin is not configured. Set client_id, client_secret, and "
            "refresh_token in the Plugins tab."
        )

    resp = httpx.post(
        _TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to refresh Gmail access token: {resp.text}")

    data = resp.json()
    access = data.get("access_token", "")
    if access:
        cfg["access_token"] = access
        save_plugin_config("gmail", cfg)
    return access


def _gmail_request(method: str, path: str, *, json_body: dict | None = None) -> dict:
    token = _get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{_GMAIL_API}{path}"
    resp = httpx.request(method, url, headers=headers, json=json_body, timeout=30)
    if resp.status_code in (401, 403):
        # Token may be expired/stale — drop it and retry once.
        cfg = _get_config()
        cfg.pop("access_token", None)
        save_plugin_config("gmail", cfg)
        token = _get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        resp = httpx.request(method, url, headers=headers, json=json_body, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"Gmail API error {resp.status_code}: {resp.text}")
    return resp.json() if resp.content else {}


def _build_raw_message(to: str, subject: str, body: str) -> str:
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


class GmailSendTool(BaseTool):
    name = "gmail_send"
    description = "Send an email via Gmail."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject"},
            "body": {"type": "string", "description": "Email body (plain text)"},
        },
        "required": ["to", "subject", "body"],
    }

    async def execute(self, **params: Any) -> str:
        to = params["to"]
        subject = params["subject"]
        body = params["body"]
        raw = _build_raw_message(to, subject, body)
        result = _gmail_request(
            "POST",
            "/gmail/v1/users/me/messages/send",
            json_body={"raw": raw},
        )
        return f"Sent email to {to}. Message id: {result.get('id', 'unknown')}"


class GmailListTool(BaseTool):
    name = "gmail_list"
    description = "List recent messages in the Gmail inbox."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "max_results": {
                "type": "integer",
                "description": "Maximum number of messages to return (default 10)",
            },
        },
        "required": [],
    }

    async def execute(self, **params: Any) -> str:
        max_results = params.get("max_results", 10)
        result = _gmail_request(
            "GET",
            f"/gmail/v1/users/me/messages?maxResults={max_results}",
        )
        messages = result.get("messages", [])
        if not messages:
            return "No messages found."
        lines = [f"{len(messages)} message(s):"]
        for m in messages:
            mid = m.get("id", "?")
            meta = _gmail_request("GET", f"/gmail/v1/users/me/messages/{mid}?format=metadata")
            headers = {
                h.get("name"): h.get("value")
                for h in meta.get("payload", {}).get("headers", [])
            }
            lines.append(
                f"- {mid}: {headers.get('Subject', '(no subject)')} "
                f"from {headers.get('From', '?')}"
            )
        return "\n".join(lines)


class GmailReadTool(BaseTool):
    name = "gmail_read"
    description = "Read a single Gmail message by id."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "Gmail message id"},
        },
        "required": ["message_id"],
    }

    async def execute(self, **params: Any) -> str:
        mid = params["message_id"]
        meta = _gmail_request("GET", f"/gmail/v1/users/me/messages/{mid}?format=full")
        payload = meta.get("payload", {})
        headers = {
            h.get("name"): h.get("value") for h in payload.get("headers", [])
        }
        body = ""
        parts = payload.get("parts", [])
        if parts:
            for part in parts:
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        body = base64.urlsafe_b64decode(data).decode("utf-8", "replace")
                        break
        else:
            data = payload.get("body", {}).get("data", "")
            if data:
                body = base64.urlsafe_b64decode(data).decode("utf-8", "replace")

        return (
            f"From: {headers.get('From', '?')}\n"
            f"Subject: {headers.get('Subject', '(no subject)')}\n"
            f"Date: {headers.get('Date', '?')}\n\n{body}"
        )


class GmailSearchTool(BaseTool):
    name = "gmail_search"
    description = "Search Gmail messages using a Gmail query string."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Gmail search query (e.g. 'from:alice subject:report')",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results (default 10)",
            },
        },
        "required": ["query"],
    }

    async def execute(self, **params: Any) -> str:
        query = params["query"]
        max_results = params.get("max_results", 10)
        result = _gmail_request(
            "GET",
            f"/gmail/v1/users/me/messages?q={httpx.QueryParams({'q': query})['q']}&maxResults={max_results}",
        )
        messages = result.get("messages", [])
        if not messages:
            return "No messages matched the query."
        lines = [f"{len(messages)} match(es):"]
        for m in messages:
            mid = m.get("id", "?")
            meta = _gmail_request("GET", f"/gmail/v1/users/me/messages/{mid}?format=metadata")
            headers = {
                h.get("name"): h.get("value")
                for h in meta.get("payload", {}).get("headers", [])
            }
            lines.append(
                f"- {mid}: {headers.get('Subject', '(no subject)')} "
                f"from {headers.get('From', '?')}"
            )
        return "\n".join(lines)
