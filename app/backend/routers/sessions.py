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
