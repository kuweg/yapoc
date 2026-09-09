from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import httpx

from app.utils.tools import BaseTool
from app.utils.tools.plugin_loader import load_plugin_config, save_plugin_config

_SCOPES = "https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/documents https://www.googleapis.com/auth/spreadsheets"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DRIVE_API = "https://www.googleapis.com/drive/v3"
_DOCS_API = "https://docs.googleapis.com/v1"
_SHEETS_API = "https://sheets.googleapis.com/v4"


def _get_config() -> dict[str, Any]:
    return load_plugin_config("drive")


def _get_access_token() -> str:
    cfg = _get_config()
    access_token = cfg.get("access_token")
    if access_token:
        return access_token

    client_id = cfg.get("client_id")
    client_secret = cfg.get("client_secret")
    refresh_token = cfg.get("refresh_token")
    if not client_id or not client_secret or not refresh_token:
        raise RuntimeError(
            "Drive plugin is not fully configured. Set client_id, client_secret, and refresh_token in plugin config."
        )

    resp = httpx.post(
        _TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "scope": _SCOPES,
        },
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Failed to refresh Drive access token: {resp.status_code} {resp.text}")

    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError("Token refresh succeeded but no access_token returned by Google OAuth.")

    cfg["access_token"] = token
    save_plugin_config("drive", cfg)
    return token


def _request_with_retry(
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    expect_json: bool = True,
    raw_content: bytes | None = None,
    content_type: str | None = None,
) -> Any:
    token = _get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    if content_type:
        headers["Content-Type"] = content_type

    kwargs: dict[str, Any] = {"headers": headers, "timeout": 60}
    if json_body is not None:
        kwargs["json"] = json_body
    if params is not None:
        kwargs["params"] = params
    if raw_content is not None:
        kwargs["content"] = raw_content

    resp = httpx.request(method, url, **kwargs)
    if resp.status_code in (401, 403):
        cfg = _get_config()
        cfg.pop("access_token", None)
        save_plugin_config("drive", cfg)
        token = _get_access_token()
        headers["Authorization"] = f"Bearer {token}"
        resp = httpx.request(method, url, **kwargs)

    if resp.status_code >= 400:
        raise RuntimeError(f"Google API request failed ({resp.status_code}): {resp.text}")

    if not expect_json:
        return resp.text

    if not resp.content:
        return {}
    return resp.json()


def _drive_request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _request_with_retry(method, f"{_DRIVE_API}{path}", json_body=json_body, params=params)


def _docs_request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _request_with_retry(method, f"{_DOCS_API}{path}", json_body=json_body)


def _sheets_request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _request_with_retry(method, f"{_SHEETS_API}{path}", json_body=json_body, params=params)


