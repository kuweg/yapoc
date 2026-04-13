"""ManageTicketsTool — agent tool for full ticket lifecycle management.

Wraps the YAPOC ticket REST API into a single tool callable by agents.
Master always operates with force=True (no assignee restriction).

Supported actions:
    list    — list all tickets (with optional status filter)
    create  — create a new user ticket
    delete  — delete a ticket by ID
    move    — change ticket status (backlog → in_progress → done → error)
    update  — update title, description, priority, or assignee
    note    — append a note to a ticket's activity log
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.utils.tools import BaseTool, RiskTier, truncate_tool_output


class ManageTicketsTool(BaseTool):
    name = "manage_tickets"
    description = (
        "Manage tickets in the YAPOC task board. "
        "Actions: list, create, delete, move (change status), update (title/description/priority/assignee), note (add activity note). "
        "Use this to track work, organize tasks, and update ticket state."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "create", "delete", "move", "update", "note"],
                "description": "Action to perform.",
            },
            "ticket_id": {
                "type": "string",
                "description": "Ticket ID (required for delete, move, update, note).",
            },
            "title": {
                "type": "string",
                "description": "Ticket title (required for create; optional for update).",
            },
            "description": {
                "type": "string",
                "description": "Ticket description (optional for create/update).",
            },
            "requirements": {
                "type": "string",
                "description": "Additional requirements (optional for create/update).",
            },
            "status": {
                "type": "string",
                "enum": ["backlog", "in_progress", "done", "error"],
                "description": "New status (required for move). One of: backlog, in_progress, done, error.",
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "critical"],
                "description": "Ticket priority (optional for update).",
            },
            "assignee": {
                "type": "string",
                "description": "Agent name to assign the ticket to (optional for update).",
            },
            "note": {
                "type": "string",
                "description": "Note text to append to the ticket activity log (required for note action).",
            },
            "filter_status": {
                "type": "string",
                "description": "Optional status filter for list action (e.g. 'in_progress').",
            },
        },
        "required": ["action"],
    }
    risk_tier = RiskTier.AUTO

    def __init__(self, agent_dir: Path | None = None) -> None:
        self._agent_name = agent_dir.name if agent_dir else "master"
        self._base = settings.base_url

    def _url(self, path: str) -> str:
        return f"{self._base}{path}"

    async def execute(self, **params: Any) -> str:
        action = params["action"]
        try:
            if action == "list":
                return await self._list(params.get("filter_status"))
            elif action == "create":
                return await self._create(params)
            elif action == "delete":
                return await self._delete(params["ticket_id"])
            elif action == "move":
                return await self._move(params["ticket_id"], params["status"])
            elif action == "update":
                return await self._update(params["ticket_id"], params)
            elif action == "note":
                return await self._note(params["ticket_id"], params["note"])
            else:
                return f"Unknown action: {action}"
        except KeyError as e:
            return f"Missing required parameter: {e}"
        except Exception as exc:
            return f"Ticket error ({action}): {exc}"

    async def _list(self, filter_status: str | None) -> str:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(self._url("/tickets"))
        if not r.is_success:
            return f"Failed to list tickets: HTTP {r.status_code}"
        tickets = r.json()
        if filter_status:
            tickets = [t for t in tickets if t.get("status") == filter_status]
        if not tickets:
            return "No tickets found."
        lines = [f"Tickets ({len(tickets)} total):\n"]
        for t in tickets:
            tid = t.get("id", "?")
            title = t.get("title", "(no title)")[:60]
            status = t.get("status", "?")
            priority = t.get("priority", "?")
            assignee = t.get("assigned_agent") or t.get("assignee") or "unassigned"
            lines.append(f"  [{status}] [{priority}] {title}\n    id: {tid} | assignee: {assignee}")
        return truncate_tool_output("\n".join(lines))

    async def _create(self, params: dict[str, Any]) -> str:
        if not params.get("title"):
            return "Error: 'title' is required for create."
        payload = {
            "title": params["title"],
            "description": params.get("description", ""),
            "requirements": params.get("requirements", ""),
        }
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(self._url("/tickets"), json=payload)
        if not r.is_success:
            return f"Failed to create ticket: HTTP {r.status_code} — {r.text}"
        ticket = r.json()
        return f"Created ticket '{ticket.get('id')}': {ticket.get('title')}"

    async def _delete(self, ticket_id: str) -> str:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.delete(self._url(f"/tickets/{ticket_id}"))
        if r.status_code == 404:
            return f"Ticket not found: {ticket_id}"
        if not r.is_success:
            return f"Failed to delete ticket: HTTP {r.status_code}"
        return f"Deleted ticket '{ticket_id}'."

    async def _move(self, ticket_id: str, status: str) -> str:
        valid = {"backlog", "in_progress", "done", "error"}
        if status not in valid:
            return f"Invalid status '{status}'. Valid: {sorted(valid)}"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.patch(
                self._url(f"/tickets/{ticket_id}/status"),
                json={"status": status},
            )
        if r.status_code == 404:
            return f"Ticket not found: {ticket_id}"
        if not r.is_success:
            return f"Failed to move ticket: HTTP {r.status_code} — {r.text}"
        return f"Ticket '{ticket_id}' moved to '{status}'."

    async def _update(self, ticket_id: str, params: dict[str, Any]) -> str:
        results = []

        if params.get("priority"):
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.patch(
                    self._url(f"/tickets/{ticket_id}/priority"),
                    json={"priority": params["priority"]},
                )
            if r.is_success:
                results.append(f"priority → {params['priority']}")
            else:
                results.append(f"priority update failed: HTTP {r.status_code}")

        if params.get("assignee") is not None:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.patch(
                    self._url(f"/tickets/{ticket_id}/assignee"),
                    json={"assignee": params["assignee"]},
                )
            if r.is_success:
                results.append(f"assignee → {params['assignee']}")
            else:
                results.append(f"assignee update failed: HTTP {r.status_code}")

        if params.get("title") or params.get("description") or params.get("requirements"):
            payload: dict[str, Any] = {}
            if params.get("title"):
                payload["title"] = params["title"]
            if params.get("description"):
                payload["description"] = params["description"]
            if params.get("requirements"):
                payload["requirements"] = params["requirements"]
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.patch(self._url(f"/tickets/{ticket_id}"), json=payload)
            if r.is_success:
                results.append(f"fields updated: {list(payload.keys())}")
            else:
                results.append(f"field update failed: HTTP {r.status_code}")

        if not results:
            return "No update fields provided. Specify at least one of: title, description, requirements, priority, assignee."
        return f"Ticket '{ticket_id}' updated — " + ", ".join(results)

    async def _note(self, ticket_id: str, note: str) -> str:
        if not note:
            return "Error: 'note' text is required."
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                self._url(f"/tickets/{ticket_id}/notes"),
                json={"note": note, "author": self._agent_name},
            )
        if r.status_code == 404:
            return f"Ticket not found: {ticket_id}"
        if not r.is_success:
            return f"Failed to add note: HTTP {r.status_code} — {r.text}"
        return f"Note added to ticket '{ticket_id}'."
