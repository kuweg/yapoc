"""Tickets router — User Defined Tickets (UDTs) + persistent agent task history."""

import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/tickets")

# ---------------------------------------------------------------------------
# Ticket store — flat JSON array in app/data/tickets.json
# ---------------------------------------------------------------------------

_TICKETS_PATH = Path(__file__).parent.parent.parent / "data" / "tickets.json"


def _load_tickets() -> list[dict]:
    try:
        return json.loads(_TICKETS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_tickets(tickets: list[dict]) -> None:
    _TICKETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=_TICKETS_PATH.parent, suffix=".tmp")
    try:
        os.write(fd, json.dumps(tickets, indent=2, ensure_ascii=False).encode())
        os.close(fd)
        os.replace(tmp, _TICKETS_PATH)
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TicketCreate(BaseModel):
    title: str
    description: str = ""
    requirements: str = ""


class TicketUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    requirements: str | None = None
    status: str | None = None  # backlog | in_progress | done | error


class AssignRequest(BaseModel):
    agent_name: str


class TicketResponse(BaseModel):
    id: str
    type: str           # "user" | "agent"
    title: str
    description: str
    requirements: str
    status: str         # backlog | in_progress | done | error
    priority: str = "medium"  # low | medium | high | critical
    assigned_agent: str | None
    parent_agent: str | None   # which agent spawned this task (assigned_by field)
    created_at: str
    updated_at: str
    # Agent-task-only fields
    agent_name: str | None = None
    task_text: str | None = None
    result_text: str | None = None
    error_text: str | None = None
    trace: list[dict] = []  # [{ts, note, agent}]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AGENT_STATUS_MAP = {
    "pending":  "backlog",
    "running":  "in_progress",
    "done":     "done",
    "error":    "error",
    "consumed": "done",
}

