"""Calendar plugin — real Google Calendar API integration via OAuth2.

Tools:
  - calendar_list_events   : list upcoming events from the primary calendar
  - calendar_create_event  : create an event on the primary calendar

Configuration is REUSED from the Gmail plugin (data/plugins/gmail/config.json),
which contains the same OAuth app credentials: client_id, client_secret,
refresh_token. The access token is refreshed automatically using the refresh
token when it is missing or expired.

Note: the refresh token was originally granted for the Gmail scope. If the
Calendar API returns 403 (insufficient scope), the user must re-authorize the
OAuth app with the Calendar scope (https://www.googleapis.com/auth/calendar).

The Calendar API is called directly over HTTPS with httpx (no google client
library dependency).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.utils.tools import BaseTool
from app.utils.tools.plugin_loader import load_plugin_config, save_plugin_config

_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"


def _get_config() -> dict:
    # Reuse the Gmail plugin's OAuth credentials (same OAuth app).
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
            "Calendar plugin is not configured. The Gmail plugin must be configured "
            "first (client_id, client_secret, refresh_token in the Plugins tab)."
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
        raise RuntimeError(f"Failed to refresh access token: {resp.text}")

    data = resp.json()
    access = data.get("access_token", "")
    if access:
        cfg["access_token"] = access
        save_plugin_config("gmail", cfg)
    return access


def _calendar_request(method: str, path: str, *, json_body: dict | None = None) -> dict:
    token = _get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{_CALENDAR_API}{path}"
    resp = httpx.request(method, url, headers=headers, json=json_body, timeout=30)
    if resp.status_code in (401, 403):
        # Token may be expired/stale — drop it and retry once.
        cfg = _get_config()
        cfg.pop("access_token", None)
        save_plugin_config("gmail", cfg)
        token = _get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        resp = httpx.request(method, url, headers=headers, json=json_body, timeout=30)
    if resp.status_code == 403:
        raise RuntimeError(
            "Calendar API returned 403 (insufficient scope). The OAuth app was "
            "authorized only for Gmail. Re-authorize it with the Calendar scope "
            f"({_CALENDAR_SCOPE}) in the Plugins tab."
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Calendar API error {resp.status_code}: {resp.text}")
    return resp.json() if resp.content else {}


def _now_rfc3339() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plus_days_rfc3339(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


class CalendarListEventsTool(BaseTool):
    name = "calendar_list_events"
    description = "List upcoming events from the primary Google Calendar."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "max_results": {
                "type": "integer",
                "description": "Maximum number of events to return (default 10)",
            },
            "time_min": {
                "type": "string",
                "description": "Lower bound (RFC3339) for event start time (default now)",
            },
            "time_max": {
                "type": "string",
                "description": "Upper bound (RFC3339) for event start time (default now+30 days)",
            },
        },
        "required": [],
    }

    async def execute(self, **params: Any) -> str:
        max_results = params.get("max_results", 10)
        time_min = params.get("time_min") or _now_rfc3339()
        time_max = params.get("time_max") or _plus_days_rfc3339(30)
        query = httpx.QueryParams(
            {
                "timeMin": time_min,
                "timeMax": time_max,
                "maxResults": str(max_results),
                "singleEvents": "true",
                "orderBy": "startTime",
            }
        )
        result = _calendar_request("GET", f"/calendars/primary/events?{query}")
        events = result.get("items", [])
        if not events:
            return "No upcoming events found."
        lines = [f"{len(events)} event(s):"]
        for e in events:
            summary = e.get("summary", "(no title)")
            start = e.get("start", {})
            end = e.get("end", {})
            start_str = start.get("dateTime") or start.get("date") or "?"
            end_str = end.get("dateTime") or end.get("date") or "?"
            lines.append(f"- {start_str} -> {end_str}: {summary}")
        return "\n".join(lines)


class CalendarCreateEventTool(BaseTool):
    name = "calendar_create_event"
    description = "Create an event on the primary Google Calendar."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Event summary/title"},
            "start": {
                "type": "string",
                "description": "Event start time (RFC3339, e.g. '2026-09-10T14:00:00+02:00')",
            },
            "end": {
                "type": "string",
                "description": "Event end time (RFC3339, e.g. '2026-09-10T15:00:00+02:00')",
            },
            "time_zone": {
                "type": "string",
                "description": "Event time zone (default 'Europe/Belgrade')",
            },
        },
        "required": ["summary", "start", "end"],
    }

    async def execute(self, **params: Any) -> str:
        summary = params["summary"]
        start = params["start"]
        end = params["end"]
        time_zone = params.get("time_zone", "Europe/Belgrade")
        body = {
            "summary": summary,
            "start": {"dateTime": start, "timeZone": time_zone},
            "end": {"dateTime": end, "timeZone": time_zone},
        }
        result = _calendar_request("POST", "/calendars/primary/events", json_body=body)
        event_id = result.get("id", "unknown")
        html_link = result.get("htmlLink", "")
        link = f" ({html_link})" if html_link else ""
        return f"Created event '{summary}'. Event id: {event_id}{link}"
