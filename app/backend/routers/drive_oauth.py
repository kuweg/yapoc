from __future__ import annotations

import json
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from loguru import logger

from app.config import settings
from app.utils.tools.plugin_loader import load_plugin_config, save_plugin_config

router = APIRouter(prefix="/drive", tags=["drive"])


def _redirect_uri() -> str:
    return f"{settings.base_url}/drive/oauth/callback"


def _scopes() -> str:
    return " ".join(
        [
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/spreadsheets",
        ]
    )


@router.get("/oauth/status")
async def oauth_status() -> dict[str, object]:
    cfg = load_plugin_config("drive") or {}

    client_id = cfg.get("client_id")
    client_secret = cfg.get("client_secret")
    refresh_token = cfg.get("refresh_token")
    access_token = cfg.get("access_token")

    connected = bool(refresh_token or access_token)

    return {
        "connected": connected,
        "user_email": cfg.get("user_email", "") or "",
        "has_client_id": bool(client_id),
        "has_client_secret": bool(client_secret),
        "has_refresh_token": bool(refresh_token),
    }


@router.post("/oauth/connect")
async def oauth_connect(payload: dict[str, str]) -> dict[str, str]:
    client_id = (payload.get("client_id") or "").strip()
    client_secret = (payload.get("client_secret") or "").strip()

    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="client_id and client_secret are required")

    cfg = load_plugin_config("drive") or {}
    state = secrets.token_urlsafe(16)

    cfg["client_id"] = client_id
    cfg["client_secret"] = client_secret
    cfg["oauth_state"] = state

    save_plugin_config("drive", cfg)

    params = {
        "client_id": client_id,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": _scopes(),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    return {"auth_url": auth_url, "state": state}


@router.get("/oauth/callback")
async def oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    if error:
        html = f"""
        <html><body style=\"font-family: Arial, sans-serif; padding: 24px;\">
          <h2>Google Drive connection failed</h2>
          <p>Authorization was denied or failed: <strong>{error}</strong></p>
          <p>You can close this tab and try connecting again.</p>
        </body></html>
        """
        return HTMLResponse(content=html, status_code=400)

    if not code or not state:
        return HTMLResponse(
            content=(
                "<html><body style='font-family: Arial, sans-serif; padding: 24px;'>"
                "<h2>Invalid OAuth callback</h2>"
                "<p>Missing required query parameters.</p>"
                "</body></html>"
            ),
            status_code=400,
        )

    cfg = load_plugin_config("drive") or {}
    expected_state = cfg.get("oauth_state")
    if not expected_state or state != expected_state:
        return HTMLResponse(
            content=(
                "<html><body style='font-family: Arial, sans-serif; padding: 24px;'>"
                "<h2>State validation failed</h2>"
                "<p>OAuth state mismatch. Please restart the connection flow.</p>"
                "</body></html>"
            ),
            status_code=400,
        )

    client_id = cfg.get("client_id")
    client_secret = cfg.get("client_secret")
    if not client_id or not client_secret:
        return HTMLResponse(
            content=(
                "<html><body style='font-family: Arial, sans-serif; padding: 24px;'>"
                "<h2>Drive credentials missing</h2>"
                "<p>Client credentials are not configured. Reconnect from settings.</p>"
                "</body></html>"
            ),
            status_code=400,
        )

    token_payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": _redirect_uri(),
        "grant_type": "authorization_code",
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            token_resp = await client.post("https://oauth2.googleapis.com/token", data=token_payload)
    except Exception as exc:
        logger.exception("Drive OAuth token exchange request failed")
        return HTMLResponse(
            content=(
                "<html><body style='font-family: Arial, sans-serif; padding: 24px;'>"
                "<h2>Drive token exchange failed</h2>"
                f"<p>Network/request error: {str(exc)}</p>"
                "<p>Please try again.</p>"
                "</body></html>"
            ),
            status_code=502,
        )

    if token_resp.status_code >= 400:
        detail = "token exchange failed"
        try:
            err_json = token_resp.json()
            detail = err_json.get("error_description") or err_json.get("error") or detail
        except Exception:
            detail = token_resp.text or detail

        logger.warning("Drive OAuth token exchange failed: {}", token_resp.status_code)
        return HTMLResponse(
            content=(
                "<html><body style='font-family: Arial, sans-serif; padding: 24px;'>"
                "<h2>Drive token exchange failed</h2>"
                f"<p>{detail}</p>"
                "<p>You can close this tab and retry the connection.</p>"
                "</body></html>"
            ),
            status_code=400,
        )

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    id_token = token_data.get("id_token")

    user_email = cfg.get("user_email", "")
    if id_token and isinstance(id_token, str):
        parts = id_token.split(".")
        if len(parts) == 3:
            try:
                import base64
                import json

                payload_b64 = parts[1]
                padded = payload_b64 + "=" * ((4 - len(payload_b64) % 4) % 4)
                decoded = base64.urlsafe_b64decode(padded.encode("utf-8"))
                claims = json.loads(decoded.decode("utf-8"))
                user_email = claims.get("email") or user_email
            except Exception:
                logger.debug("Could not decode id_token for user email")

    if not access_token and not refresh_token:
        return HTMLResponse(
            content=(
                "<html><body style='font-family: Arial, sans-serif; padding: 24px;'>"
                "<h2>Drive token exchange incomplete</h2>"
                "<p>No usable tokens were returned by Google.</p>"
                "</body></html>"
            ),
            status_code=400,
        )

    cfg["access_token"] = access_token
    if refresh_token:
        cfg["refresh_token"] = refresh_token
    cfg["user_email"] = user_email or ""
    cfg.pop("oauth_state", None)

    save_plugin_config("drive", cfg)

    email_html = f"<p>Connected account: <strong>{user_email}</strong></p>" if user_email else ""
    html = f"""
    <html><body style=\"font-family: Arial, sans-serif; padding: 24px;\">
      <h2>Google Drive connected</h2>
      {email_html}
      <p>You can close this tab and return to YAPOC.</p>
    </body></html>
    """
    return HTMLResponse(content=html, status_code=200)


async def _get_access_token() -> str | None:
    """Return a fresh Drive access token, refreshing via refresh_token if needed.

    Self-contained: reads the drive plugin config directly and performs the
    Google token refresh inline (mirrors the plugin's token logic) so the
    router has no fragile import dependency on plugins.drive.drive.
    """
    cfg = load_plugin_config("drive") or {}

    access_token = cfg.get("access_token")
    if access_token:
        return access_token

    refresh_token = cfg.get("refresh_token")
    client_id = cfg.get("client_id")
    client_secret = cfg.get("client_secret")
    if not refresh_token or not client_id or not client_secret:
        return None

    token_payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            token_resp = await client.post("https://oauth2.googleapis.com/token", data=token_payload)
    except Exception as exc:
        logger.exception("Drive token refresh request failed")
        raise HTTPException(status_code=502, detail=f"Drive token refresh failed: {exc}")

    if token_resp.status_code >= 400:
        logger.warning("Drive token refresh failed: {}", token_resp.status_code)
        raise HTTPException(status_code=401, detail="Drive token refresh failed — reconnect required")

    token_data = token_resp.json()
    new_access_token = token_data.get("access_token")
    if not new_access_token:
        raise HTTPException(status_code=401, detail="Drive token refresh returned no access token")

    cfg["access_token"] = new_access_token
    save_plugin_config("drive", cfg)
    return new_access_token


@router.get("/files")
async def drive_files(
    query: str | None = Query(default=None),
    max_results: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    access_token = await _get_access_token()
    if not access_token:
        raise HTTPException(status_code=401, detail="Drive not connected")

    q = (query or "").strip() or "trashed=false"

    params = {
        "fields": "files(id,name,mimeType,size,modifiedTime,webViewLink),nextPageToken",
        "pageSize": str(max_results),
        "q": q,
        "orderBy": "modifiedTime desc",
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                "https://www.googleapis.com/drive/v3/files",
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except Exception as exc:
        logger.exception("Drive files list request failed")
        raise HTTPException(status_code=502, detail=f"Drive files request failed: {exc}")

    if resp.status_code == 401:
        # Token may be stale — drop it so the next call refreshes.
        cfg = load_plugin_config("drive") or {}
        cfg.pop("access_token", None)
        save_plugin_config("drive", cfg)
        raise HTTPException(status_code=401, detail="Drive token expired — refresh and retry")

    if resp.status_code >= 400:
        logger.warning("Drive files list failed: {}", resp.status_code)
        raise HTTPException(status_code=resp.status_code, detail="Drive files request failed")

    data = resp.json()
    raw_files = data.get("files", []) or []

    files = [
        {
            "id": f.get("id", ""),
            "name": f.get("name", ""),
            "mime_type": f.get("mimeType", ""),
            "size": f.get("size"),
            "modified_time": f.get("modifiedTime"),
            "web_view_link": f.get("webViewLink"),
        }
        for f in raw_files
    ]

    result: dict[str, object] = {"files": files}
    if data.get("nextPageToken"):
        result["next_page_token"] = data["nextPageToken"]
    return result


@router.get("/files/{file_id}/content")
async def drive_file_content(file_id: str) -> dict[str, object]:
    from plugins.drive.drive import _summarize_ipynb, _summarize_text

    access_token = await _get_access_token()
    if not access_token:
        raise HTTPException(status_code=401, detail="Drive not connected")

    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"https://www.googleapis.com/drive/v3/files/{file_id}",
                params={"alt": "media"},
                headers=headers,
            )
    except Exception as exc:
        logger.exception("Drive file content download request failed")
        raise HTTPException(status_code=502, detail=f"Drive file download failed: {exc}")

    if resp.status_code == 401:
        cfg = load_plugin_config("drive") or {}
        cfg.pop("access_token", None)
        save_plugin_config("drive", cfg)
        raise HTTPException(status_code=401, detail="Drive token expired — refresh and retry")

    if resp.status_code >= 400:
        logger.warning("Drive file download failed: {}", resp.status_code)
        raise HTTPException(status_code=resp.status_code, detail="Drive file download failed")

    content = resp.content

    name = ""
    mime_type = ""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            meta_resp = await client.get(
                f"https://www.googleapis.com/drive/v3/files/{file_id}",
                params={"fields": "id,name,mimeType,size"},
                headers=headers,
            )
        if meta_resp.status_code < 400:
            meta = meta_resp.json()
            name = meta.get("name", "") or ""
            mime_type = meta.get("mimeType", "") or ""
    except Exception:
        logger.exception("Drive file metadata request failed")

    summary = _summarize_content(content, mime_type, _summarize_ipynb, _summarize_text)

    return {"file_id": file_id, "name": name, "mime_type": mime_type, "summary": summary}


def _summarize_content(
    content: bytes,
    mime_type: str,
    _summarize_ipynb,
    _summarize_text,
) -> str:
    is_notebook = "ipynb" in mime_type

    if not is_notebook:
        try:
            text = content.decode("utf-8")
            data = json.loads(text)
            if isinstance(data, dict) and isinstance(data.get("cells"), list) and "nbformat" in data:
                is_notebook = True
        except Exception:
            pass

    if is_notebook:
        try:
            return _summarize_ipynb(json.loads(content.decode("utf-8")))
        except Exception:
            logger.exception("Failed to summarize notebook content")

    try:
        text = content.decode("utf-8")
        if "\x00" not in text[:1024]:
            return _summarize_text(text)
    except Exception:
        pass

    return f"Binary file: {len(content)} bytes (not inspectable as text)."


@router.post("/oauth/disconnect")
async def oauth_disconnect() -> dict[str, object]:
    cfg = load_plugin_config("drive") or {}

    cfg.pop("refresh_token", None)
    cfg.pop("access_token", None)
    cfg.pop("user_email", None)
    cfg.pop("oauth_state", None)

    save_plugin_config("drive", cfg)

    return {"status": "ok", "connected": False}
