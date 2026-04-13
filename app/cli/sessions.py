"""Session persistence — JSONL-based conversation storage.

Each session is stored as ``app/agents/master/sessions/{session_id}.jsonl``
with one JSON object per line (role + content).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from app.config import settings

_SESSIONS_DIR = settings.agents_dir / "master" / "sessions"


class SessionMeta(NamedTuple):
    id: str
    name: str  # first 60 chars of first user message
    created_at: str
    message_count: int
    model: str


def new_session_id() -> str:
    """Generate a session ID: timestamp + short uuid."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"{ts}-{short}"


def session_path(session_id: str) -> Path:
    return _SESSIONS_DIR / f"{session_id}.jsonl"


def append_message(session_id: str, role: str, content: str) -> None:
    """Append a single message to a session file (sync)."""
    path = session_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"role": role, "content": content}, ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_session(session_id: str) -> list[dict[str, str]]:
    """Read all messages from a session. Returns list of {role, content}."""
    path = session_path(session_id)
    if not path.exists():
        return []
    messages: list[dict[str, str]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                messages.append(json.loads(line))
    return messages


def list_sessions(limit: int = 20) -> list[SessionMeta]:
    """List recent sessions, newest first."""
    if not _SESSIONS_DIR.exists():
        return []

    files = sorted(_SESSIONS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    results: list[SessionMeta] = []

    for f in files[:limit]:
        sid = f.stem
        messages = load_session(sid)
        if not messages:
            continue

        # First user message as name
        first_user = next((m["content"] for m in messages if m["role"] == "user"), "")
        name = first_user[:60].replace("\n", " ")

        # Created at from file mtime (or parse from session id)
        created = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )

        results.append(
            SessionMeta(
                id=sid,
                name=name,
                created_at=created,
                message_count=len(messages),
                model=settings.default_model,
            )
        )

    return results


def latest_session_id() -> str | None:
    """Return the ID of the most recent session, or None."""
    if not _SESSIONS_DIR.exists():
        return None
    files = sorted(_SESSIONS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0].stem if files else None