def _download_file(file_id: str) -> bytes:
    token = _get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    resp = httpx.get(
        f"{_DRIVE_API}/files/{file_id}",
        params={"alt": "media"},
        headers=headers,
        timeout=60,
    )
    if resp.status_code in (401, 403):
        cfg = _get_config()
        cfg.pop("access_token", None)
        save_plugin_config("drive", cfg)
        token = _get_access_token()
        headers["Authorization"] = f"Bearer {token}"
        resp = httpx.get(
            f"{_DRIVE_API}/files/{file_id}",
            params={"alt": "media"},
            headers=headers,
            timeout=60,
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Drive download failed ({resp.status_code}): {resp.text}")
    return resp.content


def _summarize_ipynb(data: dict[str, Any]) -> str:
    lines: list[str] = []

    nbformat = data.get("nbformat")
    nbformat_minor = data.get("nbformat_minor")
    if nbformat is not None:
        lines.append(f"nbformat: {nbformat}.{nbformat_minor}")

    kernelspec = (data.get("metadata") or {}).get("kernelspec") or {}
    if kernelspec:
        parts = []
        for key in ("name", "display_name", "language"):
            val = kernelspec.get(key)
            if val:
                parts.append(f"{key}={val}")
        if parts:
            lines.append("kernelspec: " + ", ".join(parts))

    cells = data.get("cells") or []
    counts: dict[str, int] = {}
    for cell in cells:
        ctype = cell.get("cell_type", "unknown")
        counts[ctype] = counts.get(ctype, 0) + 1
    lines.append(
        "cells: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    )

    for cell in cells[:200]:
        ctype = cell.get("cell_type", "unknown")
        source = cell.get("source", [])
        if isinstance(source, list):
            joined = "".join(str(s) for s in source)
        else:
            joined = str(source)
        joined = " ".join(joined.split())
        preview = joined[:120]
        line = f"[{ctype}] {preview}"
        if ctype == "code":
            outputs = cell.get("outputs") or []
            if outputs:
                out_types = []
                for out in outputs:
                    ot = out.get("output_type")
                    if ot:
                        out_types.append(ot)
                line += f" | outputs: {len(outputs)} ({', '.join(out_types)})"
        lines.append(line)

    summary = "\n".join(lines)
    if len(summary) > 8000:
        summary = summary[:8000] + "\n... (truncated)"
    return summary


def _summarize_text(text: str) -> str:
    if len(text) > 4000:
        return text[:4000] + "\n... (truncated)"
    return text


def _format_files(files: list[dict[str, Any]]) -> str:
    if not files:
        return "No files found."
    lines: list[str] = []
    for item in files:
        lines.append(
            "- {name} ({mime}) | id={id} | modified={modified} | size={size} | parents={parents} | link={link}".format(
                name=item.get("name", "(unnamed)"),
                mime=item.get("mimeType", "unknown"),
                id=item.get("id", ""),
                modified=item.get("modifiedTime", ""),
                size=item.get("size", ""),
                parents=",".join(item.get("parents", []) or []),
                link=item.get("webViewLink", ""),
            )
        )
    return "\n".join(lines)


class DriveListTool(BaseTool):
    name = "drive_list"
    description = "List files and folders in Google Drive."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "default": 20},
            "page_token": {"type": "string"},
        },
    }

    async def execute(self, **params: Any) -> str:
        query = params.get("query") or "trashed=false"
        max_results = int(params.get("max_results", 20))
        page_token = params.get("page_token")
        req_params: dict[str, Any] = {
            "fields": "files(id,name,mimeType,size,modifiedTime,parents,webViewLink),nextPageToken",
            "pageSize": max_results,
            "q": query,
            "orderBy": "modifiedTime desc",
        }
        if page_token:
            req_params["pageToken"] = page_token

        data = _drive_request("GET", "/files", params=req_params)
        files = data.get("files", [])
        next_page = data.get("nextPageToken")
        result = _format_files(files)
        if next_page:
            result += f"\nNext page token: {next_page}"
        return result


class DriveSearchTool(BaseTool):
    name = "drive_search"
    description = "Search Google Drive by file name and full text."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "default": 20},
        },
        "required": ["query"],
    }

    async def execute(self, **params: Any) -> str:
        query = str(params.get("query", "")).strip()
        if not query:
            return "query is required"
        max_results = int(params.get("max_results", 20))
        safe = query.replace("'", "\\'")
        q = f"(name contains '{safe}' or fullText contains '{safe}') and trashed=false"
        data = _drive_request(
            "GET",
            "/files",
            params={
                "q": q,
                "pageSize": max_results,
                "orderBy": "modifiedTime desc",
                "fields": "files(id,name,mimeType,size,modifiedTime,parents,webViewLink)",
            },
        )
        return _format_files(data.get("files", []))


class DriveUploadTool(BaseTool):
    name = "drive_upload"
    description = "Upload text content as a file to Google Drive."
    input_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "content": {"type": "string"},
            "mime_type": {"type": "string", "default": "text/plain"},
            "parent_id": {"type": "string"},
        },
        "required": ["name", "content"],
    }

    async def execute(self, **params: Any) -> str:
        name = str(params.get("name", "")).strip()
        content = str(params.get("content", ""))
        mime_type = str(params.get("mime_type", "text/plain"))
        parent_id = params.get("parent_id")
        if not name:
            return "name is required"

        metadata: dict[str, Any] = {"name": name}
        if parent_id:
            metadata["parents"] = [parent_id]

        token = _get_access_token()
        files = {
            "metadata": (None, json.dumps(metadata), "application/json; charset=UTF-8"),
            "media": (name, content.encode("utf-8"), mime_type),
        }
        resp = httpx.post(
            "https://www.googleapis.com/upload/drive/v3/files",
            params={"uploadType": "multipart", "fields": "id,name,webViewLink"},
            headers={"Authorization": f"Bearer {token}"},
            files=files,
            timeout=60,
        )
        if resp.status_code in (401, 403):
            cfg = _get_config()
            cfg.pop("access_token", None)
            save_plugin_config("drive", cfg)
            token = _get_access_token()
            resp = httpx.post(
                "https://www.googleapis.com/upload/drive/v3/files",
                params={"uploadType": "multipart", "fields": "id,name,webViewLink"},
                headers={"Authorization": f"Bearer {token}"},
                files=files,
                timeout=60,
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Drive upload failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        return f"Uploaded '{data.get('name', name)}' with id={data.get('id','')} | link={data.get('webViewLink','')}"


class DriveCreateFolderTool(BaseTool):
    name = "drive_create_folder"
    description = "Create a folder in Google Drive."
    input_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "parent_id": {"type": "string"},
        },
        "required": ["name"],
    }

    async def execute(self, **params: Any) -> str:
        name = str(params.get("name", "")).strip()
        parent_id = params.get("parent_id")
        if not name:
            return "name is required"
        body: dict[str, Any] = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            body["parents"] = [parent_id]
        data = _drive_request("POST", "/files", json_body=body)
        return f"Created folder '{name}' with id={data.get('id','')}"


