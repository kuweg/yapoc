"""Session helpers — summarization + channel dashboard endpoints.

Sessions are stored client-side in localStorage (the frontend's `yapoc-sessions`
Zustand store) and on disk (CLI sessions as JSONL files). This router exposes
stateless helpers that operate on session payloads sent by the client, plus
endpoints for the Channel Dashboard that aggregate sessions from CLI files
and the task_queue database table.
"""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.cli.sessions import list_sessions, load_session, SessionMeta
from app.config import settings
from app.utils.adapters import AgentConfig, Message, get_adapter
from app.utils.db import get_db

router = APIRouter(prefix="/sessions", tags=["sessions"])


class _IncomingMessage(BaseModel):
    role: str
    content: str


class SummarizeRequest(BaseModel):
    messages: list[_IncomingMessage] = Field(default_factory=list)


class SummarizeResponse(BaseModel):
    summary: str


_SYSTEM_PROMPT = (
    "You compress chat transcripts so a fresh conversation can resume with the "
    "right context. Write a concise summary of the conversation below in under "
    "250 words. Capture: (1) the user's intent and goals, (2) key decisions or "
    "conclusions reached, (3) any open questions or pending follow-ups. Use "
    "plain prose — no headers, no lists, no quoted excerpts. Refer to the "
    "participants as 'the user' and 'the assistant'."
)


def _render_transcript(messages: list[_IncomingMessage]) -> str:
    lines: list[str] = []
    for m in messages:
        role = m.role.strip().lower() or "user"
        lines.append(f"[{role}]\n{m.content.strip()}")
    return "\n\n".join(lines)


class SessionDigestResponse(BaseModel):
    """Server-side compaction checkpoint for a session. ``available=False``
    when the session has never been compacted (no sidecar on disk)."""
    session_id: str
    available: bool = False
    anchor: dict | None = None
    synth: dict | None = None
    compacted_at: str = ""
    model_used: str = ""
    msg_count_at_compact: int = 0
    schema_version: int = 0


@router.get("/{session_id}/digest", response_model=SessionDigestResponse)
async def get_session_digest(session_id: str) -> SessionDigestResponse:
    """Return the per-session compaction checkpoint, if any.

    Written by ``BaseAgent._compact_messages`` once a session crosses the
    auto-compact threshold. UI can surface it as a "session digest" panel
    so the user can see what's been compressed without re-running the LLM.
    """
    # Local import keeps the CLI module out of import-time cycles.
    from app.cli.sessions import read_summary

    data = read_summary(session_id)
    if not data:
        return SessionDigestResponse(session_id=session_id, available=False)
    return SessionDigestResponse(
        session_id=session_id,
        available=True,
        anchor=data.get("anchor"),
        synth=data.get("synth"),
        compacted_at=str(data.get("compacted_at", "")),
        model_used=str(data.get("model_used", "")),
        msg_count_at_compact=int(data.get("msg_count_at_compact", 0)),
        schema_version=int(data.get("schema_version", 0)),
    )


@router.post("/summarize", response_model=SummarizeResponse)
async def summarize(req: SummarizeRequest) -> SummarizeResponse:
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages must be non-empty")

    # Prefer the cheap compaction model on Anthropic (same one used by
    # BaseAgent's auto-compact path). Fall back to whichever adapter the
    # project's default points at.
    if settings.anthropic_api_key:
        config = AgentConfig(
            adapter="anthropic",
            model=settings.context_compact_model,
            temperature=0.2,
            max_tokens=1024,
        )
    else:
        config = AgentConfig(
            adapter=settings.default_adapter,
            model=settings.default_model,
            temperature=0.2,
            max_tokens=1024,
        )

    adapter = get_adapter(config)
    transcript = _render_transcript(req.messages)
    user_msg = (
        "Summarize this conversation. Output ONLY the summary text, with no "
        "preamble.\n\n---\n\n" + transcript
    )

    try:
        summary = await adapter.complete(
            system_prompt=_SYSTEM_PROMPT,
            user_message=user_msg,
            history=[],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"summarization failed: {exc}") from exc

    return SummarizeResponse(summary=(summary or "").strip())


# ── Channel Dashboard models ──────────────────────────────────────────────


class SessionInfo(BaseModel):
    id: str
    name: str
    createdAt: str
    messageCount: int
    source: str
    preview: str  # first 100 chars of first user message


class ChannelInfo(BaseModel):
    source: str
    count: int
    sessions: list[SessionInfo]


class ChannelsResponse(BaseModel):
    channels: list[ChannelInfo]


class ChannelSessionMessagesResponse(BaseModel):
    session_id: str
    source: str
    messages: list[dict]  # list of {role, content}


# ── Channel Dashboard endpoints ───────────────────────────────────────────