# Agents that are infrastructure only — don't create tickets automatically for them
_INFRA_AGENTS = {"base"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_task_md(content: str) -> dict | None:
    """Parse TASK.MD content into a dict. Returns None if no valid structured task."""
    if not content.strip():
        return None

    fm: dict[str, str] = {}
    fm_match = re.match(r"^---\n(.*?)\n---\n?", content, re.DOTALL)
    if not fm_match:
        return None
    for line in fm_match.group(1).splitlines():
        if ": " in line:
            key, _, val = line.partition(": ")
            fm[key.strip()] = val.strip()

    task_status = fm.get("status", "")
    if not task_status:
        return None
    if task_status == "consumed":
        task_status = "done"  # consumed = successfully processed, treat as done

    def get_section(name: str) -> str | None:
        m = re.search(rf"## {name}\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
        return m.group(1).strip() if m else None

    task_text = get_section("Task") or ""
    if not task_text:
        return None

    return {
        "status": task_status,
        "assigned_by": fm.get("assigned_by", ""),
        "assigned_at": fm.get("assigned_at", ""),
        "completed_at": fm.get("completed_at", ""),
        "task_text": task_text,
        "result_text": get_section("Result"),
        "error_text": get_section("Error"),
    }


def _agent_ticket_id(agent_name: str, assigned_at: str) -> str:
    """Stable ticket ID for an agent task run. assigned_at makes each run unique."""
    if assigned_at:
        # Sanitize the timestamp for use as ID segment
        safe_ts = re.sub(r"[^0-9TZ\-:]", "", assigned_at)
        return f"agent:{agent_name}:{safe_ts}"
    return f"agent:{agent_name}"


def _sync_agent_tasks(tickets: list[dict]) -> tuple[list[dict], bool]:
    """Scan all agent TASK.MD files and create/update persistent tickets.

    Returns (updated_tickets, changed) where changed=True means the store needs saving.
    """
    by_id = {t["id"]: t for t in tickets}
    changed = False

    for agent_dir in settings.agents_dir.iterdir():
        if not agent_dir.is_dir() or agent_dir.name in _INFRA_AGENTS:
            continue

        task_path = agent_dir / "TASK.MD"
        if not task_path.exists():
            continue

        try:
            content = task_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        parsed = _parse_task_md(content)
        if parsed is None:
            continue

        ticket_id = _agent_ticket_id(agent_dir.name, parsed["assigned_at"])
        board_status = _AGENT_STATUS_MAP.get(parsed["status"], "backlog")
        now = _now()

        if ticket_id not in by_id:
            # Before creating a new agent ticket, check if there's already an active UDT
            # assigned to this agent — if so, the TASK.MD was spawned by that UDT.
            # Update the UDT instead of creating a duplicate.
            active_udt = next(
                (t for t in tickets
                 if t.get("type") == "user"
                 and t.get("assigned_agent") == agent_dir.name
                 and t.get("status") in ("in_progress",)),
                None,
            )
            if active_udt is not None:
                # Update UDT: don't regress to backlog once it's in_progress
                effective_status = board_status if board_status != "backlog" else "in_progress"
                updates: dict = {}
                if active_udt.get("status") != effective_status:
                    updates["status"] = effective_status
                if parsed["result_text"] and active_udt.get("result_text") != parsed["result_text"]:
                    updates["result_text"] = parsed["result_text"]
                if parsed["error_text"] and active_udt.get("error_text") != parsed["error_text"]:
                    updates["error_text"] = parsed["error_text"]
                if updates:
                    active_udt.update(updates)
                    active_udt["updated_at"] = now
                    changed = True
                continue  # skip creating a new agent ticket for this TASK.MD

            # No active UDT — create a new persistent agent ticket
            ticket: dict = {
                "id": ticket_id,
                "type": "agent",
                "title": parsed["task_text"][:120],
                "description": parsed["task_text"],
                "requirements": "",
                "status": board_status,
                "assigned_agent": agent_dir.name,
                "parent_agent": parsed["assigned_by"] or None,
                "created_at": parsed["assigned_at"] or now,
                "updated_at": now,
                "agent_name": agent_dir.name,
                "task_text": parsed["task_text"],
                "result_text": parsed["result_text"],
                "error_text": parsed["error_text"],
                "trace": [],
            }
            by_id[ticket_id] = ticket
            tickets.append(ticket)
            changed = True
        else:
            # Existing ticket — update mutable fields if anything changed
            existing = by_id[ticket_id]
            updates: dict = {}
            if existing.get("status") != board_status:
                updates["status"] = board_status
            if parsed["result_text"] and existing.get("result_text") != parsed["result_text"]:
                updates["result_text"] = parsed["result_text"]
            if parsed["error_text"] and existing.get("error_text") != parsed["error_text"]:
                updates["error_text"] = parsed["error_text"]
            if updates:
                existing.update(updates)
                existing["updated_at"] = now
                changed = True

    return tickets, changed


def _sync_resume_tasks(tickets: list[dict]) -> tuple[list[dict], bool]:
    """Parse master's RESUME.MD and create tickets for any in-flight tasks recorded there.

    RESUME.MD is free-form markdown written by master or auto-populated by the CLI.
    We create a single 'resume' ticket if the file has substantive content and no
    matching ticket exists yet.
    """
    resume_path = settings.agents_dir / "master" / "RESUME.MD"
    if not resume_path.exists():
        return tickets, False

    try:
        content = resume_path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return tickets, False

    if not content:
        return tickets, False

    # Each non-empty line in RESUME.MD that looks like a task entry
    # Format can be:  "- agent_name: task description (status)"
    # or free-form paragraphs. We create one ticket per detected task line.
    changed = False
    by_id = {t["id"]: t for t in tickets}

    # Try to parse structured lines: "- <agent>: <description>"
    task_lines = re.findall(r"^[-*]\s+(\w+):\s+(.+?)(?:\s+\((\w+)\))?$", content, re.MULTILINE)

    if task_lines:
        for agent_name, description, status_hint in task_lines:
            # Use a hash of content as stable ID so duplicates aren't re-created
            resume_id = f"resume:{agent_name}:{hash(description) & 0xFFFFFF:06x}"
            if resume_id in by_id:
                continue
            board_status: str = _AGENT_STATUS_MAP.get(
                status_hint.lower() if status_hint else "pending", "backlog"
            )
            ticket: dict = {
                "id": resume_id,
                "type": "agent",
                "title": description[:120],
                "description": description,
                "requirements": "",
                "status": board_status,
                "assigned_agent": agent_name if agent_name != "master" else "master",
                "parent_agent": "master",
                "created_at": _now(),
                "updated_at": _now(),
                "agent_name": agent_name,
                "task_text": description,
                "result_text": None,
                "error_text": None,
            }
            by_id[resume_id] = ticket
            tickets.append(ticket)
            changed = True
    else:
        # Free-form RESUME.MD — create a single meta-ticket for the whole content
        resume_id = f"resume:master:{hash(content) & 0xFFFFFF:06x}"
        if resume_id not in by_id:
            ticket = {
                "id": resume_id,
                "type": "agent",
                "title": "Resume state: " + content.splitlines()[0][:80],
                "description": content,
                "requirements": "",
                "status": "in_progress",
                "assigned_agent": "master",
                "parent_agent": None,
                "created_at": _now(),
                "updated_at": _now(),
                "agent_name": "master",
                "task_text": content,
                "result_text": None,
                "error_text": None,
            }
            by_id[resume_id] = ticket
            tickets.append(ticket)
            changed = True

    return tickets, changed


def _cascade_completion(tickets: list[dict]) -> tuple[list[dict], bool]:
    """When any ticket reaches done/error, cascade that status to agent children.

    A ticket is a child of ticket T when:
      child.parent_agent == T.assigned_agent   (child was spawned by T's executor)
      child.status in (in_progress, backlog)   (still open)
    """
    changed = False
    now = _now()
    for t in tickets:
        if t.get("status") not in ("done", "error"):
            continue
        assigned = t.get("assigned_agent")
        if not assigned:
            continue
        for child in tickets:
            if child["id"] == t["id"]:
                continue
            if child.get("status") not in ("in_progress", "backlog"):
                continue
            if child.get("parent_agent") != assigned:
                continue
            child["status"] = t["status"]
            child["updated_at"] = now
            changed = True
    return tickets, changed


class TraceEntry(BaseModel):
    note: str
    agent: str | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[TicketResponse])
async def list_tickets():
    """Return all tickets. Syncs agent TASK.MD files and RESUME.MD into the store first."""
    tickets = _load_tickets()

    # Backfill fields added in later schema versions
    for t in tickets:
        t.setdefault("parent_agent", None)
        t.setdefault("trace", [])

    tickets, changed1 = _sync_agent_tasks(tickets)
    tickets, changed2 = _sync_resume_tasks(tickets)
    tickets, changed3 = _cascade_completion(tickets)

    if changed1 or changed2 or changed3:
        _save_tickets(tickets)

    return [TicketResponse(**t) for t in tickets]


@router.post("", response_model=TicketResponse, status_code=201)
async def create_ticket(body: TicketCreate):
    tickets = _load_tickets()
    now = _now()
    ticket = {
        "id": str(uuid.uuid4()),
        "type": "user",
        "title": body.title,
        "description": body.description,
        "requirements": body.requirements,
        "status": "backlog",
        "assigned_agent": None,
        "parent_agent": None,
        "created_at": now,
        "updated_at": now,
        "agent_name": None,
        "task_text": None,
        "result_text": None,
        "error_text": None,
        "trace": [],
    }
    tickets.append(ticket)
    _save_tickets(tickets)
    return TicketResponse(**ticket)


@router.patch("/{ticket_id}", response_model=TicketResponse)
async def update_ticket(ticket_id: str, body: TicketUpdate):
    tickets = _load_tickets()
    for t in tickets:
        if t["id"] == ticket_id:
            if body.title is not None:
                t["title"] = body.title
            if body.description is not None:
                t["description"] = body.description
            if body.requirements is not None:
                t["requirements"] = body.requirements
            if body.status is not None:
                valid = {"backlog", "in_progress", "done", "error"}
                if body.status not in valid:
                    raise HTTPException(status_code=422, detail=f"status must be one of {valid}")
                t["status"] = body.status
            t.setdefault("parent_agent", None)
            t.setdefault("trace", [])
            t["updated_at"] = _now()
            _save_tickets(tickets)
            return TicketResponse(**t)
    raise HTTPException(status_code=404, detail=f"Ticket '{ticket_id}' not found")


@router.delete("/{ticket_id}")
async def delete_ticket(ticket_id: str):
    tickets = _load_tickets()
    new_tickets = [t for t in tickets if t["id"] != ticket_id]
    if len(new_tickets) == len(tickets):
        raise HTTPException(status_code=404, detail=f"Ticket '{ticket_id}' not found")
    _save_tickets(new_tickets)
    return {"ok": True}


@router.post("/{ticket_id}/assign", response_model=TicketResponse)
async def assign_ticket(ticket_id: str, body: AssignRequest):
    """Assign a UDT to an agent: update ticket status + spawn agent with task."""
    agent_name = body.agent_name
    agent_dir = settings.agents_dir / agent_name
    if not agent_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

    tickets = _load_tickets()
    for t in tickets:
        if t["id"] == ticket_id:
            if t["type"] != "user":
                raise HTTPException(status_code=422, detail="Cannot assign agent-type tickets")

            # Master is in-process — the frontend routes execution through the chat
            # stream (pendingChatInput). Calling SpawnAgentTool would write a stale
            # structured TASK.MD that overwrites itself and creates ghost agent tickets.
            if agent_name != "master":
                from app.utils.tools.delegation import SpawnAgentTool
                spawn = SpawnAgentTool()
                task_text = t["title"]
                context = "\n\n".join(filter(None, [t["description"], t.get("requirements", "")]))
                result = await spawn.execute(agent_name=agent_name, task=task_text, context=context)
                if result.startswith("Error:"):
                    raise HTTPException(status_code=400, detail=result)

            t["status"] = "in_progress"
            t["assigned_agent"] = agent_name
            t.setdefault("parent_agent", None)
            t["updated_at"] = _now()
            _save_tickets(tickets)
            return TicketResponse(**t)

    raise HTTPException(status_code=404, detail=f"Ticket '{ticket_id}' not found")


@router.post("/{ticket_id}/trace", response_model=TicketResponse)
async def add_trace(ticket_id: str, body: TraceEntry):
    """Append a timestamped trace note to a ticket's activity log."""
    tickets = _load_tickets()
    for t in tickets:
        if t["id"] == ticket_id:
            t.setdefault("trace", [])
            t.setdefault("parent_agent", None)
            t["trace"].append({
                "ts": _now(),
                "note": body.note,
                "agent": body.agent,
            })
            t["updated_at"] = _now()
            _save_tickets(tickets)
            return TicketResponse(**t)
    raise HTTPException(status_code=404, detail=f"Ticket '{ticket_id}' not found")


# ---------------------------------------------------------------------------
# New manipulation endpoints (Phase 2 — ticket manipulation capability)
# ---------------------------------------------------------------------------

_VALID_STATUSES = {"pending", "in_progress", "done", "blocked"}
_VALID_PRIORITIES = {"low", "medium", "high", "critical"}


class StatusUpdate(BaseModel):
    status: str  # pending | in_progress | done | blocked


class NoteAdd(BaseModel):
    note: str
    author: str = ""


class PriorityUpdate(BaseModel):
    priority: str  # low | medium | high | critical


class AssigneeUpdate(BaseModel):
    assignee: str


@router.patch("/{ticket_id}/status", response_model=TicketResponse)
async def update_ticket_status(ticket_id: str, body: StatusUpdate):
    """Update the status of a ticket."""
    if body.status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of {sorted(_VALID_STATUSES)}",
        )
    tickets = _load_tickets()
    for t in tickets:
        if t["id"] == ticket_id:
            t.setdefault("trace", [])
            t.setdefault("parent_agent", None)
            t.setdefault("priority", "medium")
            t["status"] = body.status
            t["updated_at"] = _now()
            _save_tickets(tickets)
            return TicketResponse(**t)
    raise HTTPException(status_code=404, detail=f"Ticket '{ticket_id}' not found")