class DriveRenameTool(BaseTool):
    name = "drive_rename"
    description = "Rename a file or folder in Google Drive."
    input_schema = {
        "type": "object",
        "properties": {
            "file_id": {"type": "string"},
            "new_name": {"type": "string"},
        },
        "required": ["file_id", "new_name"],
    }

    async def execute(self, **params: Any) -> str:
        file_id = str(params.get("file_id", "")).strip()
        new_name = str(params.get("new_name", "")).strip()
        if not file_id or not new_name:
            return "file_id and new_name are required"
        _drive_request("PATCH", f"/files/{file_id}", json_body={"name": new_name})
        return f"Renamed file {file_id} to '{new_name}'."


class DriveMoveTool(BaseTool):
    name = "drive_move"
    description = "Move a file or folder to a new parent folder."
    input_schema = {
        "type": "object",
        "properties": {
            "file_id": {"type": "string"},
            "new_parent_id": {"type": "string"},
        },
        "required": ["file_id", "new_parent_id"],
    }

    async def execute(self, **params: Any) -> str:
        file_id = str(params.get("file_id", "")).strip()
        new_parent_id = str(params.get("new_parent_id", "")).strip()
        if not file_id or not new_parent_id:
            return "file_id and new_parent_id are required"

        current = _drive_request("GET", f"/files/{file_id}", params={"fields": "parents,name"})
        old_parents = ",".join(current.get("parents", []) or [])
        _drive_request(
            "PATCH",
            f"/files/{file_id}",
            params={"addParents": new_parent_id, "removeParents": old_parents},
        )
        return f"Moved '{current.get('name', file_id)}' to parent {new_parent_id}."


class DriveDeleteTool(BaseTool):
    name = "drive_delete"
    description = "Move a file or folder to trash in Google Drive."
    input_schema = {
        "type": "object",
        "properties": {
            "file_id": {"type": "string"},
        },
        "required": ["file_id"],
    }

    async def execute(self, **params: Any) -> str:
        file_id = str(params.get("file_id", "")).strip()
        if not file_id:
            return "file_id is required"
        _drive_request("PATCH", f"/files/{file_id}", json_body={"trashed": True})
        return f"Moved file {file_id} to trash."


class DriveReadDocTool(BaseTool):
    name = "drive_read_doc"
    description = "Read text content from a Google Doc."
    input_schema = {
        "type": "object",
        "properties": {
            "doc_id": {"type": "string"},
        },
        "required": ["doc_id"],
    }

    async def execute(self, **params: Any) -> str:
        doc_id = str(params.get("doc_id", "")).strip()
        if not doc_id:
            return "doc_id is required"
        doc = _docs_request("GET", f"/documents/{doc_id}")
        chunks: list[str] = []
        for block in doc.get("body", {}).get("content", []):
            paragraph = block.get("paragraph")
            if not paragraph:
                continue
            for elem in paragraph.get("elements", []):
                text = elem.get("textRun", {}).get("content")
                if text:
                    chunks.append(text)
        text = "".join(chunks).strip()
        return text or "(Document is empty or has no readable paragraph text.)"


class DriveReadSheetTool(BaseTool):
    name = "drive_read_sheet"
    description = "Read a Google Sheet range and return TSV text."
    input_schema = {
        "type": "object",
        "properties": {
            "spreadsheet_id": {"type": "string"},
            "range": {"type": "string", "default": "A1:Z1000"},
        },
        "required": ["spreadsheet_id"],
    }

    async def execute(self, **params: Any) -> str:
        spreadsheet_id = str(params.get("spreadsheet_id", "")).strip()
        cell_range = str(params.get("range", "A1:Z1000"))
        if not spreadsheet_id:
            return "spreadsheet_id is required"

        encoded_range = quote(cell_range, safe="!:$,ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")
        data = _sheets_request("GET", f"/spreadsheets/{spreadsheet_id}/values/{encoded_range}")
        values = data.get("values", [])
        if not values:
            return "No values found in the requested range."
        lines = ["\t".join(str(cell) for cell in row) for row in values]
        return "\n".join(lines)


