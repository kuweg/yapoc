"""
ticket_tool.py — Ticket manipulation tool for YAPOC agents.

Provides programmatic access to the ticket/task system via the backend REST API.
Supports: mark_done, mark_in_progress, add_note, update_priority, update_assignee,
          update_status, get_ticket.

Usage (from Master agent or any agent with HTTP access):
    from app.utils.tools.ticket_tool import TicketTool
    tool = TicketTool(base_url="http://localhost:8000", agent_name="master")
    tool.mark_done("ticket-123")
    tool.add_note("ticket-123", "Completed successfully")

Permission model:
    By default, an agent may only modify tickets where ``assigned_agent`` matches
    ``agent_name`` OR ``assigned_agent`` is None/empty.  Pass ``force=True`` to
    bypass this check (e.g. for Master or Planning agents that coordinate across
    all tickets).
"""

from __future__ import annotations

import httpx


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class TicketToolError(Exception):
    """Raised when the backend returns an unexpected HTTP error."""

    def __init__(self, message: str, status_code: int | None = None, ticket_id: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.ticket_id = ticket_id

    def __repr__(self) -> str:
        return (
            f"TicketToolError(message={str(self)!r}, "
            f"status_code={self.status_code!r}, ticket_id={self.ticket_id!r})"
        )


# ---------------------------------------------------------------------------
# TicketTool
# ---------------------------------------------------------------------------

class TicketTool:
    """Synchronous HTTP client for the YAPOC ticket system.

    Parameters
    ----------
    base_url:
        Base URL of the YAPOC backend (default: ``http://localhost:8000``).
    agent_name:
        Name of the calling agent.  Used as the ``author`` field in notes
        and for the permission check.  Pass an empty string to disable the
        permission check entirely (not recommended in production).
    timeout:
        HTTP request timeout in seconds (default: 10).
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        agent_name: str = "",
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.agent_name = agent_name
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _get(self, path: str) -> dict:
        """Perform a GET request and return the parsed JSON body."""
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(self._url(path))
        if resp.status_code == 404:
            raise TicketToolError(
                f"Ticket not found: {path}",
                status_code=404,
            )
        if not resp.is_success:
            raise TicketToolError(
                f"GET {path} failed with HTTP {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
            )
        return resp.json()

    def _patch(self, path: str, payload: dict, ticket_id: str) -> dict:
        """Perform a PATCH request and return the parsed JSON body."""
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.patch(self._url(path), json=payload)
        if resp.status_code == 404:
            raise TicketToolError(
                f"Ticket not found: {ticket_id}",
                status_code=404,
                ticket_id=ticket_id,
            )
        if resp.status_code == 422:
            raise TicketToolError(
                f"Invalid payload for {path}: {resp.text}",
                status_code=422,
                ticket_id=ticket_id,
            )
        if not resp.is_success:
            raise TicketToolError(
                f"PATCH {path} failed with HTTP {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
                ticket_id=ticket_id,
            )
        return resp.json()

    def _post(self, path: str, payload: dict, ticket_id: str) -> dict:
        """Perform a POST request and return the parsed JSON body."""
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self._url(path), json=payload)
        if resp.status_code == 404:
            raise TicketToolError(
                f"Ticket not found: {ticket_id}",
                status_code=404,
                ticket_id=ticket_id,
            )
        if resp.status_code == 422:
            raise TicketToolError(
                f"Invalid payload for {path}: {resp.text}",
                status_code=422,
                ticket_id=ticket_id,
            )
        if not resp.is_success:
            raise TicketToolError(
                f"POST {path} failed with HTTP {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
                ticket_id=ticket_id,
            )
        return resp.json()

    def _check_permission(self, ticket_id: str, force: bool = False) -> None:
        """Verify the calling agent is allowed to modify this ticket.

        Raises ``TicketToolError`` if the permission check fails.
        Skipped when ``force=True`` or when ``agent_name`` is empty.
        """
        if force or not self.agent_name:
            return
        ticket = self.get_ticket(ticket_id)
        assigned = ticket.get("assigned_agent") or ticket.get("assignee") or ""
        if assigned and assigned != self.agent_name:
            raise TicketToolError(
                f"Permission denied: ticket '{ticket_id}' is assigned to '{assigned}', "
                f"not '{self.agent_name}'. Pass force=True to override.",
                status_code=403,
                ticket_id=ticket_id,
            )

    def _ok(self, ticket_id: str, message: str, data: dict | None = None) -> dict:
        """Build a standard success response dict."""
        return {
            "success": True,
            "ticket_id": ticket_id,
            "message": message,
            "data": data,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_ticket(self, ticket_id: str) -> dict:
        """Fetch the current state of a ticket.

        Returns the raw ticket dict from the backend.

        Raises
        ------
        TicketToolError
            If the ticket does not exist or the request fails.
        """
        # The list endpoint is the only reliable way to look up by arbitrary ID
        # (including agent: and resume: prefixed IDs that contain colons).
        tickets = self._get("/api/tickets")
        for t in tickets:
            if t.get("id") == ticket_id:
                return t
        raise TicketToolError(
            f"Ticket not found: {ticket_id}",
            status_code=404,
            ticket_id=ticket_id,
        )

    def update_status(self, ticket_id: str, status: str, *, force: bool = False) -> dict:
        """Update the status of a ticket.

        Parameters
        ----------
        ticket_id:
            The ticket ID to update.
        status:
            New status value.  Must be one of: ``pending``, ``in_progress``,
            ``done``, ``blocked``.
        force:
            Bypass the assignee permission check.

        Returns
        -------
        dict
            ``{"success": True, "ticket_id": str, "message": str, "data": dict}``

        Raises
        ------
        TicketToolError
            On HTTP errors, 404, 422, or permission denial.
        """
        self._check_permission(ticket_id, force=force)
        data = self._patch(f"/api/tickets/{ticket_id}/status", {"status": status}, ticket_id)
        return self._ok(ticket_id, f"Status updated to '{status}'", data)

    def mark_done(self, ticket_id: str, *, force: bool = False) -> dict:
        """Mark a ticket as done.

        Convenience wrapper around :meth:`update_status`.

        Returns
        -------
        dict
            Standard success response.
        """
        return self.update_status(ticket_id, "done", force=force)

    def mark_in_progress(self, ticket_id: str, *, force: bool = False) -> dict:
        """Mark a ticket as in-progress.

        Convenience wrapper around :meth:`update_status`.

        Returns
        -------
        dict
            Standard success response.
        """
        return self.update_status(ticket_id, "in_progress", force=force)

    def add_note(self, ticket_id: str, note: str, *, force: bool = False) -> dict:
        """Append a note to a ticket's activity log.

        Parameters
        ----------
        ticket_id:
            The ticket ID to annotate.
        note:
            The note text to append.  Must not be empty.
        force:
            Bypass the assignee permission check.

        Returns
        -------
        dict
            Standard success response with updated ticket data.

        Raises
        ------
        TicketToolError
            On HTTP errors, 404, 422, or permission denial.
        """
        self._check_permission(ticket_id, force=force)
        payload = {"note": note, "author": self.agent_name or ""}
        data = self._post(f"/api/tickets/{ticket_id}/notes", payload, ticket_id)
        return self._ok(ticket_id, "Note added", data)

    def update_priority(self, ticket_id: str, priority: str, *, force: bool = False) -> dict:
        """Update the priority of a ticket.

        Parameters
        ----------
        ticket_id:
            The ticket ID to update.
        priority:
            New priority value.  Must be one of: ``low``, ``medium``,
            ``high``, ``critical``.
        force:
            Bypass the assignee permission check.

        Returns
        -------
        dict
            Standard success response with updated ticket data.

        Raises
        ------
        TicketToolError
            On HTTP errors, 404, 422, or permission denial.
        """
        self._check_permission(ticket_id, force=force)
        data = self._patch(f"/api/tickets/{ticket_id}/priority", {"priority": priority}, ticket_id)
        return self._ok(ticket_id, f"Priority updated to '{priority}'", data)

    def update_assignee(self, ticket_id: str, assignee: str, *, force: bool = False) -> dict:
        """Reassign a ticket to a different agent.

        Parameters
        ----------
        ticket_id:
            The ticket ID to reassign.
        assignee:
            Name of the agent to assign the ticket to.
        force:
            Bypass the assignee permission check.

        Returns
        -------
        dict
            Standard success response with updated ticket data.

        Raises
        ------
        TicketToolError
            On HTTP errors, 404, 422, or permission denial.
        """
        self._check_permission(ticket_id, force=force)
        data = self._patch(f"/api/tickets/{ticket_id}/assignee", {"assignee": assignee}, ticket_id)
        return self._ok(ticket_id, f"Assignee updated to '{assignee}'", data)