def _get_preview_from_task_queue(db, session_id: str, source: str) -> str:
    """Return first 100 chars of the first user message for a session."""
    row = db.execute(
        "SELECT prompt FROM task_queue WHERE session_id = ? AND source = ? ORDER BY created_at ASC LIMIT 1",
        (session_id, source),
    ).fetchone()
    if row and row["prompt"]:
        return row["prompt"][:100]
    return ""


def _get_preview_from_cli(session_id: str) -> str:
    """Return first 100 chars of the first user message from a CLI session."""
    messages = load_session(session_id)
    for m in messages:
        if m.get("role") == "user":
            return m["content"][:100]
    return ""


@router.get("/channels", response_model=ChannelsResponse)
async def get_channels() -> ChannelsResponse:
    """Return sessions grouped by source/channel.

    Aggregates CLI sessions (from disk) and UI/Telegram sessions (from
    the task_queue database table) into channel groups.
    """
    db = get_db()

    # 1. Collect CLI sessions — these are source="cli"
    cli_sessions = list_sessions(limit=100)
    cli_channel = ChannelInfo(
        source="cli",
        count=len(cli_sessions),
        sessions=[
            SessionInfo(
                id=s.id,
                name=s.name,
                createdAt=s.created_at,
                messageCount=s.message_count,
                source="cli",
                preview=_get_preview_from_cli(s.id),
            )
            for s in cli_sessions
        ],
    )

    # 2. Query task_queue for all non-CLI sources (UI, Telegram, etc.)
    rows = db.execute(
        "SELECT DISTINCT source, session_id FROM task_queue WHERE source != 'cli' ORDER BY source"
    ).fetchall()

    # Group session_ids by source
    source_sessions: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        source_sessions[row["source"]].add(row["session_id"])

    # 3. Build channel info for each source from task_queue
    channels: list[ChannelInfo] = [cli_channel]

    for source, session_ids in sorted(source_sessions.items()):
        session_infos: list[SessionInfo] = []
        for sid in sorted(session_ids):
            # Count messages for this session in task_queue
            count_row = db.execute(
                "SELECT COUNT(*) as cnt FROM task_queue WHERE session_id = ? AND source = ?",
                (sid, source),
            ).fetchone()
            msg_count = count_row["cnt"] if count_row else 0

            # Get the first prompt as the session name
            name_row = db.execute(
                "SELECT prompt FROM task_queue WHERE session_id = ? AND source = ? ORDER BY created_at ASC LIMIT 1",
                (sid, source),
            ).fetchone()
            name = ""
            if name_row and name_row["prompt"]:
                name = name_row["prompt"].replace("\n", " ")[:60]

            # Get created_at from the earliest task
            created_row = db.execute(
                "SELECT created_at FROM task_queue WHERE session_id = ? AND source = ? ORDER BY created_at ASC LIMIT 1",
                (sid, source),
            ).fetchone()
            created_at = created_row["created_at"] if created_row else ""

            preview = _get_preview_from_task_queue(db, sid, source)

            session_infos.append(
                SessionInfo(
                    id=sid,
                    name=name,
                    createdAt=created_at,
                    messageCount=msg_count,
                    source=source,
                    preview=preview,
                )
            )

        channels.append(
            ChannelInfo(
                source=source,
                count=len(session_infos),
                sessions=session_infos,
            )
        )

    return ChannelsResponse(channels=channels)


@router.get("/channel/{source}/{session_id}", response_model=ChannelSessionMessagesResponse)
async def get_channel_session_messages(source: str, session_id: str) -> ChannelSessionMessagesResponse:
    """Return full session messages for a given channel + session ID."""
    if source == "cli":
        messages = load_session(session_id)
        if not messages:
            raise HTTPException(
                status_code=404,
                detail=f"CLI session '{session_id}' not found",
            )
        return ChannelSessionMessagesResponse(
            session_id=session_id,
            source=source,
            messages=messages,
        )

    if source == "ui":
        raise HTTPException(
            status_code=404,
            detail="UI sessions are stored client-side in localStorage and are not accessible from the backend",
        )

    # For telegram or any other source: query task_queue
    db = get_db()
    rows = db.execute(
        "SELECT prompt, result, status, created_at FROM task_queue "
        "WHERE session_id = ? AND source = ? ORDER BY created_at ASC",
        (session_id, source),
    ).fetchall()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found for source '{source}'",
        )

    messages: list[dict] = []
    for row in rows:
        messages.append({"role": "user", "content": row["prompt"]})
        if row["result"]:
            messages.append({"role": "assistant", "content": row["result"]})

    return ChannelSessionMessagesResponse(
        session_id=session_id,
        source=source,
        messages=messages,
    )


__all__ = ["router"]