@router.post("/{ticket_id}/notes", response_model=TicketResponse)
async def add_ticket_note(ticket_id: str, body: NoteAdd):
    """Append a note to a ticket's activity log."""
    if not body.note or not body.note.strip():
        raise HTTPException(status_code=422, detail="note must not be empty")
    tickets = _load_tickets()
    for t in tickets:
        if t["id"] == ticket_id:
            t.setdefault("trace", [])
            t.setdefault("parent_agent", None)
            t.setdefault("priority", "medium")
            t["trace"].append({
                "ts": _now(),
                "note": body.note.strip(),
                "agent": body.author or None,
            })
            t["updated_at"] = _now()
            _save_tickets(tickets)
            return TicketResponse(**t)
    raise HTTPException(status_code=404, detail=f"Ticket '{ticket_id}' not found")


@router.patch("/{ticket_id}/priority", response_model=TicketResponse)
async def update_ticket_priority(ticket_id: str, body: PriorityUpdate):
    """Update the priority of a ticket."""
    if body.priority not in _VALID_PRIORITIES:
        raise HTTPException(
            status_code=422,
            detail=f"priority must be one of {sorted(_VALID_PRIORITIES)}",
        )
    tickets = _load_tickets()
    for t in tickets:
        if t["id"] == ticket_id:
            t.setdefault("trace", [])
            t.setdefault("parent_agent", None)
            t["priority"] = body.priority
            t["updated_at"] = _now()
            _save_tickets(tickets)
            return TicketResponse(**t)
    raise HTTPException(status_code=404, detail=f"Ticket '{ticket_id}' not found")


