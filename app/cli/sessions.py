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
        name = first_user.replace("\n", " ")

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


# ── Per-session compaction checkpoint ─────────────────────────────────────
# When _compact_messages fires, we persist the resulting anchor + facts +
# summary to a sidecar JSON file alongside the session JSONL. On resume,
# master can hydrate from this instead of compacting again, and the UI
# can surface a "session digest" without re-running the LLM call.
#
# Schema (written by BaseAgent._compact_messages → write_summary):
#   {
#     "session_id": "...",
#     "anchor": {"role": "user", "content": "..."},   # first user msg
#     "synth": {"role": "user", "content": "..."},    # facts JSON + summary
#     "compacted_at": "ISO-8601 UTC",
#     "model_used": "claude-haiku-4-5-...",
#     "msg_count_at_compact": 34,                     # for resume diffing
#     "schema_version": 1,
#   }
#
# Size cap + rotation: a runaway session could keep appending, so we cap
# at settings.session_summary_max_chars and rotate to .summary.N.json.bak.

_SUMMARY_SCHEMA_VERSION = 1


def summary_path(session_id: str) -> Path:
    return _SESSIONS_DIR / f"{session_id}.summary.json"


def read_summary(session_id: str) -> dict | None:
    """Load the per-session compaction checkpoint, or None if absent/invalid."""
    path = summary_path(session_id)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def write_summary(
    session_id: str,
    anchor: dict,
    synth: dict,
    msg_count_at_compact: int,
    model_used: str = "",
) -> None:
    """Persist a compaction checkpoint to disk (atomic write).

    Best-effort: any I/O error is swallowed — losing the sidecar is not
    catastrophic (the next compact will rebuild it). All string fields
    are scrubbed for secrets before writing.
    """
    try:
        from app.utils.secrets import scrub
    except Exception:  # pragma: no cover — secrets module always available in prod
        def scrub(s: str) -> str:
            return s

    cap = int(getattr(settings, "session_summary_max_chars", 32000))
    payload = {
        "session_id": session_id,
        "anchor": {
            "role": anchor.get("role", "user"),
            "content": scrub(str(anchor.get("content", "")))[:cap],
        },
        "synth": {
            "role": synth.get("role", "user"),
            "content": scrub(str(synth.get("content", "")))[:cap],
        },
        "compacted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model_used": model_used,
        "msg_count_at_compact": msg_count_at_compact,
        "schema_version": _SUMMARY_SCHEMA_VERSION,
    }
    path = summary_path(session_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Rotate any prior summary into a .bak before overwriting — keeps the
        # last-good version recoverable if a faulty compact produces garbage.
        if path.exists():
            try:
                bak = path.with_suffix(".prev.json.bak")
                bak.write_bytes(path.read_bytes())
            except OSError:
                pass  # rotation is best-effort
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        # Best-effort: a write failure should not crash the compact path.
        return