class DriveCreateDocTool(BaseTool):
    name = "drive_create_doc"
    description = "Create a Google Doc and insert text content."
    input_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["title", "content"],
    }

    async def execute(self, **params: Any) -> str:
        title = str(params.get("title", "")).strip()
        content = str(params.get("content", ""))
        if not title:
            return "title is required"

        created = _docs_request("POST", "/documents", json_body={"title": title})
        doc_id = created.get("documentId")
        if not doc_id:
            raise RuntimeError("Google Docs API did not return documentId.")

        if content:
            chunk_size = 5000
            chunks = [content[i : i + chunk_size] for i in range(0, len(content), chunk_size)]
            index = 1
            requests: list[dict[str, Any]] = []
            for chunk in chunks:
                requests.append({"insertText": {"location": {"index": index}, "text": chunk}})
                index += len(chunk)
            _docs_request("POST", f"/documents/{doc_id}:batchUpdate", json_body={"requests": requests})

        link = f"https://docs.google.com/document/d/{doc_id}/edit"
        return f"Created document '{title}' with id={doc_id} | link={link}"


class DriveCreateSheetTool(BaseTool):
    name = "drive_create_sheet"
    description = "Create a Google Sheet and optionally populate rows."
    input_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "rows": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "string"}},
            },
        },
        "required": ["title"],
    }

    async def execute(self, **params: Any) -> str:
        title = str(params.get("title", "")).strip()
        rows = params.get("rows")
        if not title:
            return "title is required"

        created = _sheets_request("POST", "/spreadsheets", json_body={"properties": {"title": title}})
        spreadsheet_id = created.get("spreadsheetId")
        if not spreadsheet_id:
            raise RuntimeError("Google Sheets API did not return spreadsheetId.")

        if isinstance(rows, list) and rows:
            _sheets_request(
                "PUT",
                f"/spreadsheets/{spreadsheet_id}/values/Sheet1!A1",
                params={"valueInputOption": "RAW"},
                json_body={"values": rows},
            )

        link = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        return f"Created spreadsheet '{title}' with id={spreadsheet_id} | link={link}"


class DriveExportTool(BaseTool):
    name = "drive_export"
    description = "Export a Google Workspace file (Doc/Sheet/etc.) to text or CSV."
    input_schema = {
        "type": "object",
        "properties": {
            "file_id": {"type": "string"},
            "mime_type": {"type": "string", "default": "text/plain"},
        },
        "required": ["file_id"],
    }

    async def execute(self, **params: Any) -> str:
        file_id = str(params.get("file_id", "")).strip()
        mime_type = str(params.get("mime_type", "text/plain"))
        if not file_id:
            return "file_id is required"
        text = _request_with_retry(
            "GET",
            f"{_DRIVE_API}/files/{file_id}/export",
            params={"mimeType": mime_type},
            expect_json=False,
        )
        return text or "(Empty export result)"


class DriveDownloadTool(BaseTool):
    name = "drive_download"
    description = "Download a non-Google binary or text file from Drive and return a safe summary. For .ipynb notebooks, returns a structured summary of cells and code. For other text files, returns a truncated preview. For binary files, reports size and type only."
    input_schema = {
        "type": "object",
        "properties": {
            "file_id": {"type": "string"},
            "mime_type": {"type": "string", "default": ""},
        },
        "required": ["file_id"],
    }

    async def execute(self, **params: Any) -> str:
        file_id = str(params.get("file_id", "")).strip()
        if not file_id:
            return "file_id is required"
        mime_type = str(params.get("mime_type", "")).strip()

        content = _download_file(file_id)

        is_notebook = "ipynb" in mime_type
        if not is_notebook:
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                text = None
            if text is not None:
                try:
                    data = json.loads(text)
                except (ValueError, TypeError):
                    data = None
                if isinstance(data, dict) and isinstance(data.get("cells"), list) and "nbformat" in data:
                    is_notebook = True

        if is_notebook:
            try:
                text = content.decode("utf-8")
                data = json.loads(text)
                return _summarize_ipynb(data)
            except (UnicodeDecodeError, ValueError, TypeError):
                pass

        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = None

        if text is not None and "\x00" not in text[:1024]:
            return _summarize_text(text)

        return f"Binary file: {len(content)} bytes (not inspectable as text)."
