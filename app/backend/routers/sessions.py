"""Session helpers — currently just summarization.

Sessions are stored client-side in localStorage (the frontend's `yapoc-sessions`
Zustand store). The backend does not persist sessions. This router exposes
stateless helpers that operate on a session payload sent by the client.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.utils.adapters import AgentConfig, Message, get_adapter

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


__all__ = ["router"]