@router.patch("/{ticket_id}/assignee", response_model=TicketResponse)
async def update_ticket_assignee(ticket_id: str, body: AssigneeUpdate):
    """Update the assignee of a ticket."""
    if not body.assignee or not body.assignee.strip():
        raise HTTPException(status_code=422, detail="assignee must not be empty")
    tickets = _load_tickets()
    for t in tickets:
        if t["id"] == ticket_id:
            t.setdefault("trace", [])
            t.setdefault("parent_agent", None)
            t.setdefault("priority", "medium")
            t["assigned_agent"] = body.assignee.strip()
            t["updated_at"] = _now()
            _save_tickets(tickets)
            return TicketResponse(**t)
    raise HTTPException(status_code=404, detail=f"Ticket '{ticket_id}' not found")


@router.get("/by-agent/{agent_name}")
async def get_ticket_by_agent(agent_name: str):
    """Return the most recent active ticket for an agent (used by agents for self-tracing)."""
    tickets = _load_tickets()
    matches = [
        t for t in tickets
        if t.get("assigned_agent") == agent_name
        and t.get("status") in ("in_progress", "backlog")
    ]
    if not matches:
        return None
    best = max(matches, key=lambda t: t.get("created_at", ""))
    best.setdefault("trace", [])
    best.setdefault("parent_agent", None)
    return TicketResponse(**best)
